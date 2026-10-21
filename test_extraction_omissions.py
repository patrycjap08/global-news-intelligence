import copy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import jsonschema

import ai_pipeline as ai
import perspective_summaries as p
from test_perspective_summaries import article, extraction, fact, coverage_reply
from test_perspective_validation_recovery import written
from test_topic_titles import FakeMergeClient


class ExtractionOmissionTests(unittest.TestCase):
    def payload(self, count=8):
        rows = [{**article(f'a{i}', 'CENTER'), 'body_original': f'Pełny artykuł {i}. ' * 100}
                for i in range(count)]
        known = p.route_facts({'facts': [fact('Znany fakt.', ['a0'], kind='FACT')]},
                              rows, [], ai.normalize_generated_text)[1]
        base = {'perspective_version': 1, 'summary_pl': 'Zachowana publikacja.',
                'general_context': {'text_pl': 'Zachowane tło.'}, 'perspective_facts': known}
        return {'topic': {'working_title_pl': '[Polska] Wydarzenie'}, 'all_articles': rows,
                'new_article_ids': [a['article_id'] for a in rows[1:]],
                'previous_aggregation': {'base_summary': base}}

    def run_sdk(self, payload, answer):
        calls = []
        def request(**settings):
            fmt = settings['text']['format']
            data = json.JSONDecoder().raw_decode(settings['input'])[0]
            calls.append((fmt['name'], data))
            value = answer(fmt, data)
            if isinstance(value, SimpleNamespace):
                return value
            for a in data.get('all_articles', []):
                for f in value.get('article_results', {}).get(a['article_id'], {}).get('facts', []):
                    f.setdefault('evidence_quote', a['body_original'].split('.')[0] + '.')
                    f.setdefault('attribution', '')
            return SimpleNamespace(status='completed', usage=None, output_text=json.dumps(value, ensure_ascii=False))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('openai.OpenAI') as sdk, patch.object(ai, 'log') as log:
            sdk.return_value.responses.create.side_effect = request
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        return result, calls, log

    def test_seven_omitted_articles_cost_no_repair_and_are_not_automatically_requeued(self):
        payload = self.payload()
        original = copy.deepcopy(payload)
        known = payload['previous_aggregation']['base_summary']['perspective_facts'][0]
        def answer(fmt, data):
            self.assertEqual(fmt['name'], 'perspective_facts')
            reply = coverage_reply(extraction([
                fact('', ['a0'], known['fact_id'], reason='', kind='FACT')], data['all_articles']))
            for aid, entry in reply['article_results'].items():
                if aid != 'a0':
                    entry['no_relevant_facts_reason_pl'] = '' if aid != 'a1' else 'Brak nowych informacji.'
            return reply
        result, calls, log = self.run_sdk(payload, answer)
        self.assertEqual([name for name, _ in calls], ['perspective_facts'])
        self.assertEqual([a['body_original'] for a in calls[0][1]['all_articles']],
                         [a['body_original'] for a in payload['all_articles'][1:]])
        self.assertEqual(result['perspective_facts'][0]['article_ids'], ['a0'])
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(result['summary_pl'], 'Zachowana publikacja.')
        self.assertEqual(payload, original)
        self.assertTrue(any('artykułów bez użytecznych przypisań: 7' in str(c) for c in log.call_args_list))
        client = FakeMergeClient([], [], [])
        base = payload['previous_aggregation']['base_summary']
        ai.persist_summary(client, topic_id='t', run_id='r', model='fake', summary=result,
            summary_hash='h', previous_row={'version': 1, 'summary': {'base_summary': base,
                'updates': [], 'processed_article_ids': ['a0']}}, new_article_ids=payload['new_article_ids'])
        saved = next(items[0] for table, items, _ in client.upserts if table == 'topic_summaries')
        self.assertEqual(set(saved['summary']['processed_article_ids']), {a['article_id'] for a in payload['all_articles']})
        self.assertEqual(saved['summary']['updates'], [])
        client.rows['topic_summaries'] = [saved]
        client.rows['article_topic_assignments'] = [{'topic_id': 't', 'run_id': 'r', 'article_id': a['article_id']}
                                                    for a in payload['all_articles']]
        self.assertEqual(ai.pending_run_merge_focus(client, 'r'), set())

    def test_invalid_fact_in_completed_json_does_not_discard_valid_confirmation_or_retry(self):
        payload = self.payload(2)
        known = payload['previous_aggregation']['base_summary']['perspective_facts'][0]
        def answer(fmt, data):
            self.assertEqual(fmt['name'], 'perspective_facts')
            reply = coverage_reply(extraction([
                fact('', ['a0'], known['fact_id'], reason='', kind='FACT'),
                fact('Niepoprawny fakt.', ['a1'], kind='UNKNOWN')], data['all_articles']))
            # Simulate a provider answer failing the local schema. Production
            # must use its one completed response, not buy a corrected copy.
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(reply, fmt['schema'])
            return reply
        result, calls, log = self.run_sdk(payload, answer)
        self.assertEqual([name for name, _ in calls], ['perspective_facts'])
        self.assertEqual(result['perspective_facts'], payload['previous_aggregation']['base_summary']['perspective_facts'])
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertTrue(any('odrzuconych błędnych ustaleń: 1' in str(c) for c in log.call_args_list))
        self.assertFalse(any('ponawiam próbę' in str(c) for c in log.call_args_list))

    def test_foreign_article_and_invented_known_fact_are_dropped_without_guessing(self):
        payload = self.payload(2)
        known = payload['previous_aggregation']['base_summary']['perspective_facts'][0]
        bad = extraction([
            fact('', ['a0'], known['fact_id'], reason='', kind='FACT'),
            fact('Fakt z literówką ID.', ['a2'], kind='FACT'),
            fact('', ['a1'], 'invented', reason='', kind='FACT'),
            fact('', ['a1'], known['fact_id'], reason='', kind='FACT')], payload['all_articles'])
        # A separate citation list cannot override the nested article owner.
        typed = coverage_reply(bad)
        typed['article_results']['a1']['facts'][-1]['article_ids'] = ['a0']
        typed['article_results']['a2'] = {'facts': [fact('Obce.', [], kind='FACT')],
                                          'no_relevant_facts_reason_pl': ''}
        with patch.object(ai, 'call_openai', return_value=typed) as request, patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        request.assert_called_once()
        self.assertEqual(result['perspective_facts'][0]['article_ids'], ['a0'])
        self.assertEqual(len(result['perspective_facts']), 1)

    def test_missing_newness_reason_discards_only_that_fact_without_an_audit_or_correction(self):
        payload = self.payload(2)
        known = payload['previous_aggregation']['base_summary']['perspective_facts'][0]
        reply = extraction([
            fact('', ['a1'], known['fact_id'], reason='', kind='FACT'),
            fact('Nieuzasadniona nowość.', ['a1'], reason='', kind='FACT')], payload['all_articles'])
        for f in reply['facts']:
            f['evidence_quote'] = payload['all_articles'][1]['body_original'].split('.')[0] + '.'
        with patch.object(ai, 'call_openai', return_value=reply) as request, patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        request.assert_called_once()
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(len(result['perspective_facts']), 1)
        self.assertEqual(result['perspective_facts'][0]['article_ids'], ['a0', 'a1'])

    def test_empty_or_truncated_response_uses_one_attempt_and_preserves_the_base(self):
        for status, body in [('completed', ''), ('incomplete', '{"article_results": {')]:
            with self.subTest(status=status):
                result, calls, _ = self.run_sdk(self.payload(2), lambda fmt, data: SimpleNamespace(
                    status=status, usage=None, output_text=body,
                    incomplete_details=SimpleNamespace(reason='max_output_tokens')))
                self.assertEqual([name for name, _ in calls], ['perspective_facts'])
                self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
                self.assertEqual(result['summary_pl'], 'Zachowana publikacja.')
                self.assertEqual(len(result['perspective_facts']), 1)

    def test_all_omitted_first_publication_does_not_buy_a_writer_or_context(self):
        payload = self.payload(2)
        payload.pop('previous_aggregation')
        result, calls, _ = self.run_sdk(payload, lambda fmt, data: {
            'headline_pl': '[Polska] Wydarzenie', 'categories': [],
            'article_results': {a['article_id']: {'facts': [], 'no_relevant_facts_reason_pl': ''}
                                for a in data['all_articles']}})
        self.assertEqual([name for name, _ in calls], ['perspective_facts'])
        self.assertEqual(result['summary_pl'], '')
        self.assertEqual(result['perspective_facts'], [])
        self.assertEqual(result['background_context'], [])

    def test_forty_articles_are_read_once_in_five_batches_despite_many_omissions(self):
        payload = self.payload(40)
        payload.pop('previous_aggregation')
        def answer(fmt, data):
            if fmt['name'] == 'perspective_summary':
                return written(data)
            self.assertEqual(fmt['name'], 'perspective_facts')
            known = data['previous_facts']
            aid = data['all_articles'][0]['article_id']
            reply = coverage_reply(extraction([fact('' if known else 'Decyzja zapadła.', [aid],
                known[0]['fact_id'] if known else '', reason='', kind='FACT')], data['all_articles']))
            for item in reply['article_results'].values():
                item['no_relevant_facts_reason_pl'] = ''
            return reply
        result, calls, _ = self.run_sdk(payload, answer)
        self.assertEqual([name for name, _ in calls], ['perspective_facts'] * 5 + ['perspective_summary'])
        bodies = [a['body_original'] for name, data in calls if name == 'perspective_facts' for a in data['all_articles']]
        self.assertCountEqual(bodies, [a['body_original'] for a in payload['all_articles']])
        self.assertEqual(result['perspective_facts'][0]['article_ids'], ['a0', 'a16', 'a23', 'a30', 'a38'])

    def test_partial_checkpoint_is_explicit_and_cannot_satisfy_strict_extraction(self):
        payload = self.payload(2)
        payload['new_article_ids'] = ['a0', 'a1']
        def request(instructions, data, model, **settings):
            if settings['response_schema_name'] == 'perspective_facts':
                return extraction([{**fact('Nowa decyzja.', ['a1'], kind='FACT'), 'evidence_quote': 'Pełny artykuł 1.'}], data['all_articles'])
            raise RuntimeError('Późniejszy etap zawiódł.')
        with patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log'), self.assertRaises(RuntimeError) as error:
            ai.generate_summary_response(payload, 'gpt-5-nano')
        checkpoint = ai.parse_failure_for_storage(error.exception)['extraction_checkpoint']
        self.assertEqual(checkpoint['omissions'][0]['omitted_article_ids'], ['a0'])
        known = payload['previous_aggregation']['base_summary']['perspective_facts']
        key = p.extraction_checkpoint_key(payload, ai.SUMMARY_MAX_PAYLOAD_CHARS)
        self.assertIsNone(p.restore_extraction_checkpoint(checkpoint, key, payload['all_articles'], known, ai.normalize_generated_text))
        self.assertIsNotNone(p.restore_extraction_checkpoint(checkpoint, key, payload['all_articles'], known,
                                                           ai.normalize_generated_text, allow_omissions=True))


if __name__ == '__main__':
    unittest.main()
