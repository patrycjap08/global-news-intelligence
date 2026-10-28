"""Reader context lives in narrative, with one writing call and no new facts."""
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
from test_writing_fixtures import article_response, paired_article_response

DATA = json.loads(Path(__file__).with_name('test_data').joinpath('texas_context_20261021.json').read_text())


def articles():
    return [{**a, 'body_original': '\n\n'.join(DATA['context_quotes'][a['article_id']])} for a in DATA['articles']]


def stored():
    return {'base_summary': copy.deepcopy(DATA['current_summary']),
            'current_summary': copy.deepcopy(DATA['current_summary']),
            'perspective_state': {'perspective_facts': copy.deepcopy(DATA['facts']), 'facts': copy.deepcopy(DATA['facts'])},
            'processed_article_ids': [a['article_id'] for a in DATA['articles']]}


def written():
    name = '(Transgender Education Network of Texas, organizacja wspierająca osoby transpłciowe w Teksasie)'
    postal = '(United States Postal Service, amerykańskiego operatora pocztowego)'
    history = 'Działa od 2010 roku.'
    registry = 'Spółkę o tej nazwie zarejestrowano we wrześniu 2026 roku.'
    return {'situation_context': {'text_pl': 'Sprawa dotyczy niejasnego nadawcy listów o zasobach dla osób transpłciowych w Teksasie. Wskazanie organizacji w ulotce nie przesądza, że przygotowała ona lub rozesłała materiały.', 'basis': 'SUPPLIED_MATERIAL'}, 'entity_context': [], 'paragraphs': [
        {'text_pl': 'Do rodzin w Teksasie trafiły SMS-y i listy dotyczące zasobów dla osób transpłciowych; jako nadawca widnieje Texas Transgender Student Union. ' + registry,
         'fact_ids': [DATA['facts'][2]['fact_id']],
         'context_spans': [{'text_pl': registry, 'basis': 'SUPPLIED_MATERIAL'}]},
        {'text_pl': f'TENT {name} zaprzeczyła swojemu udziałowi w wysyłce ulotki. {history}',
         'fact_ids': [DATA['facts'][0]['fact_id']],
         'context_spans': [{'text_pl': name, 'basis': 'GENERAL_KNOWLEDGE'}, {'text_pl': history, 'basis': 'SUPPLIED_MATERIAL'}]},
        {'text_pl': f'CBS News zwróciło się o komentarz do USPS {postal}, ale nie otrzymało odpowiedzi.',
         'fact_ids': [DATA['facts'][1]['fact_id']],
         'context_spans': [{'text_pl': postal, 'basis': 'GENERAL_KNOWLEDGE'}]},
    ]}


def article_written():
    registry = 'Spółkę o tej nazwie zarejestrowano we wrześniu 2026 roku.'
    tent = '(organizacja wspierająca osoby transpłciowe)'
    postal = '(amerykańska poczta)'
    return article_response([
        {'text_pl': 'Do rodzin w Teksasie trafiły SMS-y i listy dotyczące zasobów dla osób transpłciowych. Jako nadawca widnieje Texas Transgender Student Union. ' + registry,
         'fact_ids': [DATA['facts'][2]['fact_id']]},
        {'text_pl': f'TENT {tent} zaprzeczyła swojemu udziałowi w wysyłce ulotki.',
         'fact_ids': [DATA['facts'][0]['fact_id']]},
        {'text_pl': f'CBS News zwróciło się o komentarz do USPS {postal}, ale nie otrzymało odpowiedzi.',
         'fact_ids': [DATA['facts'][1]['fact_id']]}], [
             {'text_pl': registry, 'basis': 'SUPPLIED_MATERIAL', 'kind': 'SITUATION'},
             {'text_pl': tent, 'basis': 'GENERAL_KNOWLEDGE', 'kind': 'ENTITY'},
             {'text_pl': postal, 'basis': 'GENERAL_KNOWLEDGE', 'kind': 'ENTITY'}])


class InlineContextTests(unittest.TestCase):
    def test_context_from_memory_and_source_passages_survives_inline(self):
        response = written()
        schema = p.writing_schema(DATA['facts'], inline_context=True)
        check_response_schema(schema)
        jsonschema.validate(response, schema)
        self.assertEqual(set(schema['required']), {'situation_context', 'entity_context', 'paragraphs'})
        result = p.safe_inline_written(response, DATA['facts'])
        self.assertEqual(len(result['paragraphs']), 3)
        self.assertEqual(len(result['narrative_context']), 4)
        self.assertIn('2010', result['paragraphs'][1]['text_pl'])
        self.assertIn('operatora pocztowego', result['paragraphs'][2]['text_pl'])
        self.assertEqual(result['background_context'], [])
        self.assertIsNone(result['general_context'])
        self.assertNotIn('article_ids', result['narrative_context'][0], 'General knowledge is not an article confirmation')

    def test_context_cannot_replace_the_whole_event_or_hide_an_unmarked_changed_number(self):
        main = [{'fact_id': 'f', 'article_ids': ['a'], 'text_pl': 'Policja zatrzymała 8 osób w Marsylii.'}]
        valid = {'text_pl': 'Policja zatrzymała 8 osób w Marsylii (mieście na południu Francji).',
                 'fact_ids': ['f'], 'context_spans': [{'text_pl': '(mieście na południu Francji)', 'basis': 'GENERAL_KNOWLEDGE'}]}
        bad = []
        row = copy.deepcopy(valid); row['text_pl'] = row['text_pl'].replace('8', '300'); bad.append(row)
        row = copy.deepcopy(valid); row['fact_ids'] = ['alien']; bad.append(row)
        row = copy.deepcopy(valid); row['context_spans'][0]['text_pl'] = row['text_pl']; bad.append(row)
        row = copy.deepcopy(valid); row['context_spans'][0]['text_pl'] = 'Nieobecny fragment'; bad.append(row)
        row = copy.deepcopy(valid); row['context_spans'][0]['basis'] = 'UNVERIFIED_EVENT'; bad.append(row)
        row = copy.deepcopy(valid); row['context_spans'] = [{}]; bad.append(row)
        for paragraph in bad:
            with self.subTest(paragraph=paragraph):
                self.assertEqual(p.safe_inline_written({'paragraphs': [paragraph]}, main)['paragraphs'], [])
        self.assertEqual(len(p.safe_inline_written({'paragraphs': [valid]}, main)['paragraphs']), 1)

    def test_optional_source_passages_are_bounded_and_exclude_state_sources(self):
        rows = [{**articles()[0], 'article_id': str(i), 'source_profile': 'STATE_ALIGNED' if i == 0 else 'CENTER',
                 'body_original': (f'Organization number {i} was founded in 2010 and registered in Wyoming.\n' * 150)} for i in range(20)]
        sources = p.context_source_passages(rows, [])
        self.assertEqual(len(sources), 3)
        self.assertNotIn('0', [s['article_id'] for s in sources])
        self.assertLessEqual(sum(len(text) for source in sources for text in source['passages']), 3600)
        for source in sources:
            original = next(a['body_original'] for a in rows if a['article_id'] == source['article_id'])
            self.assertTrue(all(text in original for text in source['passages']))

    def test_texas_gets_one_writer_no_extraction_and_context_never_becomes_a_fact(self):
        calls = []
        previous = stored()
        def call(instructions, data, schema, name):
            calls.append(name)
            self.assertEqual(name, 'perspective_summary')
            self.assertIn('KONTEKST WPLEĆ W SYNTEZĘ', instructions)
            self.assertIn('dobrze ugruntowaną wiedzę ogólną', instructions)
            self.assertIn('Prezydentów państw nie trzeba', instructions)
            self.assertIn('context_sources', data)
            response = paired_article_response(article_written())
            jsonschema.validate(response, schema)
            return response
        payload = {'topic': {'topic_id': DATA['topic']['topic_id'], 'working_title_pl': DATA['topic']['headline_pl']},
                   'all_articles': articles(), 'new_article_ids': [], 'previous_aggregation': previous}
        result = p.generate(payload, call, ai.normalize_generated_text, allow_omissions=True)
        self.assertEqual(calls, ['perspective_summary'])
        self.assertEqual(result['quality_report']['read_articles'], 0)
        self.assertEqual(result['inline_context_version'], integrity.INLINE_CONTEXT_VERSION)
        self.assertEqual(result['background_context'], [])
        self.assertEqual(len(result['facts']), len(DATA['facts']))
        self.assertFalse(any('2010' in f['text_pl'] for f in result['facts']))
        self.assertIn('2026', result['summary_pl'])
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        previous['current_summary'] = result
        previous['perspective_state'] = result['perspective_state']
        p.generate(payload, lambda *args: self.fail('No repeated context writing'), ai.normalize_generated_text, allow_omissions=True)

    def test_empty_context_attempt_is_not_repeated_without_new_information(self):
        previous = stored()
        def call(*args):
            primary = integrity.primary_fact(DATA['facts'], DATA['topic']['headline_pl'])
            return article_response([{'text_pl': primary['text_pl'], 'fact_ids': [primary['fact_id']]}])
        payload = {'topic': {'topic_id': DATA['topic']['topic_id'], 'working_title_pl': DATA['topic']['headline_pl']},
                   'all_articles': articles(), 'new_article_ids': [], 'previous_aggregation': previous}
        result = p.generate(payload, call, ai.normalize_generated_text, allow_omissions=True)
        self.assertEqual(result['narrative_context'], [])
        self.assertEqual(result['inline_context_version'], integrity.INLINE_CONTEXT_VERSION)
        previous['current_summary'] = result
        p.generate(payload, lambda *args: self.fail('Do not pay again for missing context'), ai.normalize_generated_text, allow_omissions=True)

    def test_queue_refreshes_unexplained_acronyms_once_even_without_source_passages(self):
        self.assertTrue(integrity.needs_inline_context({**DATA['current_summary'], 'inline_context_version': None}))
        self.assertFalse(integrity.needs_inline_context({**DATA['current_summary'],
            'summary_pl': 'TENT (organizacja wspierająca osoby transpłciowe) zaprzeczyła udziałowi. USPS (amerykańska poczta) nie odpowiedziało.'}))
        topic = {**DATA['topic'], 'last_seen_at': '2026-10-07T12:00:00Z'}
        tid = topic['topic_id']
        rows = [(a['article_id'], a['source_id'], a['source_profile']) for a in DATA['articles']]
        links = [{'topic_id': tid, 'article_id': a[0]} for a in rows]
        assignments = [{**l, 'created_at': '2026-10-07T10:00:00Z'} for l in links]
        summaries = [{'topic_id': tid, 'version': 1, 'summary': stored(), 'updated_at': '2026-10-07T11:00:00Z'}]
        h = queue_tests.SummaryQueueTests()
        stats, generate, persist, _ = h.run_queue([topic], rows, links, summaries, assignments)
        self.assertEqual(stats['summaries'], 1)
        generate.assert_called_once()
        self.assertEqual(persist.call_args.kwargs['new_article_ids'], [])
        summaries[0]['summary']['current_summary']['inline_context_version'] = 1
        summaries[0]['summary']['current_summary']['situation_context_version'] = integrity.SITUATION_CONTEXT_VERSION
        summaries[0]['summary']['current_summary']['brief_generation_version'] = integrity.BRIEF_GENERATION_VERSION
        stats, generate, persist, _ = h.run_queue([topic], rows, links, summaries, assignments)
        self.assertEqual(stats['summaries'], 0)
        generate.assert_not_called()

    def test_normalization_and_database_save_keep_the_once_only_marker(self):
        from test_topic_titles import FakeMergeClient
        previous = stored()
        payload = {'topic': {'topic_id': DATA['topic']['topic_id'], 'working_title_pl': DATA['topic']['headline_pl']},
                   'all_articles': articles(), 'new_article_ids': [], 'previous_aggregation': previous}
        with patch.object(ai, 'call_openai', return_value=article_written()) as request, patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['retry_limit'], 1)
        self.assertEqual(result['inline_context_version'], integrity.INLINE_CONTEXT_VERSION)
        self.assertEqual(len(result['narrative_context']), 3)
        client = FakeMergeClient([], [], [])
        ai.persist_summary(client, topic_id=DATA['topic']['topic_id'], run_id='test', model='fake',
            summary=result, summary_hash='h', previous_row={'version': 1, 'summary': previous}, new_article_ids=[])
        saved = next(rows[0]['summary'] for table, rows, _ in client.upserts if table == 'topic_summaries')
        self.assertEqual(saved['current_summary']['inline_context_version'], integrity.INLINE_CONTEXT_VERSION)
        self.assertFalse(integrity.needs_inline_context(saved['current_summary']))
        self.assertEqual(saved['current_summary']['narrative_context'], result['narrative_context'])
        payload['previous_aggregation'] = saved
        with patch.object(ai, 'call_openai') as request, patch.object(ai, 'log'):
            ai.generate_summary_response(payload, 'gpt-5-nano')
        request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
