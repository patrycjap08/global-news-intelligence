"""A separate short read, with no extra writer call on a new publication."""
import copy
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import jsonschema
import ai_pipeline as ai
import editorial_integrity as integrity
import perspective_summaries as p
from structured_outputs import check_response_schema
from test_publication_flow import PersistingClient
from test_writing_fixtures import article_response


FACTS = [
    {'fact_id': 'f1', 'text_pl': 'Rada miasta przyjęła program budowy trzech nowych szkół.',
     'kind': 'FACT', 'lane': 'COMMON', 'article_ids': ['a', 'b']},
    {'fact_id': 'f2', 'text_pl': 'Budowa szkół ma rozpocząć się w 2027 roku.',
     'kind': 'FACT', 'lane': 'COMMON', 'article_ids': ['a', 'b']},
    {'fact_id': 'f3', 'text_pl': 'Inwestycje mają zapewnić miejsca dla 1200 uczniów.',
     'kind': 'FACT', 'lane': 'COMMON', 'article_ids': ['a', 'b']},
]
ARTICLES = [{'article_id': aid, 'source_id': aid, 'source_name': aid,
             'source_profile': 'CENTER', 'body_original': 'NEVER_RESEND_ARTICLE'} for aid in ('a', 'b')]
BRIEF = [
    {'text_pl': 'Rada miasta przyjęła program budowy trzech nowych szkół dla 1200 uczniów.',
     'fact_ids': ['f1', 'f3']},
    {'text_pl': 'Budowa szkół ma rozpocząć się w 2027 roku.', 'fact_ids': ['f2']},
]
FULL = '\n\n'.join(f['text_pl'] for f in FACTS)


def stored():
    current = {'topic': {'headline_pl': '[Polska] Budowa szkół'}, 'summary_pl': FULL,
               'perspective_version': 1, 'publication_version': 2, 'coverage_mode': 'SINGLE_CENTER',
               'inline_context_version': 2, 'situation_context_version': 1}
    return {'base_summary': copy.deepcopy(current), 'current_summary': current,
            'perspective_state': {'facts': copy.deepcopy(FACTS), 'perspective_facts': copy.deepcopy(FACTS)},
            'processed_article_ids': ['a', 'b'], 'updates': [], 'needs_narrative_refresh': False}


def payload(previous=None):
    return {'topic': {'topic_id': 'topic_perspectives_brief', 'working_title_pl': '[Polska] Budowa szkół'},
            'all_articles': copy.deepcopy(ARTICLES), 'new_article_ids': [],
            'previous_aggregation': previous or stored(), 'generate_brief_if_missing': True}


class TwoParagraphBriefTests(unittest.TestCase):
    def test_schema_requires_two_brief_paragraphs_and_shares_large_fact_id_enum(self):
        raw = article_response([{'text_pl': f['text_pl'], 'fact_ids': [f['fact_id']]} for f in FACTS],
                               brief_paragraphs=copy.deepcopy(BRIEF))
        schema = p.article_writing_schema(FACTS)
        check_response_schema(schema)
        jsonschema.validate(raw, schema)
        for paragraphs in (BRIEF[:1], BRIEF + BRIEF[:1]):
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate({**raw, 'brief_paragraphs': paragraphs}, schema)
        many = [{**FACTS[0], 'fact_id': f'fact_{i:024x}'} for i in range(500)]
        self.assertLess(check_response_schema(p.article_writing_schema(many))['enum_values'], 1000)

    def test_full_article_and_distinct_brief_use_one_request(self):
        old = stored()
        old['needs_narrative_refresh'] = True
        raw = article_response([{'text_pl': f['text_pl'], 'fact_ids': [f['fact_id']]} for f in FACTS],
                               brief_paragraphs=copy.deepcopy(BRIEF))
        with patch.object(ai, 'call_openai', return_value=raw) as request, patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload(old), 'gpt-6-luna')
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['response_schema_name'], 'perspective_summary')
        self.assertEqual(result['summary_pl'], FULL)
        self.assertEqual(result['brief_pl'], '\n\n'.join(row['text_pl'] for row in BRIEF))
        self.assertNotEqual(result['brief_pl'], '\n\n'.join(FULL.split('\n\n')[:2]))
        self.assertEqual(result['quality_report']['brief_validation']['status'], 'VALID')
        self.assertEqual(result['quality_report']['read_articles'], 0)

    def test_existing_article_buys_only_one_small_brief_request_and_saves_it_without_news_update(self):
        before = payload()
        original = copy.deepcopy(before)
        with patch.object(ai, 'call_openai', return_value={'brief_paragraphs': BRIEF}) as request, patch.object(ai, 'log'):
            result = ai.generate_summary_response(before, 'gpt-6-luna')
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['response_schema_name'], 'perspective_brief')
        self.assertEqual(request.call_args.kwargs['reasoning_effort'], 'low')
        self.assertEqual(request.call_args.kwargs['retry_limit'], 1)
        self.assertEqual(request.call_args.kwargs['max_output_tokens'], 3000)
        self.assertEqual(set(request.call_args.args[1]), {'headline_pl', 'primary_fact_id', 'main_facts'})
        self.assertNotIn('NEVER_RESEND_ARTICLE', json.dumps(request.call_args.args[1]))
        self.assertEqual(result['summary_pl'], FULL)
        self.assertEqual(result['perspective_state']['facts'], FACTS)
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(before, original)
        client = PersistingClient([], [], [])
        ai.persist_summary(client, topic_id='topic_perspectives_brief', run_id='test', model='gpt-6-luna',
                           summary=result, summary_hash='brief-test',
                           previous_row={'version': 1, 'summary': before['previous_aggregation']}, new_article_ids=[])
        saved = client.rows['topic_summaries'][0]['summary']
        self.assertEqual(saved['current_summary']['brief_pl'], result['brief_pl'])
        self.assertEqual(saved['base_summary'], original['previous_aggregation']['base_summary'])
        self.assertEqual(saved['updates'], [])
        with patch.object(ai, 'call_openai') as request, patch.object(ai, 'log'):
            ai.generate_summary_response(payload(saved), 'gpt-6-luna')
        request.assert_not_called()

    def test_malformed_brief_is_omitted_once_without_erasing_synthesis_or_retrying(self):
        bad = [None, [], BRIEF[:1], BRIEF + BRIEF[:1], [BRIEF[0], BRIEF[0]],
               [BRIEF[0], {**BRIEF[1], 'text_pl': 'Budowa szkół ma rozpocząć się w 2099 roku.'}],
               [BRIEF[0], {**BRIEF[1], 'fact_ids': ['foreign']}],
               [BRIEF[0], {**BRIEF[1], 'text_pl': BRIEF[1]['text_pl'] + '\nDrugi akapit.'}],
               [BRIEF[0], {**BRIEF[1], 'text_pl': 'Budowa szkół ruszy w 2027 roku; inwestycje.'}]]
        for paragraphs in bad:
            with self.subTest(paragraphs=paragraphs):
                with patch.object(ai, 'call_openai', return_value={'brief_paragraphs': paragraphs}) as request, patch.object(ai, 'log'):
                    result = ai.generate_summary_response(payload(), 'gpt-6-luna')
                request.assert_called_once()
                self.assertEqual(result['brief_pl'], '')
                self.assertEqual(result['summary_pl'], FULL)
                self.assertEqual(result['brief_generation_version'], integrity.BRIEF_GENERATION_VERSION)
                previous = stored()
                previous['current_summary'] = result
                with patch.object(ai, 'call_openai') as request, patch.object(ai, 'log'):
                    ai.generate_summary_response(payload(previous), 'gpt-6-luna')
                request.assert_not_called()

    def test_ai_only_backfills_brief_once_even_without_new_assignments(self):
        tid = 'topic_perspectives_brief'
        topics = [{'topic_id': tid, 'headline_pl': '[Polska] Budowa szkół',
                   'last_seen_at': '2026-10-21T08:00:00Z', 'status': 'ACTIVE'}]
        client = PersistingClient(topics, [{'topic_id': tid, 'article_id': a['article_id']} for a in ARTICLES],
                                  [{'topic_id': tid, 'version': 1, 'summary': stored(), 'updated_at': '2026-10-21T08:00:00Z'}])
        def build(base, new_rows, all_rows):
            self.assertTrue(base['generate_brief_if_missing'])
            self.assertEqual(new_rows, [])
            return {**base, 'all_articles': copy.deepcopy(ARTICLES), 'new_article_ids': []}, 0, 'test'
        with TemporaryDirectory() as folder:
            db = Path(folder) / 'articles.sqlite3'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE articles(article_id TEXT PRIMARY KEY, source_id TEXT, source_profile TEXT)')
                conn.executemany('INSERT INTO articles VALUES(?,?,?)', [(aid, aid, 'CENTER') for aid in ('a', 'b')])
            with patch.object(ai, 'build_bounded_summary_input', side_effect=build), \
                 patch.object(ai, 'call_openai', return_value={'brief_paragraphs': BRIEF}) as request, \
                 patch.object(ai, 'now', return_value='2026-10-21T08:00:00Z'), patch.object(ai, 'log'):
                self.assertEqual(ai.retry_incomplete_summaries(db, 'test', client)['summaries'], 1)
                self.assertEqual(ai.retry_incomplete_summaries(db, 'test-again', client)['summaries'], 0)
            request.assert_called_once()


if __name__ == '__main__':
    unittest.main()
