import copy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from openai import BadRequestError
import jsonschema

import ai_pipeline as ai
import perspective_summaries as p
from structured_outputs import check_response_schema
from test_perspective_novelty import verdict
from test_perspective_summaries import article, extraction, fact, coverage_reply
from test_topic_titles import FakeMergeClient


class StructuredOutputTests(unittest.TestCase):
    def test_all_perspective_schemas_with_large_ledgers_fit_supported_subset(self):
        for count in (0, 17, 100, 500):
            with self.subTest(count=count):
                known = [{'fact_id': f'fact_{i:024x}', 'text_pl': f'Ustalenie {i}.',
                          'kind': p.FACT_KINDS[i % 3], 'article_ids': [f'a{i % 49}']}
                         for i in range(count)]
                candidates = [{'fact_id': f'new_{i}', 'text_pl': 'Pełne ustalenie. ' * 1000}
                              for i in range(p.NOVELTY_BATCH_FACTS)]
                for schema in (p.extraction_schema(known, [f'a{i}' for i in range(8)]),
                               p.article_coverage_schema(known, ['a1', 'a2']),
                               p.novelty_schema(known, candidates), p.novelty_decision_schema(known, candidates),
                               p.writing_schema(known)):
                    check_response_schema(schema)
                novelty = p.novelty_schema(known, candidates)
                for value in novelty['properties']['decisions']['properties'].values():
                    self.assertNotIn('anyOf', value)
                    self.assertEqual(value['properties']['new_text_pl'], {'type': 'string'})
                # Sentence length has no influence on the API grammar size.
                shorter = [{**f, 'text_pl': 'Krótko.'} for f in candidates]
                self.assertEqual(novelty, p.novelty_schema(known, shorter))

    def test_preflight_rejects_invalid_subset_and_limits_before_openai_client(self):
        valid = p.novelty_schema([{'fact_id': 'old'}], [{'fact_id': 'new', 'text_pl': 'Nowe.'}])
        bad_required = copy.deepcopy(valid)
        bad_required['required'] = []
        too_many = p.obj({'ids': {'type': 'string', 'enum': [str(i) for i in range(1001)]}})
        unsupported = p.obj({'value': {'oneOf': [p.STRING, {'type': 'null'}]}})
        missing_ref = p.obj({'value': {'$ref': '#/$defs/missing'}})
        for schema in (bad_required, too_many, unsupported, missing_ref):
            with self.subTest(schema=schema), patch('openai.OpenAI') as sdk:
                with self.assertRaises(ai.AIRequestSchemaError) as caught:
                    ai.call_openai('Test.', {}, 'gpt-5-nano', response_schema=schema)
                self.assertEqual(caught.exception.response_details['source'], 'local_preflight')
                sdk.assert_not_called()

    def test_full_api_schema_rejection_is_logged_and_stored_without_model_retry(self):
        message = ('Invalid schema for response_format perspective_novelty_audit: '
                   + 'diagnostic context; ' * 20 + 'specific provider rejection at the end')
        error = BadRequestError(message, response=httpx.Response(400,
            request=httpx.Request('POST', 'https://api.openai.com/v1/responses')),
            body={'message': message, 'type': 'invalid_request_error', 'param': 'text.format.schema'})
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('openai.OpenAI') as sdk:
            sdk.return_value.responses.create.side_effect = error
            with self.assertRaises(ai.AIRequestSchemaError) as caught:
                ai.call_openai('Test.', {}, 'gpt-5-nano', response_schema=p.obj({'x': p.STRING}),
                               response_schema_name='perspective_novelty_audit')
            self.assertEqual(sdk.return_value.responses.create.call_count, 1)
        with patch.object(ai, 'log') as logger:
            ai.log_parse_failure('SUMMARY', caught.exception)
        self.assertIn('specific provider rejection at the end', str(logger.call_args_list))
        self.assertNotIn('model nie zwrócił', str(logger.call_args_list))
        stored = ai.parse_failure_for_storage(caught.exception)
        self.assertEqual(stored['response_details']['api_error'], message)
        self.assertEqual(stored['response_details']['status'], 400)

    def test_valid_json_that_breaks_schema_is_retried_before_returning_it(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('openai.OpenAI') as sdk:
            sdk.return_value.responses.create.side_effect = [
                SimpleNamespace(status='completed', usage=None, output_text='{"x": 10}'),
                SimpleNamespace(status='completed', usage=None, output_text='{"x": "ok"}'),
            ]
            result = ai.call_openai('Test.', {}, 'gpt-5-nano', response_schema=p.obj({'x': p.STRING}))
            self.assertEqual(result, {'x': 'ok'})
            self.assertEqual(sdk.return_value.responses.create.call_count, 2)

    def test_entire_49_article_update_through_sdk_schema_repair_audit_and_storage(self):
        # Explicit synthetic judgments, not a simulation of model accuracy.
        # Exercise the actual API adapter rather than mocking call_openai.
        rows = [{**article(f'a{i}', ('LEFT', 'CENTER', 'RIGHT')[i % 3]),
                 'body_original': f'Pełny tekst artykułu {i}. ' * 180} for i in range(49)]
        known = p.route_facts({'facts': [
            fact(f'Znane ustalenie {i}.', ['a0'], kind='STATEMENT' if i == 0 else 'FACT')
            for i in range(17)]}, rows, [], ai.normalize_generated_text)[1]
        base = {'perspective_version': 1, 'fact_classification_version': 1,
                'summary_pl': 'Pierwotny artykuł.\n\nDrugi akapit.',
                'background_context': [{'text_pl': 'Wcześniejsze tło.', 'article_ids': [], 'needs_verification': False}],
                'perspective_facts': known, 'facts': known, 'coverage_mode': 'MIXED'}
        payload = {'topic': {}, 'all_articles': rows, 'new_article_ids': [a['article_id'] for a in rows[23:]],
                   'previous_aggregation': {'base_summary': base}}
        before = copy.deepcopy(payload)
        calls, bodies, repairs, candidate_texts = [], [], [], []

        def response(**request):
            fmt = request['text']['format']
            name, schema = fmt['name'], fmt['schema']
            check_response_schema(schema)
            data = json.JSONDecoder().raw_decode(request['input'])[0]
            calls.append(name)
            if name == 'perspective_facts':
                current = data['all_articles']
                self.assertLessEqual(len(current), 8)
                bodies.extend(a['body_original'] for a in current)
                ids = [a['article_id'] for a in current if a['article_id'] != 'a7']
                returned = [fact('', ids, f['fact_id'], reason='', kind=f['kind']) for f in known]
                if len(calls) == 1:
                    # A new-branch exact match cannot change the old type.
                    returned.append(fact(known[0]['text_pl'], ['a0'], kind='FACT'))
                    returned.extend(fact(f'Nowy szczegół {i}.', ['a0'], kind='FACT') for i in range(22))
                answer = extraction(returned, current)
                if any(a['article_id'] == 'a7' for a in current):
                    answer['article_coverage']['a7']['no_relevant_facts_reason_pl'] = ''
            elif name == 'perspective_article_coverage':
                repairs.extend(a['article_id'] for a in data['all_articles'])
                answer = coverage_reply(extraction([
                    fact('', ['a7'], known[0]['fact_id'], reason='', kind='STATEMENT')], data['all_articles']))
            else:
                self.assertEqual(name, 'perspective_novelty_audit')
                self.assertNotIn('all_articles', data)
                self.assertEqual(len(data['candidate_facts']), 22)
                candidate_texts.extend(f['text_pl'] for f in data['candidate_facts'])
                decisions = {f['fact_id']: verdict(f['text_pl']) for f in data['candidate_facts']}
                first, second, third = data['candidate_facts'][:3]
                decisions[first['fact_id']] = verdict('', [known[1]['fact_id']] * 2, 'Parafraza znanego.')
                decisions[third['fact_id']] = verdict('', [second['fact_id']], 'Powtórzenie wcześniejszego kandydata.')
                answer = {'decisions': {cid: {
                    'decision': 'NEW' if not d['covered_fact_ids'] else 'DETAIL' if d['new_text_pl'] else 'DUPLICATE',
                    'new_detail_pl': d['new_text_pl'] if d['covered_fact_ids'] else '',
                    'covered_fact_ids': d['covered_fact_ids'], 'reason_pl': d['reason_pl'],
                } for cid, d in decisions.items()}}
            jsonschema.validate(answer, schema)
            return SimpleNamespace(status='completed', usage=None, output_text=json.dumps(answer, ensure_ascii=False))

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('openai.OpenAI') as sdk, patch.object(ai, 'log') as logger:
            sdk.return_value.responses.create.side_effect = response
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        self.assertEqual(calls.count('perspective_facts'), 7)
        self.assertEqual(calls.count('perspective_article_coverage'), 1)
        self.assertEqual(calls.count('perspective_novelty_audit'), 1)
        self.assertNotIn('perspective_summary', calls)
        self.assertFalse(any(c.kwargs.get('level') == 'WARN' for c in logger.call_args_list))
        self.assertEqual(bodies, [a['body_original'] for a in rows])
        self.assertEqual(repairs, ['a7'])
        self.assertEqual(payload, before)
        self.assertEqual(result['summary_pl'], base['summary_pl'])
        self.assertEqual(result['background_context'], base['background_context'])
        self.assertEqual(len(result['perspective_facts']), 37)  # 17 old + 20 admitted.
        stable = next(f for f in result['perspective_facts'] if f['fact_id'] == known[0]['fact_id'])
        self.assertEqual(stable['kind'], 'STATEMENT')
        self.assertEqual(set(stable['article_ids']), {a['article_id'] for a in rows})
        self.assertNotIn(candidate_texts[0], json.dumps(result['perspective_facts']))
        self.assertNotIn(candidate_texts[2], json.dumps(result['perspective_facts']))
        client = FakeMergeClient([], [], [])
        previous_row = {'version': 1, 'summary': {'base_summary': base, 'updates': [],
                                                'processed_article_ids': ['a0']}}
        ai.persist_summary(client, topic_id='t', run_id='r', model='fake', summary=result,
                           summary_hash='h', previous_row=previous_row, new_article_ids=payload['new_article_ids'])
        saved = next(items[0]['summary'] for table, items, _ in client.upserts if table == 'topic_summaries')
        self.assertEqual(saved['base_summary'], base)
        self.assertEqual(len(saved['updates']), 1)
        self.assertTrue(set(payload['new_article_ids']) <= set(saved['processed_article_ids']))


if __name__ == '__main__':
    unittest.main()
