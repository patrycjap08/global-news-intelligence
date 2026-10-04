from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import ai_pipeline as ai
import rebuild_topic_updates as rebuild
from test_rebuild_topic_updates import fixtures, Client


def payload():
    # Facts from the Flydubai example: full history, including spelling variations.
    return {
        'previous_aggregation': {
            'base_summary': {'summary_pl': 'Samolot wylądował w Tabuku. Pasażerowie obezwładnili napastnika.',
                             'facts': [{'text_pl': 'Trwa śledztwo.', 'article_ids': ['old']}]},
            'prior_updates': [
                {'new_information_pl': 'Kapitan Smit Machchhar otworzył drzwi kokpitu. Flydubai zawiesiło loty do Izraela.'},
                {'new_information_pl': 'Netanjahu i Modi pochwalili kapitana. Yaniv Hayun pomógł obezwładnić napastnika.'},
            ],
        },
        'new_articles': [{'article_id': 'new', 'body_original':
            'Samolot wylądował w Tabuku. Smit Machchhar otworzył drzwi kokpitu. '
            'ABC News podaje 182 pasażerów. Flydubai zawiesiło loty do Izraela.'}],
    }


def fact(text, article_id='new'):
    return {'text_pl': text, 'article_ids': [article_id], 'why_new_pl': 'Kandydat do niezależnego sprawdzenia.'}


def verdict(index, keep):
    return {'fact_index': index, 'keep': keep, 'reason_pl': 'Nowa liczba w artykule.' if keep else 'Fakt obecny w syntezie lub wcześniejszej aktualizacji.'}


class AtomicUpdateTests(unittest.TestCase):
    def test_invalid_evidence_is_retried_with_feedback_then_audited(self):
        with patch.object(ai, 'call_openai', side_effect=[
            {'facts': [fact('Nowy fakt.', 'old')]},
            {'facts': [fact('Nowy fakt.')]},
            {'verdicts': {'0': {'keep': True, 'reason_pl': 'Potwierdzony nowy fakt.'}}},
        ]) as model:
            result = ai.generate_topic_update(payload(), 'model')
        self.assertEqual(model.call_count, 3)
        self.assertIn('artykuł spoza bieżącej paczki', model.call_args_list[1].args[0])
        self.assertEqual(result['update']['new_information_pl'], 'Nowy fakt.')

    def test_missing_verdict_is_retried_without_repeating_selection(self):
        with patch.object(ai, 'call_openai', side_effect=[
            {'facts': [fact('Nowy fakt.'), fact('Znany fakt.')]},
            {'verdicts': {'0': {'keep': True, 'reason_pl': 'Nowy.'}}},
            {'verdicts': {'0': {'keep': True, 'reason_pl': 'Nowy.'}, '1': {'keep': False, 'reason_pl': 'W syntezie.'}}},
        ]) as model:
            result = ai.generate_topic_update(payload(), 'model')
        self.assertEqual(model.call_count, 3)
        self.assertEqual(model.call_args_list[1].args[1], model.call_args_list[2].args[1])
        self.assertIn('brakuje decyzji', model.call_args_list[2].args[0])
        self.assertEqual(result['update']['new_information_pl'], 'Nowy fakt.')

    def test_mixed_article_produces_only_one_approved_new_fact(self):
        original = payload()
        facts = [fact('Samolot wylądował w Tabuku.'), fact('ABC News podaje 182 pasażerów.'),
                 fact('Smit Machchhar otworzył drzwi kokpitu.'), fact('Flydubai zawiesiło loty do Izraela.')]
        with patch.object(ai, 'call_openai', side_effect=[{'facts': facts},
                          {'verdicts': [verdict(3, False), verdict(1, True), verdict(0, False), verdict(2, False)]}]) as model:
            result = ai.generate_topic_update(original, 'model')
        self.assertEqual(model.call_count, 2)  # no prose rewrite after filtering
        evidence_schema = model.call_args_list[0].kwargs['response_schema']['properties']['facts']['items']['properties']['article_ids']
        self.assertEqual(evidence_schema['items']['enum'], ['new'])
        audit_schema = model.call_args_list[1].kwargs['response_schema']['properties']['verdicts']
        self.assertEqual(audit_schema['required'], ['0', '1', '2', '3'])
        self.assertEqual(model.call_args_list[1].args[1]['previous_aggregation'], original['previous_aggregation'])
        self.assertEqual(model.call_args_list[1].args[1]['new_articles'], original['new_articles'])
        self.assertEqual(result['update']['new_information_pl'], 'ABC News podaje 182 pasażerów.')
        self.assertEqual(result['update']['what_changed_pl'], '')
        self.assertEqual(result['update']['status'], 'NEW_INFORMATION')
        self.assertEqual(result['summary_pl'], original['previous_aggregation']['base_summary']['summary_pl'])
        self.assertEqual(payload(), original)

    def test_repeated_only_facts_result_in_no_information(self):
        with patch.object(ai, 'call_openai', side_effect=[
            {'facts': [fact('Smit Machchhar otworzył drzwi kokpitu.'), fact('Flydubai zawiesiło loty do Izraela.')]},
            {'verdicts': [verdict(0, False), verdict(1, False)]},
        ]):
            result = ai.generate_topic_update(payload(), 'model')
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertFalse(result['update']['is_update'])
        self.assertEqual(result['update']['new_information_pl'], '')
        self.assertEqual(result['update']['new_article_ids'], ['new'])

    def test_empty_selection_needs_no_audit(self):
        with patch.object(ai, 'call_openai', return_value={'facts': []}) as model:
            result = ai.generate_topic_update(payload(), 'model')
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')

    def test_generic_confirmation_is_filtered_before_audit(self):
        with patch.object(ai, 'call_openai', return_value={'facts': [fact('Kolejne artykuły potwierdzają wcześniejsze dane.')]}) as model:
            result = ai.generate_topic_update(payload(), 'model')
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')

    def test_untraceable_facts_abort_before_audit(self):
        for candidate in [fact('Nowa informacja.', 'old'), fact('', 'new'),
                          {'text_pl': 'Nowy fakt.', 'article_ids': ['new'], 'why_new_pl': ''}]:
            with self.subTest(candidate=candidate), patch.object(ai, 'call_openai', return_value={'facts': [candidate]}) as model:
                with self.assertRaises(ValueError):
                    ai.generate_topic_update(payload(), 'model')
                self.assertEqual(model.call_count, 2)

    def test_incomplete_or_invalid_audit_never_accepts_unchecked_text(self):
        for decisions in [[], [verdict(9, True)], [verdict(True, True)],
                          [{'fact_index': 0, 'keep': 'true', 'reason_pl': 'New'}],
                          [{'fact_index': 0, 'keep': True, 'reason_pl': ''}]]:
            with self.subTest(decisions=decisions), patch.object(ai, 'call_openai', side_effect=[
                {'facts': [fact('ABC News podaje 182 pasażerów.')]}, {'verdicts': decisions}, {'verdicts': decisions},
            ]):
                with self.assertRaises(ValueError):
                    ai.generate_topic_update(payload(), 'model')

    def test_duplicate_audit_indices_abort(self):
        with patch.object(ai, 'call_openai', side_effect=[
            {'facts': [fact('Pierwszy fakt.'), fact('Drugi fakt.')]},
            {'verdicts': [verdict(0, True), verdict(0, True)]},
            {'verdicts': [verdict(0, True), verdict(0, True)]},
        ]):
            with self.assertRaises(ValueError):
                ai.generate_topic_update(payload(), 'model')

    def test_identical_approved_facts_are_not_repeated(self):
        with patch.object(ai, 'call_openai', side_effect=[
            {'facts': [fact('ABC News podaje 182 pasażerów.'), fact('ABC News podaje 182 pasażerów.')]},
            {'verdicts': [verdict(0, True), verdict(1, True)]},
        ]):
            result = ai.generate_topic_update(payload(), 'model')
        self.assertEqual(result['update']['new_information_pl'], 'ABC News podaje 182 pasażerów.')

    def test_rebuild_is_chronological_and_logs_titles(self):
        job = fixtures()
        candidates = [
            {'facts': [fact('Podpisano porozumienie.', 'a1')]},
            {'verdicts': [verdict(0, True)]},
            {'facts': [fact('Podpisano porozumienie.', 'a2')]},
            {'verdicts': [verdict(0, False)]},
        ]
        client = Client()
        with TemporaryDirectory() as directory, patch.object(ai, 'call_openai', side_effect=candidates) as model, patch('sys.stdout', new_callable=StringIO) as output:
            self.assertEqual(rebuild.execute({'jobs': [job]}, Path(directory) / 'state.json', client, 'model'), 0)
            logs = output.getvalue()
        self.assertEqual(model.call_count, 4)
        previous = model.call_args_list[2].args[1]['previous_aggregation']
        self.assertEqual(previous['prior_updates'][0]['new_information_pl'], 'Podpisano porozumienie.')
        updates = job['replacement']['current']['summary']['updates']
        self.assertEqual([row['status'] for row in updates], ['NEW_INFORMATION', 'NO_NEW_INFORMATION'])
        self.assertEqual([row['new_article_ids'] for row in updates], [['a1'], ['a2', 'a3']])
        self.assertIn(job['title'] + ': aktualizacja 1/2', logs)
        self.assertIn('Zapisano ' + job['title'], logs)
        self.assertNotIn(job['topic_id'] + ':', logs)
        self.assertIn('widocznych po naprawie: 1', logs)

    def test_audit_failure_in_second_update_prevents_whole_topic_save(self):
        job = fixtures()
        client = Client()
        original = deepcopy(job['current'])
        with TemporaryDirectory() as directory, patch.object(ai, 'call_openai', side_effect=[
            {'facts': [fact('Pierwszy fakt.', 'a1')]}, {'verdicts': [verdict(0, True)]},
            {'facts': [fact('Drugi fakt.', 'a2')]}, RuntimeError('Audit API failed'),
        ]), patch('sys.stdout', new_callable=StringIO) as output:
            self.assertEqual(rebuild.execute({'jobs': [job]}, Path(directory) / 'state.json', client, 'model'), 1)
            self.assertIn('Nie zapisano ' + job['title'], output.getvalue())
        self.assertEqual(client.calls, [])
        self.assertEqual(job['current'], original)
        self.assertNotIn('replacement', job)

    def test_common_entrypoint_uses_fact_selection_only_for_updates(self):
        with patch.object(ai, 'generate_topic_update', return_value={'update': {}}) as update, patch.object(ai, 'call_openai', return_value={}) as synthesis:
            ai.generate_summary_response(payload(), 'model')
            update.assert_called_once()
            synthesis.assert_not_called()
            ai.generate_summary_response({'previous_aggregation': None, 'new_articles': []}, 'model')
            synthesis.assert_called_once()
            self.assertIs(synthesis.call_args.kwargs['response_schema'], ai.SUMMARY_RESPONSE_SCHEMA)


if __name__ == '__main__':
    unittest.main()
