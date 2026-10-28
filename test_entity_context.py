"""Real Witkoff publication: roles survive writing rejection without a retry."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonschema
import ai_pipeline as ai
import editorial_integrity as integrity
import perspective_summaries as p
from structured_outputs import check_response_schema
import test_summary_queue as queue_tests
from test_topic_titles import FakeMergeClient
from test_writing_fixtures import article_response, paired_article_response

DATA = json.loads(Path(__file__).with_name('test_data').joinpath('witkoff_missing_context_20261021.json').read_text())


def previous():
    return {'base_summary': copy.deepcopy(DATA['current_summary']),
            'current_summary': copy.deepcopy(DATA['current_summary']),
            'perspective_state': {'facts': copy.deepcopy(DATA['facts']),
                                  'perspective_facts': copy.deepcopy(DATA['facts'])},
            'processed_article_ids': [a['article_id'] for a in DATA['articles']]}


def legacy_response(*, reject=False):
    facts = DATA['facts']
    result = {'situation_context': {'text_pl': 'Witkoff uczestniczy w amerykańskich zabiegach dyplomatycznych dotyczących zakończenia wojny w Ukrainie. Spotkaniom z rosyjskimi władzami towarzyszą rozmowy o uwalnianiu przetrzymywanych obywateli USA, stąd znaczenie podziękowania Putinowi za zwolnienie Hubbarda.', 'basis': 'SUPPLIED_MATERIAL'}, 'entity_context': [
        {'mentions': ['Thom Tillis', 'Tillis'], 'description_pl': 'republikański senator USA', 'basis': 'SUPPLIED_MATERIAL'},
        {'mentions': ['Steve Witkoff', 'Witkoffa', 'Witkoff'], 'description_pl': 'specjalny wysłannik prezydenta USA', 'basis': 'SUPPLIED_MATERIAL'}],
        'paragraphs': [
            {'text_pl': 'Thom Tillis skrytykował Witkoffa za nazwanie Putina humanitarystą.',
             'fact_ids': [facts[0]['fact_id']], 'context_spans': []},
            {'text_pl': 'Witkoff spotkał się z Putinem w Petersburgu i podziękował mu za zwolnienie Stephena Hubbarda, 74-letniego obywatela USA przetrzymywanego od 2022 r.',
             'fact_ids': [facts[i]['fact_id'] for i in (4, 8, 9)], 'context_spans': []}]}
    if reject:
        result['paragraphs'] = [{'text_pl': 'Thom Tillis skrytykował Witkoffa w 2099 roku.',
                                  'fact_ids': [facts[0]['fact_id']], 'context_spans': []}]
        result['entity_context'].append({'mentions': ['Hubbard', 'Stephena Hubbarda'],
            'description_pl': 'obywatel USA uwolniony z rosyjskiego więzienia', 'basis': 'SUPPLIED_MATERIAL'})
    return result


def response(*, reject=False):
    old = legacy_response()
    senator = '(republikański senator USA)'
    envoy = '(specjalny wysłannik prezydenta USA)'
    first = f'Thom Tillis {senator} skrytykował Witkoffa {envoy} za nazwanie Putina humanitarystą.'
    if reject:
        first = f'Thom Tillis {senator} skrytykował Witkoffa {envoy} w 2099 roku.'
    paragraphs = [{'text_pl': first, 'fact_ids': [DATA['facts'][0]['fact_id']]},
                  {'text_pl': old['situation_context']['text_pl'], 'fact_ids': []}]
    if not reject:
        paragraphs.append(old['paragraphs'][1])
    return article_response(paragraphs, [
        {'text_pl': senator, 'basis': 'SUPPLIED_MATERIAL', 'kind': 'ENTITY'},
        {'text_pl': envoy, 'basis': 'SUPPLIED_MATERIAL', 'kind': 'ENTITY'},
        {**old['situation_context'], 'kind': 'SITUATION'}])


class EntityContextTests(unittest.TestCase):
    def payload(self, stored):
        return {'topic': {'topic_id': DATA['topic']['topic_id'], 'working_title_pl': DATA['topic']['headline_pl']},
                'all_articles': DATA['articles'], 'new_article_ids': [], 'previous_aggregation': stored}

    def test_actual_contextless_fact_copy_is_eligible_once(self):
        self.assertTrue(integrity.needs_inline_context(DATA['current_summary'], DATA['facts']))
        current = {**DATA['current_summary'], 'inline_context_version': integrity.INLINE_CONTEXT_VERSION}
        self.assertFalse(integrity.needs_inline_context(current, DATA['facts']))
        for current in ({**DATA['current_summary'], 'narrative_context': [{'text_pl': 'objaśnienie'}]},
                        {**DATA['current_summary'], 'summary_pl': 'Senator USA skrytykował wypowiedź dyplomaty.'}):
            self.assertFalse(integrity.needs_inline_context(current, DATA['facts']))

    def test_one_writer_explains_people_and_circumstances_without_new_extraction(self):
        stored = previous()
        calls = []
        def call(instructions, data, schema, name):
            calls.append(name)
            self.assertEqual(name, 'perspective_summary')
            check_response_schema(schema)
            jsonschema.validate(paired_article_response(response()), schema)
            passages = ' '.join(t for s in data['context_sources'] for t in s['passages'])
            self.assertIn('Senator republikanów Thom Tillis', passages)
            self.assertIn('specjalny wysłannik prezydenta USA', passages)
            self.assertIn('main_facts', data)
            return paired_article_response(response())
        result = p.generate(self.payload(stored), call, ai.normalize_generated_text, allow_omissions=True)
        self.assertEqual(calls, ['perspective_summary'])
        self.assertIn('Thom Tillis (republikański senator USA)', result['summary_pl'])
        self.assertIn('Witkoffa (specjalny wysłannik prezydenta USA)', result['summary_pl'])
        self.assertIn('Petersburgu', result['summary_pl'])
        self.assertIn('przetrzymywanego od 2022', result['summary_pl'])
        self.assertEqual(len(result['narrative_context']), 3)
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(result['quality_report']['read_articles'], 0)
        self.assertFalse(result['quality_report']['narrative_fallback'])
        self.assertFalse(any('republikański senator' in f['text_pl'] for f in result['facts']))
        stored['current_summary'] = result
        p.generate(self.payload(stored), lambda *args: self.fail('No repeated writing'), ai.normalize_generated_text, allow_omissions=True)

    def test_rejected_prose_uses_facts_without_assembling_roles_or_buying_a_repair(self):
        calls = []
        def call(*args):
            calls.append(args[-1])
            return response(reject=True)
        stored = previous()
        result = p.generate(self.payload(stored), call, ai.normalize_generated_text, allow_omissions=True)
        self.assertEqual(calls, ['perspective_summary'])
        self.assertNotIn('2099', result['summary_pl'])
        self.assertIn('Thom Tillis', result['summary_pl'])
        self.assertNotIn('Hubbard (obywatel USA uwolniony z rosyjskiego więzienia)', result['summary_pl'])
        self.assertNotIn('(republikański senator USA)', result['summary_pl'])
        self.assertTrue(result['quality_report']['narrative_fallback'])
        self.assertEqual(result['quality_report']['writing_validation']['rejections'],
                         {'event_not_supported_by_cited_facts': 1})
        self.assertEqual(result['quality_report']['context_additions_accepted'], 0)
        self.assertEqual(result['facts'], DATA['facts'])
        stored['current_summary'] = result
        p.generate(self.payload(stored), lambda *args: self.fail('No repair loop'), ai.normalize_generated_text, allow_omissions=True)

    def test_only_known_entities_get_inline_context_once_without_changing_ids(self):
        raw = legacy_response()
        raw['entity_context'].extend([
            {'mentions': ['Nieobecna osoba'], 'description_pl': 'zupełnie inna osoba', 'basis': 'GENERAL_KNOWLEDGE'},
            copy.deepcopy(raw['entity_context'][0]),
            {'mentions': ['Putin'], 'description_pl': 'zły opis', 'basis': 'INVALID'}])
        written = p.safe_inline_written(raw, DATA['facts'])
        ids = [p['fact_ids'][:] for p in written['paragraphs']]
        p.insert_entity_context(written, DATA['facts'])
        self.assertEqual(len(written['narrative_context']), 2)
        self.assertEqual(ids, [p['fact_ids'] for p in written['paragraphs']])
        self.assertNotIn('Nieobecna', str(written['paragraphs']))

    def test_complete_schema_failure_or_truncation_does_not_assemble_roles_from_rejected_text(self):
        raw = response(reject=True)
        raw['paragraph_sources'][0]['fact_ids'] = ['unknown-fact']
        for status in ('completed', 'incomplete'):
            with self.subTest(status=status):
                error = ai.AIResponseParseError('Invalid paragraph reference', json.dumps(raw))
                error.response_details = {'status': status}
                with patch.object(ai, 'call_openai', side_effect=error) as request, patch.object(ai, 'log'):
                    result = ai.generate_summary_response(self.payload(previous()), 'gpt-5-nano')
                request.assert_called_once()
                self.assertEqual(result['quality_report']['api_calls'], 1)
                self.assertTrue(result['quality_report']['narrative_fallback'])
                self.assertNotIn('2099', result['summary_pl'])
                self.assertNotIn('unknown-fact', str(result['facts']))
                self.assertNotIn('republikański senator USA', result['summary_pl'])

    def test_new_synthesis_and_fallback_do_not_add_publisher_labels(self):
        for rejected in (False, True):
            with self.subTest(rejected=rejected):
                raw = response(reject=rejected)
                raw['summary_pl'] = 'Według WP: ' + raw['summary_pl']
                result = p.generate(self.payload(previous()), lambda *args: raw,
                                    ai.normalize_generated_text, allow_omissions=True)
                self.assertNotIn('Według WP:', result['summary_pl'])
                self.assertNotIn('Według WP:', result['topic']['what_happened_one_sentence_pl'])
                self.assertIn('Tillis', result['summary_pl'])
                self.assertEqual(result['facts'], DATA['facts'])
        self.assertEqual(integrity.without_publisher_prefixes(
            'Według agencji PAP: Minister powiedział, że rozmowy trwają.\n\nWedług Onet: Zapadła decyzja.', ['PAP', 'Onet']),
            'Minister powiedział, że rozmowy trwają.\n\nZapadła decyzja.')
        self.assertEqual(integrity.without_publisher_prefixes(
            'Według lekarza: Pacjent wymaga leczenia.', ['PAP']),
            'Według lekarza: Pacjent wymaga leczenia.')

    def test_queue_and_persistence_rewrite_old_fallback_but_never_reread_it(self):
        topic = {**DATA['topic'], 'last_seen_at': '2026-10-07T12:00:00Z'}
        tid = topic['topic_id']
        rows = [(a['article_id'], a['source_id'], a['source_profile']) for a in DATA['articles']]
        links = [{'topic_id': tid, 'article_id': a[0]} for a in rows]
        summaries = [{'topic_id': tid, 'version': 1, 'summary': previous(), 'updated_at': '2026-10-07T11:00:00Z'}]
        stats, generate, persist, _ = queue_tests.SummaryQueueTests().run_queue([topic], rows, links, summaries)
        self.assertEqual(stats['summaries'], 1)
        generate.assert_called_once()
        self.assertEqual(persist.call_args.kwargs['new_article_ids'], [])
        with patch.object(ai, 'call_openai', return_value=response()) as request, patch.object(ai, 'log'):
            result = ai.generate_summary_response(self.payload(previous()), 'gpt-5-nano')
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['retry_limit'], 1)
        client = FakeMergeClient([], [], [])
        ai.persist_summary(client, topic_id=tid, run_id='test', model='fake', summary=result,
                           summary_hash='h', previous_row=summaries[0], new_article_ids=[])
        saved = next(items[0]['summary'] for table, items, _ in client.upserts if table == 'topic_summaries')
        self.assertIn('republikański senator', saved['current_summary']['summary_pl'])
        self.assertEqual(saved['current_summary']['inline_context_version'], integrity.INLINE_CONTEXT_VERSION)
        self.assertEqual(saved['current_summary']['situation_context_version'], integrity.SITUATION_CONTEXT_VERSION)
        self.assertIsNone(saved['current_summary']['situation_context'])
        self.assertTrue(any(s.get('kind') == 'SITUATION' for s in saved['current_summary']['narrative_context']))
        summaries[0]['summary'] = saved
        stats, generate, _, _ = queue_tests.SummaryQueueTests().run_queue([topic], rows, links, summaries)
        self.assertEqual(stats['summaries'], 0)
        generate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
