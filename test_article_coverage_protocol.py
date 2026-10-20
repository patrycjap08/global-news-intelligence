import copy
import json
from pathlib import Path
import unittest

import jsonschema

import ai_pipeline as ai
import perspective_summaries as p
from test_perspective_summaries import article, coverage_reply


class ArticleCoverageProtocolTests(unittest.TestCase):
    def setUp(self):
        self.observed = json.loads((Path(__file__).parent / 'test_data/perspective_unaccounted_article_20261020.json').read_text())['response']
        self.ids = list(self.observed['article_coverage'])
        self.rows = [article(self.ids[0], 'LEFT'), article(self.ids[1], 'CENTER')]
        self.known = [{'fact_id': f['known_fact_id'], 'text_pl': f'Znane ustalenie {i}.',
                       'kind': f['kind'], 'article_ids': [self.ids[0]], 'lane': 'COMMON'}
                      for i, f in enumerate(self.observed['facts'])]

    def test_actual_empty_article_cannot_pass_the_new_api_schema(self):
        schema = p.article_coverage_schema(self.known, self.ids)
        jsonschema.Draft202012Validator.check_schema(schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(self.observed, schema)
        # Even after translating the old format, the actual missing evidence
        # plus empty reason is structurally invalid, before semantic checks.
        typed = coverage_reply(self.observed)
        self.assertEqual(typed['article_results'][self.ids[1]],
                         {'facts': [], 'no_relevant_facts_reason_pl': ''})
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(typed, schema)
        with self.assertRaisesRegex(ValueError, self.ids[1]):
            p.flatten_article_coverage(typed, self.rows)

    def test_explicit_article_judgment_adds_only_the_fact_assigned_to_that_article(self):
        typed = coverage_reply(self.observed)
        explicit = copy.deepcopy(typed['article_results'][self.ids[0]]['facts'][0])
        typed['article_results'][self.ids[1]]['facts'] = [explicit]
        jsonschema.validate(typed, p.article_coverage_schema(self.known, self.ids))
        original = copy.deepcopy(typed)
        flat = p.flatten_article_coverage(typed, self.rows)
        p.validate_article_coverage(flat, self.rows)
        p.validate_batch_citations(flat, self.rows, self.known, ai.normalize_generated_text)
        self.assertEqual([r['fact_indexes'] for r in flat['article_coverage']], [[0, 1, 2], [3]])
        _, routed = p.route_facts(flat, self.rows, self.known, ai.normalize_generated_text)
        self.assertEqual(routed[0]['article_ids'], self.ids)
        self.assertEqual([f['article_ids'] for f in routed[1:]], [[self.ids[0]], [self.ids[0]]])
        self.assertEqual(typed, original)

    def test_generate_repairs_the_omitted_article_with_an_explicit_result(self):
        base = {'perspective_version': 1, 'summary_pl': 'Zachowana publikacja.',
                'general_context': {'text_pl': 'Zachowany kontekst.'}, 'perspective_facts': self.known}
        payload = {'topic': {}, 'all_articles': [{**a, 'body_original': 'Pełny tekst. ' * 100} for a in self.rows],
                   'previous_aggregation': {'base_summary': base}, 'new_article_ids': [self.ids[1]]}
        original, calls = copy.deepcopy(payload), []
        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_facts':
                return copy.deepcopy(self.observed)
            self.assertEqual(name, 'perspective_article_coverage')
            self.assertEqual(data['all_articles'], [{**payload['all_articles'][1], 'source_group': 'CENTER'}])
            result = coverage_reply(self.observed)
            result['article_results'] = {self.ids[1]: {
                'facts': [copy.deepcopy(result['article_results'][self.ids[0]]['facts'][0])],
                'no_relevant_facts_reason_pl': '',
            }}
            jsonschema.validate(result, schema)
            return result
        result = p.generate(payload, call, ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_article_coverage'])
        self.assertEqual(result['summary_pl'], base['summary_pl'])
        self.assertEqual(result['general_context'], base['general_context'])
        self.assertEqual(len(result['perspective_facts']), len(self.known))
        self.assertEqual(result['perspective_facts'][0]['article_ids'], self.ids)
        self.assertEqual(result['update']['perspective_sections']['COMMON'], [])
        self.assertEqual(payload, original)

    def test_real_exclusion_needs_no_invented_fact_but_no_news_is_not_an_exclusion(self):
        typed = coverage_reply(self.observed)
        schema = p.article_coverage_schema(self.known, self.ids)
        omitted = typed['article_results'][self.ids[1]]
        omitted['no_relevant_facts_reason_pl'] = 'Materiał opisuje inne wydarzenie.'
        jsonschema.validate(typed, schema)
        flat = p.flatten_article_coverage(typed, self.rows)
        self.assertFalse(any(self.ids[1] in f['article_ids'] for f in flat['facts']))
        for reason in ['', '   ', 'Brak nowych informacji.']:
            omitted['no_relevant_facts_reason_pl'] = reason
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                p.flatten_article_coverage(typed, self.rows)

    def test_foreign_keys_and_independent_citation_lists_are_rejected(self):
        typed = coverage_reply(self.observed)
        typed['article_results'][self.ids[1]]['no_relevant_facts_reason_pl'] = 'Inne wydarzenie.'
        alien = copy.deepcopy(typed)
        alien['article_results']['foreign'] = alien['article_results'].pop(self.ids[1])
        with self.assertRaisesRegex(ValueError, 'każdego artykułu'):
            p.flatten_article_coverage(alien, self.rows)
        injection = copy.deepcopy(typed)
        injection['article_results'][self.ids[0]]['facts'][0]['article_ids'] = [self.ids[1]]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(injection, p.article_coverage_schema(self.known, self.ids))
        with self.assertRaisesRegex(ValueError, 'bez article_ids'):
            p.flatten_article_coverage(injection, self.rows)

    def test_shared_fact_definition_does_not_repeat_id_enums_for_each_article(self):
        known = [{'fact_id': f'fact_{i}', 'text_pl': f'Ustalenie {i}.', 'kind': 'FACT', 'article_ids': ['old']}
                 for i in range(100)]
        schema = p.article_coverage_schema(known, self.ids)
        jsonschema.Draft202012Validator.check_schema(schema)
        self.assertEqual(json.dumps(schema).count('"fact_0"'), 1)
        self.assertEqual(set(schema['properties']['article_results']['required']), set(self.ids))


if __name__ == '__main__':
    unittest.main()
