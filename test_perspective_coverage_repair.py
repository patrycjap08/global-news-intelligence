import copy
import json
import unittest
from unittest.mock import patch

import jsonschema

import ai_pipeline as ai
import perspective_summaries as p
from test_perspective_summaries import article, extraction, fact, coverage_reply
from test_perspective_validation_recovery import written


def repair_protocol(call):
    def adapted(instructions, data, schema, name):
        response = call(instructions, data, schema, name)
        return coverage_reply(response) if name == 'perspective_article_coverage' else response
    return adapted


class PerspectiveCoverageRepairTests(unittest.TestCase):
    def test_large_topic_reads_every_complete_article_in_bounded_batches(self):
        rows = [{**article(str(i), 'CENTER'), 'body_original': f'Artykuł {i}. ' * 300}
                for i in range(40)]
        calls, bodies = [], []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_summary':
                return written(data)
            current = data['all_articles']
            self.assertLessEqual(len(current), 8)
            bodies.extend(a['body_original'] for a in current)
            known = data['previous_facts']
            response = extraction([fact('' if known else 'Minister złożył dymisję.',
                                        [a['article_id'] for a in current],
                                        known[0]['fact_id'] if known else '', reason='')], current)
            jsonschema.validate(response, schema)
            return response

        result = p.generate({'topic': {}, 'all_articles': rows}, call, ai.normalize_generated_text)
        self.assertEqual(bodies, [a['body_original'] for a in rows])
        self.assertEqual(calls, ['perspective_facts'] * 5 + ['perspective_summary'])
        self.assertEqual(len(result['perspective_facts']), 1)
        self.assertEqual(result['perspective_facts'][0]['article_ids'], [a['article_id'] for a in rows])

    def test_repair_sends_only_omitted_full_bodies_and_preserves_correct_facts(self):
        rows = [{**article(aid, 'LEFT' if aid == 'l' else 'RIGHT'), 'body_original': aid * 1000}
                for aid in ['l', 'r', 'off_topic']]
        payload = {'topic': {}, 'all_articles': rows}
        original = copy.deepcopy(payload)
        calls, repairs = [], []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_summary':
                self.assertEqual(data['main_facts'][0]['article_ids'], ['l', 'r'])
                return written(data)
            if len(calls) == 1:
                result = extraction([fact('Minister złożył dymisję.', ['l'])], rows)
                result['article_coverage']['r']['no_relevant_facts_reason_pl'] = ''
                return result
            self.assertIn(p.COVERAGE_REPAIR_INSTRUCTIONS, instructions)
            self.assertEqual(data['all_articles'], [{**rows[1], 'source_group': 'RIGHT'}])
            self.assertEqual(len(data['previous_facts']), 1)
            result = extraction([fact('', ['r'], data['previous_facts'][0]['fact_id'], reason='')], data['all_articles'])
            result = coverage_reply(result)
            jsonschema.validate(result, schema)
            return result

        result = p.generate(payload, repair_protocol(call), ai.normalize_generated_text,
                            on_coverage_repair=lambda ids: repairs.append(ids))
        self.assertEqual(calls, ['perspective_facts', 'perspective_article_coverage', 'perspective_summary'])
        self.assertEqual(repairs, [['r']])
        self.assertEqual(result['perspective_facts'][0]['article_ids'], ['l', 'r'])
        self.assertEqual(len(result['perspective_facts']), 1)
        self.assertEqual(payload, original)

    def test_many_missing_articles_are_rechecked_in_batches_of_two(self):
        rows = [article(str(i), 'CENTER') for i in range(8)]
        sent = []

        def call(instructions, data, schema, name):
            if name == 'perspective_summary':
                return written(data)
            sent.append([a['article_id'] for a in data['all_articles']])
            if len(sent) == 1:
                result = extraction([fact('Decyzja zapadła.', ['0'])], rows)
                for aid in map(str, range(1, 8)):
                    result['article_coverage'][aid]['no_relevant_facts_reason_pl'] = ''
                return result
            self.assertLessEqual(len(data['all_articles']), 2)
            return extraction([fact('', sent[-1], data['previous_facts'][0]['fact_id'])], data['all_articles'])

        result = p.generate({'topic': {}, 'all_articles': rows}, repair_protocol(call), ai.normalize_generated_text)
        self.assertEqual(sent[1:], [['1', '2'], ['3', '4'], ['5', '6'], ['7']])
        self.assertEqual(result['perspective_facts'][0]['article_ids'], list(map(str, range(8))))

    def test_repair_collects_missing_details_with_their_own_evidence(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_summary':
                return written(data)
            if len(calls) == 1:
                result = extraction([fact('Minister złożył dymisję.', ['l'])], rows)
                result['article_coverage']['r']['no_relevant_facts_reason_pl'] = ''
                return result
            return extraction([
                fact('', ['r'], data['previous_facts'][0]['fact_id'], reason=''),
                fact('Prezydent odmówił przyjęcia dymisji.', ['r']),
            ], data['all_articles'])

        result = p.generate({'topic': {}, 'all_articles': rows}, repair_protocol(call), ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_article_coverage', 'perspective_summary'])
        self.assertEqual([(f['text_pl'], f['article_ids']) for f in result['perspective_facts']], [
            ('Minister złożył dymisję.', ['l', 'r']),
            ('Prezydent odmówił przyjęcia dymisji.', ['r']),
        ])

    def test_confirmations_after_repair_do_not_create_news_or_rewrite_the_base(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        known = p.route_facts({'facts': [fact('Decyzja zapadła.', ['l'], kind='FACT')]},
                              rows, [], ai.normalize_generated_text)[1]
        base = {'perspective_version': 1, 'summary_pl': 'Pierwotny artykuł.',
                'general_context': {'text_pl': 'Wcześniejszy kontekst.'}, 'perspective_facts': known}
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            self.assertIn(name, ('perspective_facts', 'perspective_article_coverage'))
            result = extraction([fact('', ['l'], known[0]['fact_id'])], data['all_articles'])
            if len(calls) == 1:
                result['article_coverage']['r']['no_relevant_facts_reason_pl'] = 'Brak nowych informacji.'
            else:
                result = extraction([fact('', ['r'], known[0]['fact_id'])], data['all_articles'])
            return result

        # A new citation within a profile, without broadening cross-profile
        # support, is not a visible update. Use two sources of the same profile.
        rows[1]['source_profile'] = 'LEFT'
        result = p.generate({'topic': {}, 'all_articles': rows, 'new_article_ids': ['r'],
                             'previous_aggregation': {'base_summary': base}}, repair_protocol(call), ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_article_coverage'])
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(result['summary_pl'], base['summary_pl'])
        self.assertEqual(result['general_context'], base['general_context'])
        self.assertEqual(result['perspective_facts'][0]['article_ids'], ['l', 'r'])

    def test_unresolved_coverage_cannot_publish_or_mark_a_partial_topic_processed(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        calls, retries = [], []

        def call(instructions, data, schema, name):
            calls.append((name, [a['article_id'] for a in data['all_articles']]))
            self.assertIn(name, ('perspective_facts', 'perspective_article_coverage'))  # Never reach the writer.
            result = extraction([fact('Poprawny fakt.', ['l'])] if len(calls) == 1 else [], data['all_articles'])
            result['article_coverage']['r']['no_relevant_facts_reason_pl'] = ''
            return result

        payload = {'topic': {}, 'all_articles': rows}
        original = copy.deepcopy(payload)
        with self.assertRaisesRegex(ValueError, 'Artykuł r wymaga faktów'):
            p.generate(payload, repair_protocol(call), ai.normalize_generated_text,
                       on_validation_retry=lambda *args: retries.append(args))
        self.assertEqual(calls, [('perspective_facts', ['l', 'r']), ('perspective_article_coverage', ['r']), ('perspective_article_coverage', ['r'])])
        self.assertEqual(len(retries), 1)
        self.assertEqual(payload, original)

    def test_an_explained_unrelated_article_does_not_get_fabricated_citations(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_summary':
                return written(data)
            if len(calls) == 1:
                result = extraction([fact('Poprawny fakt.', ['l'])], rows)
                result['article_coverage']['r']['no_relevant_facts_reason_pl'] = ''
                return result
            return extraction([], data['all_articles'])  # Explicit off-topic reason.

        result = p.generate({'topic': {}, 'all_articles': rows}, repair_protocol(call), ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_article_coverage', 'perspective_summary'])
        self.assertEqual(result['perspective_facts'][0]['article_ids'], ['l'])

    def test_pipeline_reports_successful_repair_without_leaving_the_omission_unhandled(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        calls = []

        def request(instructions, data, model, **settings):
            name = settings['response_schema_name']
            calls.append(name)
            if name == 'perspective_summary':
                return written(data)
            if len(calls) == 1:
                result = extraction([fact('Poprawny fakt.', ['l'])], rows)
                result['article_coverage']['r']['no_relevant_facts_reason_pl'] = ''
                return result
            return coverage_reply(extraction([fact('', ['r'], data['previous_facts'][0]['fact_id'], reason='')], data['all_articles']))

        with patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log') as log:
            result = ai.generate_summary_response({'topic': {}, 'all_articles': rows}, 'gpt-5-nano')
        self.assertEqual(result['perspective_facts'][0]['article_ids'], ['l', 'r'])
        self.assertTrue(any('Kontrola pokrycia: uzupełniam 1' in str(c) for c in log.call_args_list))
        self.assertFalse(any(c.kwargs.get('level') == 'WARN' for c in log.call_args_list))
        self.assertEqual(calls, ['perspective_facts', 'perspective_article_coverage', 'perspective_summary'])


if __name__ == '__main__':
    unittest.main()
