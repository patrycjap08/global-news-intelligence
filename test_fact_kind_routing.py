import copy
import unittest
from unittest.mock import patch

import jsonschema

import ai_pipeline as ai
import perspective_summaries as p
from test_perspective_summaries import article, extraction, fact
from test_topic_titles import FakeMergeClient


class FactKindRoutingTests(unittest.TestCase):
    def route(self, rows, facts, known=()):
        return p.route_facts({'facts': facts}, rows, list(known), ai.normalize_generated_text)

    def test_neutral_details_and_attributed_claims_are_independent_of_outlet_profile(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT'), article('c', 'CENTER'), article('s', 'STATE_ALIGNED')]
        _, facts = self.route(rows, [
            fact('Numer lotu to OS82.', ['l'], kind='FACT'),
            fact('Tunel ma mieć 12 km.', ['r'], kind='FACT'),
            fact('Minister zapowiada, że tunel odciąży miasto.', ['r'], kind='STATEMENT'),
            fact('Opozycja nazwała plan skandalicznym.', ['l'], kind='STATEMENT'),
            fact('Autor ocenia plan jako skandaliczny.', ['l'], kind='EDITORIAL'),
            fact('Autor ocenia plan jako nieodpowiedzialny.', ['c'], kind='EDITORIAL'),
            fact('Według państwowej agencji: zapowiedź.', ['s'], kind='STATEMENT'),
        ])
        self.assertEqual([f['lane'] for f in facts], ['COMMON'] * 4 + ['EDITORIAL', 'EDITORIAL', 'STATE'])
        sections = p.fact_sections(facts)
        self.assertEqual(len(sections['LEFT']), 1)
        self.assertEqual(len(sections['CENTER']), 1)
        self.assertEqual(sections['RIGHT'], [])
        self.assertEqual(facts[2]['text_pl'], 'Minister zapowiada, że tunel odciąży miasto.')

    def test_shared_assessment_is_not_promoted_to_fact_and_citations_stay_per_group(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT'), article('c', 'CENTER')]
        _, facts = self.route(rows, [fact('Autorzy uznają plan za ryzykowny.', ['l', 'r', 'c'], kind='EDITORIAL')])
        self.assertEqual(facts[0]['lane'], 'EDITORIAL')
        sections = p.fact_sections(facts)
        self.assertEqual(sections['COMMON'], [])
        for group, aid in [('LEFT', 'l'), ('RIGHT', 'r'), ('CENTER', 'c')]:
            self.assertEqual(sections[group][0]['article_ids'], [aid])
            self.assertEqual(sections[group][0]['fact_id'], facts[0]['fact_id'])

    def test_single_profile_never_turns_editorial_assessment_into_neutral_information(self):
        for profile in ('LEFT', 'RIGHT', 'CENTER'):
            with self.subTest(profile=profile):
                mode, facts = self.route([article('a', profile)], [fact('Autor krytykuje plan.', ['a'], kind='EDITORIAL')])
                self.assertEqual(mode, 'SINGLE_' + profile)
                self.assertEqual(facts[0]['lane'], 'EDITORIAL')
        _, state = self.route([article('s', 'STATE_ALIGNED')],
                              [fact('Agencja państwowa ocenia plan.', ['s'], kind='EDITORIAL')])
        self.assertEqual(state[0]['lane'], 'STATE')

    def test_two_calls_keep_full_articles_order_shared_core_first_and_exclude_editorials(self):
        rows = [{**article(key, profile), 'body_original': key * 1000}
                for key, profile in [('l', 'LEFT'), ('r', 'RIGHT'), ('c', 'CENTER'), ('s', 'STATE_ALIGNED')]]
        extracted = [fact('Dodatkowy numer lotu OS82.', ['l'], kind='FACT'),
                     fact('Minister zapowiada kontrolę.', ['r'], kind='STATEMENT'),
                     fact('Samolot bezpiecznie wylądował.', ['l', 'r'], kind='FACT'),
                     fact('Lot kontynuowano.', ['c'], kind='FACT'),
                     fact('Autor krytykuje działania władz.', ['r'], kind='EDITORIAL'),
                     fact('Według agencji państwowej: komunikat.', ['s'], kind='FACT')]
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_facts':
                self.assertEqual([a['body_original'] for a in data['all_articles']], [a['body_original'] for a in rows])
                response = extraction(extracted, data['all_articles'])
                jsonschema.validate(response, schema)
                return response
            self.assertEqual([f['text_pl'] for f in data['main_facts']],
                             [extracted[i]['text_pl'] for i in (2, 3, 0, 1)])
            self.assertEqual(data['core_fact_count'], 2)
            self.assertTrue(all(f['kind'] in ('FACT', 'STATEMENT') for f in data['main_facts']))
            self.assertNotIn('s', [a['article_id'] for a in data['main_sources']])
            response = {'paragraphs': [{'text_pl': 'Pierwszy akapit.', 'fact_ids': [f['fact_id'] for f in data['main_facts'][:2]]},
                                       {'text_pl': 'Drugi akapit z przypisaniem.', 'fact_ids': [f['fact_id'] for f in data['main_facts'][2:]]}],
                        'general_context': {'text_pl': 'Tło.', 'article_ids': [], 'needs_verification': True},
                        'background_context': []}
            jsonschema.validate(response, schema)
            return response

        result = p.generate({'topic': {}, 'all_articles': rows}, call, ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_summary'])
        self.assertEqual(result['summary_pl'], 'Pierwszy akapit.\n\nDrugi akapit z przypisaniem.')
        self.assertEqual(result['fact_classification_version'], 1)
        self.assertEqual(result['perspective_sections']['RIGHT'][0]['kind'], 'EDITORIAL')
        self.assertEqual(result['perspective_sections']['LEFT'], [])

    def test_classifying_existing_fact_does_not_publish_update_or_rewrite_base(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        _, known = self.route(rows, [fact('Numer lotu to OS82.', ['l'])])  # Older untyped record.
        self.assertEqual(known[0]['lane'], 'LEFT')
        base = {'perspective_version': 1, 'summary_pl': 'Pierwotna synteza.',
                'background_context': [{'text_pl': 'Pierwotny kontekst.'}], 'perspective_facts': known}
        frozen = copy.deepcopy(base)
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            self.assertEqual(name, 'perspective_facts')
            return extraction([fact('', ['l'], known[0]['fact_id'], reason='', kind='FACT')], data['all_articles'])

        result = p.generate({'topic': {}, 'all_articles': rows,
                             'previous_aggregation': {'base_summary': base}}, call, ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts'])
        self.assertEqual(result['facts'][0]['kind'], 'FACT')
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(result['summary_pl'], frozen['summary_pl'])
        self.assertEqual(base, frozen)
        client = FakeMergeClient([], [], [])
        ai.persist_summary(client, topic_id='t', run_id='r', model='fake', summary=result,
                           summary_hash='h', previous_row={'version': 1, 'summary': {'base_summary': base, 'updates': []}},
                           new_article_ids=['l'])
        saved = [items[0]['summary'] for table, items, _ in client.upserts if table == 'topic_summaries'][-1]
        self.assertEqual(saved['base_summary'], frozen)
        self.assertEqual(saved['updates'], [])
        self.assertEqual(saved['perspective_state']['fact_classification_version'], 1)

    def test_real_broader_support_of_already_neutral_fact_is_still_detected(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        _, known = self.route(rows, [fact('Znana decyzja.', ['l'], kind='FACT')])
        _, confirmed = self.route(rows, [fact('', ['r'], known[0]['fact_id'], reason='', kind='FACT')], known)
        self.assertEqual(known[0]['lane'], 'COMMON')
        update = p.make_update(confirmed, known, True, ['r'], {a['article_id']: a for a in rows})
        self.assertEqual(update['status'], 'NEW_INFORMATION')
        self.assertEqual(len(update['promoted_facts']), 1)
        again = p.make_update(confirmed, confirmed, True, ['r'], {a['article_id']: a for a in rows})
        self.assertEqual(again['status'], 'NO_NEW_INFORMATION')

    def test_pipeline_normalization_keeps_fact_types_and_uses_existing_two_requests(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        def response(instructions, data, model, **settings):
            if settings['response_schema_name'] == 'perspective_facts':
                return extraction([fact('Minister zapowiedział kontrolę.', ['l'], kind='STATEMENT'),
                                   fact('Autor krytykuje kontrolę.', ['r'], kind='EDITORIAL')], rows)
            self.assertEqual([f['kind'] for f in data['main_facts']], ['STATEMENT'])
            return {'paragraphs': [{'text_pl': 'Minister zapowiedział kontrolę.',
                                    'fact_ids': [data['main_facts'][0]['fact_id']]}],
                    'general_context': {'text_pl': 'Tło.', 'article_ids': [], 'needs_verification': True},
                    'background_context': []}
        with patch.object(ai, 'call_openai', side_effect=response) as request, patch.object(ai, 'log'):
            result = ai.generate_summary_response({'topic': {}, 'all_articles': rows}, 'fake')
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result['facts'][0]['kind'], 'STATEMENT')
        self.assertEqual(result['fact_classification_version'], 1)
        self.assertEqual(result['perspective_sections']['RIGHT'][0]['kind'], 'EDITORIAL')

    def test_known_classification_is_protected_by_schema_and_validation(self):
        rows = [article('l', 'LEFT')]
        _, known = self.route(rows, [fact('Znana decyzja.', ['l'], kind='FACT')])
        bad = extraction([fact('', ['l'], known[0]['fact_id'], reason='', kind='EDITORIAL')], rows)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, p.extraction_schema(known, ['l']))
        # The schema still requests the established type. If a caller sends a
        # conflicting type anyway, the ledger keeps its existing classification.
        self.assertEqual(self.route(rows, bad['facts'], known)[1], known)
        for kind in (None, 'UNKNOWN'):
            with self.subTest(kind=kind):
                response = extraction([fact('Decyzja.', ['l'])], rows)
                response['facts'][0]['kind'] = kind
                calls = []
                def call(*args):
                    calls.append(args[-1])
                    return copy.deepcopy(response)
                with self.assertRaisesRegex(ValueError, 'musi mieć typ'):
                    p.generate({'topic': {}, 'all_articles': rows}, call, ai.normalize_generated_text)
                self.assertEqual(calls, ['perspective_facts', 'perspective_facts'])

    def test_cross_batch_editorial_support_and_slim_known_context(self):
        rows = [{**article(key, profile), 'body_original': key * 200}
                for key, profile in [('l', 'LEFT'), ('c', 'CENTER')]]
        calls = []
        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_summary':
                self.assertEqual(data['main_facts'], [])
                return {'paragraphs': [], 'general_context': {'text_pl': '', 'article_ids': [], 'needs_verification': False},
                        'background_context': []}
            known = data['previous_facts']
            self.assertTrue(all('editorial_sources' not in f for f in known))
            current = data['all_articles'][0]['article_id']
            response = extraction([fact('' if known else 'Autor ocenia projekt jako ryzykowny.', [current],
                                        known[0]['fact_id'] if known else '',
                                        reason='' if known else 'Pierwsza ocena.', kind='EDITORIAL')], data['all_articles'])
            jsonschema.validate(response, schema)
            return response
        result = p.generate({'topic': {}, 'all_articles': rows}, call, ai.normalize_generated_text, max_payload_chars=100)
        self.assertEqual(calls, ['perspective_facts', 'perspective_facts', 'perspective_summary'])
        self.assertFalse(result['shared_available'])
        self.assertEqual(result['perspective_sections']['LEFT'][0]['article_ids'], ['l'])
        self.assertEqual(result['perspective_sections']['CENTER'][0]['article_ids'], ['c'])


if __name__ == '__main__':
    unittest.main()
