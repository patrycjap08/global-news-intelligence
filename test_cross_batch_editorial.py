"""Batch boundaries preserve confirmations and distinct editorial readings."""
import copy
import unittest
from unittest.mock import patch

import jsonschema
import ai_pipeline as ai
import perspective_summaries as p
from test_editorial_integrity import article, claim, extraction, writer
from test_novelty_decisions_and_resume import decision


FACT = 'Rząd przyjął reformę transportu publicznego.'


def rows(count):
    return [article(f'a{i:02}', FACT, ('LEFT', 'CENTER', 'RIGHT')[i % 3]) for i in range(count)]


def confirmations(data, text=FACT):
    known = next((f for f in data['previous_facts'] if f['text_pl'] == text), None)
    specs = []
    for a in data['all_articles']:
        item = claim('' if known else text, a['article_id'])
        if known:
            item.update(known_fact_id=known['fact_id'], why_new_pl='')
        specs.append(item)
    return specs


class CrossBatchEditorialTests(unittest.TestCase):
    def test_seventeen_articles_share_one_growing_fact_register_across_three_batches(self):
        articles = rows(17)
        reads, stages, previous_counts = [], [], []
        def call(instructions, data, model, **settings):
            name = settings['response_schema_name']
            stages.append(name)
            if name == 'perspective_facts':
                previous_counts.append(len(data['previous_facts']))
                reads.append([a['article_id'] for a in data['all_articles']])
                self.assertTrue(all(set(f) <= {'fact_id', 'text_pl', 'kind', 'attribution'} for f in data['previous_facts']))
                reply = extraction(data, confirmations(data))
            else:
                self.assertEqual(name, 'perspective_summary', 'No redundant audit of an already identified single fact')
                self.assertEqual(len(data['main_facts']), 1)
                self.assertEqual(len(data['main_facts'][0]['article_ids']), 17)
                reply = writer(data)
            jsonschema.validate(reply, settings['response_schema'])
            return reply
        with patch.object(ai, 'call_openai', side_effect=call), patch.object(ai, 'log'):
            result = ai.generate_summary_response({'topic': {'working_title_pl': '[Polska] Reforma transportu publicznego'},
                                                   'all_articles': articles}, 'gpt-6-luna')
        self.assertEqual(list(map(len, reads)), [8, 8, 1])
        self.assertEqual(previous_counts, [0, 1, 1])
        self.assertEqual(sum(reads, []), [a['article_id'] for a in articles])
        self.assertEqual(stages, ['perspective_facts'] * 3 + ['perspective_summary'])
        self.assertEqual(len(result['perspective_facts']), 1)
        self.assertEqual(result['summary_pl'], FACT)
        self.assertEqual(result['quality_report']['read_articles'], 17)

    def test_new_batches_only_confirming_a_published_fact_do_not_buy_an_audit_or_writer(self):
        old = article('old', FACT)
        articles = [old, *rows(9)]
        _, known = p.route_facts({'facts': [claim(FACT, 'old')]}, articles, [], ai.normalize_generated_text)
        current = {'summary_pl': FACT, 'publication_version': 2, 'perspective_version': 1,
                   'inline_context_version': 2, 'situation_context_version': 1, 'perspective_facts': known}
        payload = {'topic': {'working_title_pl': '[Polska] Reforma transportu publicznego'}, 'all_articles': articles,
                   'new_article_ids': [a['article_id'] for a in articles[1:]],
                   'previous_aggregation': {'base_summary': current, 'current_summary': current,
                       'perspective_state': {'facts': known, 'perspective_facts': known}, 'processed_article_ids': ['old']}}
        original, stages = copy.deepcopy(payload), []
        def call(instructions, data, model, **settings):
            stages.append(settings['response_schema_name'])
            self.assertEqual(stages[-1], 'perspective_facts')
            self.assertNotIn('old', [a['article_id'] for a in data['all_articles']])
            self.assertEqual(len(data['previous_facts']), 1)
            reply = extraction(data, confirmations(data))
            jsonschema.validate(reply, settings['response_schema'])
            return reply
        with patch.object(ai, 'call_openai', side_effect=call), patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-6-luna')
        self.assertEqual(stages, ['perspective_facts', 'perspective_facts'])
        self.assertEqual(len(result['perspective_facts']), 1)
        self.assertEqual(len(result['perspective_facts'][0]['article_ids']), 10)
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(result['summary_pl'], FACT)
        self.assertEqual(payload, original)

    def test_audit_catches_a_paraphrase_accidentally_marked_new_in_the_second_batch(self):
        articles = rows(9)
        paraphrase = 'Reforma transportu publicznego została przyjęta przez rząd.'
        stages = []
        def call(instructions, data, model, **settings):
            name = settings['response_schema_name']; stages.append(name)
            if name == 'perspective_facts':
                specs = confirmations(data) if not data['previous_facts'] else [claim(paraphrase, 'a08')]
                reply = extraction(data, specs)
            elif name == 'perspective_novelty_audit':
                self.assertNotIn('all_articles', data)
                self.assertEqual([f['text_pl'] for f in data['candidate_facts']], [FACT, paraphrase])
                reply = {'decisions': {'C1': decision('NEW'), 'C2': decision('DUPLICATE', ['C1'])}}
            else:
                self.assertEqual(len(data['main_facts']), 1)
                reply = writer(data)
            jsonschema.validate(reply, settings['response_schema'])
            return reply
        with patch.object(ai, 'call_openai', side_effect=call), patch.object(ai, 'log'):
            result = ai.generate_summary_response({'topic': {}, 'all_articles': articles}, 'gpt-6-luna')
        self.assertEqual(stages, ['perspective_facts', 'perspective_facts', 'perspective_novelty_audit', 'perspective_summary'])
        self.assertEqual(len(result['perspective_facts']), 1)
        self.assertEqual(len(result['perspective_facts'][0]['article_ids']), 9)
        self.assertEqual(result['summary_pl'], FACT)

    def test_opposite_editorial_readings_survive_across_batches_and_stay_out_of_the_factual_synthesis(self):
        articles = rows(9)
        articles[0].update(source_name='Lewy Dziennik', source_profile='LEFT',
            body_original=FACT + ' Znów zabrakło przygotowania. Chaotyczne poprawki dorzucono w ostatniej chwili. Kolejna rządowa improwizacja.')
        articles[8].update(source_name='Prawy Dziennik', source_profile='RIGHT',
            body_original=FACT + ' Wreszcie sprawne działanie. Dopracowane rozwiązania kończą lata bezczynności. Tak realizuje się obietnice.')
        negative = 'Artykuł Lewego Dziennika przedstawia reformę krytycznie, akcentując chaos w przygotowaniu i improwizację władz.'
        positive = 'Artykuł Prawego Dziennika przedstawia reformę pozytywnie, podkreślając sprawność działań i realizację obietnic.'
        stages = []
        def call(instructions, data, model, **settings):
            name = settings['response_schema_name']; stages.append(name)
            if name == 'perspective_facts':
                specs = confirmations(data)
                if any(a['article_id'] == 'a00' for a in data['all_articles']):
                    specs.append(claim(negative, 'a00', 'EDITORIAL', 'Lewy Dziennik'))
                if any(a['article_id'] == 'a08' for a in data['all_articles']):
                    self.assertTrue(any(f['text_pl'] == negative for f in data['previous_facts']))
                    specs.append(claim(positive, 'a08', 'EDITORIAL', 'Prawy Dziennik'))
                reply = extraction(data, specs)
            elif name == 'perspective_novelty_audit':
                self.assertEqual([f['kind'] for f in data['candidate_facts']].count('EDITORIAL'), 2)
                reply = {'decisions': {f['fact_id']: decision('NEW') for f in data['candidate_facts']}}
            else:
                self.assertEqual([f['text_pl'] for f in data['main_facts']], [FACT])
                reply = writer(data)
            jsonschema.validate(reply, settings['response_schema'])
            return reply
        with patch.object(ai, 'call_openai', side_effect=call), patch.object(ai, 'log'):
            result = ai.generate_summary_response({'topic': {}, 'all_articles': articles}, 'gpt-6-luna')
        opinions = result['perspective_sections']['EDITORIAL']
        self.assertEqual(len(result['facts']), 1)
        self.assertEqual(len(opinions), 2)
        self.assertEqual({f['attribution'] for f in opinions}, {'Lewy Dziennik', 'Prawy Dziennik'})
        by_text = {f['text_pl']: f for f in opinions}
        self.assertEqual(by_text[negative]['article_ids'], ['a00'])
        self.assertEqual(by_text[negative]['editorial_sources'], {'LEFT': ['a00']})
        self.assertEqual(by_text[positive]['article_ids'], ['a08'])
        self.assertEqual(by_text[positive]['editorial_sources'], {'RIGHT': ['a08']})
        self.assertEqual(result['summary_pl'], FACT)
        self.assertEqual(stages, ['perspective_facts', 'perspective_facts', 'perspective_novelty_audit', 'perspective_summary'])


if __name__ == '__main__':
    unittest.main()
