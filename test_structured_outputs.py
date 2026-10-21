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
                               p.article_coverage_schema(known, [f'a{i}' for i in range(8)]),
                               p.article_coverage_schema(known, [f'a{i}' for i in range(8)], allow_omissions=True),
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

    def test_entire_49_article_update_with_complete_first_extraction_audit_and_storage(self):
        from test_editorial_integrity import article as full_article, claim, extraction as per_article, writer
        rows = [full_article(f'a{i:02}', f'Rada miasta zrealizuje inwestycję numer {i}.') for i in range(49)]
        known = p.route_facts({'facts': [claim(rows[0]['body_original'], 'a00')]}, rows, [], ai.normalize_generated_text)[1]
        base = {'perspective_version': 1, 'summary_pl': 'Pierwotny artykuł.', 'perspective_facts': known}
        payload = {'topic': {}, 'all_articles': rows, 'new_article_ids': [a['article_id'] for a in rows[23:]],
                   'previous_aggregation': {'base_summary': base, 'processed_article_ids': [a['article_id'] for a in rows[:23]]}}
        before = copy.deepcopy(payload)
        calls, bodies = [], []
        def response(**request):
            fmt = request['text']['format']; name, schema = fmt['name'], fmt['schema']
            check_response_schema(schema)
            data = json.JSONDecoder().raw_decode(request['input'])[0]
            calls.append(name)
            if name == 'perspective_facts':
                bodies.extend(a['body_original'] for a in data['all_articles'])
                answer = per_article(data, [claim(a['body_original'], a['article_id']) for a in data['all_articles']])
            elif name == 'perspective_novelty_audit':
                answer = {'decisions': {f['fact_id']: {'decision': 'NEW', 'new_detail_pl': '',
                    'covered_fact_ids': [], 'reason_pl': 'Odrębna inwestycja.'} for f in data['candidate_facts']}}
            else:
                answer = writer(data)
            jsonschema.validate(answer, schema)
            return SimpleNamespace(status='completed', usage=None, output_text=json.dumps(answer, ensure_ascii=False))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('openai.OpenAI') as sdk, patch.object(ai, 'log'):
            sdk.return_value.responses.create.side_effect = response
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        self.assertEqual(calls.count('perspective_facts'), 4)
        self.assertEqual(calls.count('perspective_novelty_audit'), 2)
        self.assertEqual(calls.count('perspective_summary'), 1)
        self.assertEqual(bodies, [a['body_original'] for a in rows[23:]])
        self.assertEqual(payload, before)
        self.assertEqual(len(result['perspective_facts']), 27)
        client = FakeMergeClient([], [], [])
        ai.persist_summary(client, topic_id='t', run_id='r', model='fake', summary=result,
            summary_hash='h', previous_row={'version': 1, 'summary': {'base_summary': base,
            'processed_article_ids': [a['article_id'] for a in rows[:23]]}}, new_article_ids=payload['new_article_ids'])
        saved = next(items[0]['summary'] for table, items, _ in client.upserts if table == 'topic_summaries')
        self.assertEqual(saved['base_summary'], base)
        self.assertEqual(len(saved['updates']), 1)
        self.assertEqual(set(saved['processed_article_ids']), {a['article_id'] for a in rows})

    def test_eight_sources_confirm_known_fact_in_one_call_without_update_or_repairs(self):
        rows = [article(f'a{i}', ('CENTER', 'LEFT', 'RIGHT')[i % 3]) for i in range(8)]
        known = p.route_facts({'facts': [fact('Minister ogłosił decyzję.', ['a0'], kind='STATEMENT')]},
                              rows, [], ai.normalize_generated_text)[1]
        base = {'perspective_version': 1, 'summary_pl': 'Zachowana publikacja.',
                'perspective_facts': known}
        payload = {'topic': {'working_title_pl': 'Decyzja ministra'}, 'all_articles': rows,
                   'new_article_ids': [a['article_id'] for a in rows[1:]],
                   'previous_aggregation': {'base_summary': base}}

        def response(**request):
            fmt = request['text']['format']
            self.assertEqual(fmt['name'], 'perspective_facts')
            self.assertIn('article_results', fmt['schema']['required'])
            self.assertIn('Brak NOWYCH faktów jest poprawny', request['instructions'])
            data = json.JSONDecoder().raw_decode(request['input'])[0]
            answer = coverage_reply(extraction([
                fact('', [a['article_id'] for a in data['all_articles']], known[0]['fact_id'],
                     reason='', kind='STATEMENT')], data['all_articles']))
            for result in answer['article_results'].values():
                for f in result['facts']:
                    f.update(attribution='Minister')
            jsonschema.validate(answer, fmt['schema'])
            return SimpleNamespace(status='completed', usage=None, output_text=json.dumps(answer))

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('openai.OpenAI') as sdk, patch.object(ai, 'log') as logger:
            sdk.return_value.responses.create.side_effect = response
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        self.assertEqual(sdk.return_value.responses.create.call_count, 1)
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(len(result['perspective_facts']), 1)
        self.assertEqual(set(result['perspective_facts'][0]['article_ids']), {a['article_id'] for a in rows})
        self.assertEqual(result['summary_pl'], base['summary_pl'])
        self.assertFalse(any(c.kwargs.get('level') == 'WARN' for c in logger.call_args_list))


if __name__ == '__main__':
    unittest.main()
