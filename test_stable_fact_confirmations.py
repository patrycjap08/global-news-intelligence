import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonschema

import ai_pipeline as ai
import perspective_summaries as p
from test_perspective_summaries import article, extraction, fact
from test_perspective_validation_recovery import written


class StableFactConfirmationTests(unittest.TestCase):
    def test_real_failed_answer_reuses_a_cross_batch_fact_without_changing_its_type(self):
        fixture = json.loads((Path(__file__).parent / 'test_data/perspective_type_conflict_20261020.json').read_text())
        response = fixture['response']
        repeated = response['facts'][7]
        self.assertEqual(repeated['known_fact_id'], '')
        self.assertEqual(repeated['kind'], 'FACT')
        self.assertTrue(repeated['text_pl'].startswith('Trump powiedział'))
        rows = [article(aid, 'CENTER') for aid in response['article_coverage']]
        rows.append(article('earlier', 'CENTER'))
        # Reconstruct a previous batch containing the exact statement. The
        # public failure log did not include that intermediate AI answer.
        known = p.route_facts({'facts': [fact(repeated['text_pl'], ['earlier'], kind='STATEMENT')]},
                              rows, [], ai.normalize_generated_text)[1]
        original = copy.deepcopy(known)
        p.validate_batch_citations(response, rows[:-1], known, ai.normalize_generated_text)
        _, routed = p.route_facts(response, rows, known, ai.normalize_generated_text)
        reused = next(f for f in routed if f['fact_id'] == known[0]['fact_id'])
        self.assertEqual(reused['kind'], 'STATEMENT')
        self.assertEqual(reused['text_pl'], known[0]['text_pl'])
        self.assertEqual(reused['article_ids'], ['earlier', *repeated['article_ids']])
        self.assertEqual(len(routed), len(response['facts']))
        update = p.make_update(routed, known, True, list(response['article_coverage']),
                               {a['article_id']: a for a in rows})
        self.assertNotIn(reused['fact_id'], {f['fact_id'] for f in update['perspective_sections']['COMMON']})
        self.assertEqual(known, original)

    def test_cross_batch_exact_text_conflict_does_not_retry_or_duplicate(self):
        rows = [article('first', 'LEFT'), article('second', 'RIGHT')]
        original = 'Minister zapowiedział kontrolę.'
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_summary':
                self.assertEqual(len(data['main_facts']), 1)
                self.assertEqual(data['main_facts'][0]['kind'], 'STATEMENT')
                return written(data)
            aid = data['all_articles'][0]['article_id']
            if aid == 'first':
                result = extraction([fact(original, [aid], kind='STATEMENT')], data['all_articles'])
            else:
                # Valid new-claim branch, but deterministic normalization
                # recognizes the earlier fact before considering its kind.
                result = extraction([fact('MINISTER   zapowiedział kontrolę', [aid], kind='FACT')], data['all_articles'])
            jsonschema.validate(result, schema)
            return result

        retries = []
        with patch.object(p, 'EXTRACTION_BATCH_ARTICLES', 1):
            result = p.generate({'topic': {}, 'all_articles': rows}, call, ai.normalize_generated_text,
                                on_validation_retry=lambda *args: retries.append(args))
        self.assertEqual(calls, ['perspective_facts', 'perspective_facts', 'perspective_summary'])
        self.assertEqual(retries, [])
        self.assertEqual(len(result['perspective_facts']), 1)
        self.assertEqual(result['perspective_facts'][0]['text_pl'], original)
        self.assertEqual(result['perspective_facts'][0]['kind'], 'STATEMENT')
        self.assertEqual(result['perspective_facts'][0]['article_ids'], ['first', 'second'])

    def test_existing_editorial_is_not_promoted_and_does_not_create_an_update(self):
        rows = [article('old', 'LEFT'), article('new', 'LEFT')]
        text = 'Autor uważa decyzję za niesprawiedliwą.'
        known = p.route_facts({'facts': [fact(text, ['old'], kind='EDITORIAL')]},
                              rows, [], ai.normalize_generated_text)[1]
        base = {'perspective_version': 1, 'summary_pl': 'Zachowana synteza.',
                'general_context': {'text_pl': 'Zachowany kontekst.'}, 'perspective_facts': known}
        payload = {'topic': {}, 'all_articles': rows, 'new_article_ids': ['new'],
                   'previous_aggregation': {'base_summary': base}}
        original = copy.deepcopy(payload)

        def request(instructions, data, model, **settings):
            self.assertEqual(settings['response_schema_name'], 'perspective_facts')
            result = extraction([fact(text, ['old', 'new'], kind='FACT')], data['all_articles'])
            jsonschema.validate(result, settings['response_schema'])
            return result

        with patch.object(ai, 'call_openai', side_effect=request) as request, patch.object(ai, 'log') as log:
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(result['facts'], [])
        self.assertEqual(result['perspective_facts'][0]['kind'], 'EDITORIAL')
        self.assertEqual(result['perspective_facts'][0]['article_ids'], ['old', 'new'])
        self.assertEqual(result['summary_pl'], base['summary_pl'])
        self.assertTrue(any(base['general_context']['text_pl'] in item['text_pl']
                            for item in result['background_context']))
        self.assertFalse(any(c.kwargs.get('level') == 'WARN' for c in log.call_args_list))
        self.assertEqual(payload, original)

    def test_first_type_and_text_remain_stable_within_one_response(self):
        rows = [article('a', 'LEFT'), article('b', 'RIGHT')]
        for saved in p.FACT_KINDS:
            for proposed in p.FACT_KINDS:
                with self.subTest(saved=saved, proposed=proposed):
                    response = {'facts': [fact('Pierwsze ustalenie.', ['a'], kind=saved),
                                          fact('PIERWSZE ustalenie', ['b'], kind=proposed)]}
                    _, routed = p.route_facts(response, rows, [], ai.normalize_generated_text)
                    self.assertEqual(len(routed), 1)
                    self.assertEqual(routed[0]['kind'], saved)
                    self.assertEqual(routed[0]['text_pl'], 'Pierwsze ustalenie.')
                    self.assertEqual(routed[0]['article_ids'], ['a', 'b'])


if __name__ == '__main__':
    unittest.main()
