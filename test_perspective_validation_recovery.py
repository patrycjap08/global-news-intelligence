import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonschema

import ai_pipeline as ai
import perspective_summaries as p
from test_perspective_summaries import article, extraction, fact, coverage_reply


def written(data):
    return {'paragraphs': [{'text_pl': ' '.join(f['text_pl'] for f in data['main_facts']),
                            'fact_ids': [f['fact_id'] for f in data['main_facts']]}],
            'general_context': {'text_pl': 'Ogólne tło tematu.', 'article_ids': [], 'needs_verification': True},
            'background_context': []}


class PerspectiveValidationRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / 'test_data' / 'perspective_validation_regressions.json'
        cls.fixtures = {row['case']: row for row in json.loads(path.read_text())}
        # Preserve the historical errors while supplying the newly required
        # classification field to these mocked extraction responses.
        for fixture in cls.fixtures.values():
            for row in fixture['response'].get('facts', []):
                row['kind'] = 'FACT'

    def payload(self, fixture):
        # Actual profiles/previous ledger from the public snapshot; synthetic
        # long bodies check transport preservation without paying for an AI run.
        rows = [{**a, 'body_original': ('Pełny tekst artykułu. ' * 100) + a['article_id']}
                for a in fixture['articles']]
        payload = {'topic': {}, 'all_articles': rows, 'new_article_ids': [a['article_id'] for a in rows]}
        if 'previous_aggregation' in fixture:
            payload['previous_aggregation'] = copy.deepcopy(fixture['previous_aggregation'])
        return payload

    def test_real_article_id_typo_is_constrained_and_corrected_without_guessing_in_code(self):
        fixture = self.fixtures['article_id_typo']
        bad = copy.deepcopy(fixture['response'])
        payload = self.payload(fixture)
        correct_id = '8846f889b81b4bc313fac97c'
        typo = '8846f889b81b4bc313fac97d'
        # Stand-in for a rechecked AI answer, not a fuzzy-ID repair algorithm.
        corrected = copy.deepcopy(bad)
        for row in corrected['facts']:
            row['article_ids'] = [correct_id if aid == typo else aid for aid in row['article_ids']]
        calls, retries = [], []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_summary':
                return written(data)
            self.assertEqual(data['all_articles'], [{**a, 'source_group': p.article_group(a)} for a in payload['all_articles']])
            if len(calls) == 1:
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(bad, schema)
                return copy.deepcopy(bad)
            self.assertEqual(data['validation_feedback']['response_to_correct'], bad)
            self.assertIn('Nie zgaduj', instructions)
            jsonschema.validate(corrected, schema)
            return copy.deepcopy(corrected)

        original = copy.deepcopy(payload)
        result = p.generate(payload, call, ai.normalize_generated_text,
                            on_validation_retry=lambda *args: retries.append(args))
        self.assertEqual(calls, ['perspective_facts', 'perspective_facts', 'perspective_summary'])
        self.assertEqual(len(retries), 1)
        self.assertEqual(len(result['perspective_facts']), len(corrected['facts']))
        self.assertFalse(any(typo in f['article_ids'] for f in result['perspective_facts']))
        self.assertEqual(payload, original)

    def test_real_missing_novelty_reasons_get_one_recheck_preserving_published_text(self):
        for key in ('missing_novelty_reason', 'missing_novelty_reasons_after_merge'):
            with self.subTest(case=key):
                fixture = self.fixtures[key]
                bad = copy.deepcopy(fixture['response'])
                payload = self.payload(fixture)
                base = copy.deepcopy(payload['previous_aggregation']['base_summary'])
                corrected = copy.deepcopy(bad)
                for row in corrected['facts']:
                    if not row['known_fact_id'] and not row['why_new_pl']:
                        row['why_new_pl'] = 'Dodatkowy szczegół nieobecny we wcześniejszym rejestrze ustaleń.'
                calls = []

                def call(instructions, data, schema, name):
                    calls.append(name)
                    if name == 'perspective_novelty_audit':
                        return {'decisions': {f['fact_id']: {'new_text_pl': f['text_pl'],
                            'covered_fact_ids': [], 'reason_pl': 'Nowy szczegół testowy.'} for f in data['candidate_facts']}}
                    if name == 'perspective_article_coverage':
                        # These synthetic bodies do not establish additional
                        # evidence. Explicitly account for the historical gaps.
                        return coverage_reply(extraction([], data['all_articles']))
                    self.assertEqual(name, 'perspective_facts')  # Never rewrite old prose.
                    self.assertEqual(data['all_articles'], [{**a, 'source_group': p.article_group(a)} for a in payload['all_articles']])
                    if len(calls) == 1:
                        with self.assertRaises(jsonschema.ValidationError):
                            jsonschema.validate(bad, schema)
                        return copy.deepcopy(bad)
                    self.assertEqual(data['validation_feedback']['response_to_correct'], bad)
                    jsonschema.validate(corrected, schema)
                    return copy.deepcopy(corrected)

                # The fixture is one complete historical answer, not an AI
                # mock that can generate responses for arbitrary sub-batches.
                with patch.object(p, 'EXTRACTION_BATCH_ARTICLES', len(payload['all_articles'])):
                    result = p.generate(payload, call, ai.normalize_generated_text)
                self.assertEqual(calls[:2], ['perspective_facts'] * 2)
                self.assertEqual(calls[-1], 'perspective_novelty_audit')
                self.assertTrue(all(name in ('perspective_facts', 'perspective_article_coverage') for name in calls[:-1]))
                self.assertEqual(result['summary_pl'], base['summary_pl'])
                self.assertEqual(result.get('general_context'), base.get('general_context'))
                self.assertEqual(result.get('background_context'), base.get('background_context'))
                self.assertEqual(len(result['perspective_facts']), len(corrected['facts']))
                self.assertEqual(result['update']['status'], 'NEW_INFORMATION')

    def test_reasonless_paraphrase_repaired_as_confirmation_never_becomes_an_update(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        _, known = p.route_facts({'facts': [fact('Minister złożył rezygnację.', ['l', 'r'])]},
                                rows, [], ai.normalize_generated_text)
        base = {'perspective_version': 1, 'summary_pl': 'Pierwotny artykuł.', 'perspective_facts': known}
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            if len(calls) == 1:
                return extraction([fact('Minister podał się do dymisji.', ['r'], reason='')], rows)
            self.assertEqual(data['previous_facts'], known)
            self.assertIn('Nowe ustalenie', data['validation_feedback']['validation_error_pl'])
            return extraction([fact('', ['r'], known[0]['fact_id'], reason='')], rows)

        result = p.generate({'topic': {}, 'all_articles': rows,
                             'previous_aggregation': {'base_summary': base}}, call, ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_facts'])
        self.assertEqual(result['perspective_facts'], [{**f, 'kind':'FACT'} for f in known])
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(result['summary_pl'], base['summary_pl'])

    def test_real_empty_context_is_valid_without_common_facts_and_never_invents_prose(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_facts':
                return extraction([fact('Ustalenie lewicy.', ['l'],kind='EDITORIAL'), fact('Ustalenie prawicy.', ['r'],kind='EDITORIAL')], rows)
            self.assertEqual(data['main_facts'], [])
            response = copy.deepcopy(self.fixtures['empty_context_without_common_facts']['response'])
            jsonschema.validate(response, schema)
            return response

        result = p.generate({'topic': {}, 'all_articles': rows}, call, ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_summary'])
        self.assertFalse(result['shared_available'])
        self.assertEqual(result['summary_pl'], '')
        self.assertEqual(result['facts'], [])
        self.assertIsNone(result['general_context'])
        self.assertEqual(len(result['perspective_sections']['LEFT']), 1)
        self.assertEqual(len(result['perspective_sections']['RIGHT']), 1)

    def test_empty_context_with_common_facts_retries_only_writer(self):
        rows = [article('a', 'CENTER')]
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_facts':
                return extraction([fact('Decyzja.', ['a'])], rows)
            response = written(data)
            if len(calls) == 2:
                response['general_context']['text_pl'] = ''
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(response, schema)
            else:
                self.assertIn('Brak ogólnego kontekstu', data['validation_feedback']['validation_error_pl'])
            return response

        result = p.generate({'topic': {}, 'all_articles': rows}, call, ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_summary', 'perspective_summary'])
        self.assertEqual(result['general_context']['text_pl'], 'Ogólne tło tematu.')

    def test_still_invalid_evidence_fails_after_one_correction_without_partial_result(self):
        fixture = self.fixtures['article_id_typo']
        calls, retries = [], []

        def call(instructions, data, schema, name):
            calls.append(name)
            return copy.deepcopy(fixture['response'])

        with self.assertRaisesRegex(ValueError, 'spoza bieżącej paczki'):
            p.generate(self.payload(fixture), call, ai.normalize_generated_text,
                       on_validation_retry=lambda *args: retries.append(args))
        self.assertEqual(calls, ['perspective_facts', 'perspective_facts'])
        self.assertEqual(len(retries), 1)

    def test_confirmation_schema_and_validator_preserve_batch_and_per_fact_boundaries(self):
        known = [{'fact_id': 'f1', 'text_pl': 'Pierwszy.', 'article_ids': ['old1'], 'lane': 'COMMON'},
                 {'fact_id': 'f2', 'text_pl': 'Drugi.', 'article_ids': ['old2'], 'lane': 'COMMON'}]
        schema = p.extraction_schema(known, ['current'])
        valid = extraction([fact('', ['current'], 'f1', reason='')], [article('current', 'CENTER')])
        jsonschema.validate(valid, schema)
        p.validate_batch_citations(valid, [{'article_id': 'current'}], known, ai.normalize_generated_text)
        invalid = copy.deepcopy(valid)
        invalid['facts'][0]['article_ids'] = ['old2']
        # Old evidence stays in the ledger; it is not requested from the model.
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)
        with self.assertRaisesRegex(ValueError, 'spoza bieżącej paczki'):
            p.validate_batch_citations(invalid, [{'article_id': 'current'}], known, ai.normalize_generated_text)
        legacy = copy.deepcopy(valid)
        legacy['facts'][0]['article_ids'] = ['old1', 'current']
        p.validate_batch_citations(legacy, [{'article_id': 'current'}], known, ai.normalize_generated_text)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(legacy, schema)
        for reason in ('', '  ', '\n'):
            invalid = extraction([fact('Nowy.', ['current'], reason=reason)], [article('current', 'CENTER')])
            with self.subTest(reason=reason), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(invalid, schema)


if __name__ == '__main__':
    unittest.main()
