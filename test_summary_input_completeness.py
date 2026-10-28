"""Missing local source records must never buy failed extraction/brief calls."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import ai_pipeline as ai
from article_harvester import open_db
import perspective_summaries as p
from supabase_client import SupabaseRestClient
from supabase_sync import ARTICLE_COLUMNS, ArticleRestoreError, hydrate_articles, pull_state
from test_publication_flow import PersistingClient
from test_two_paragraph_brief import FACTS, BRIEF, stored as brief_stored


REAL = json.loads(Path(__file__).with_name('test_data').joinpath('summary_source_gap_20261028.json').read_text())


def source_row(aid, source=None):
    stamp = datetime.now(timezone.utc).isoformat()
    return dict.fromkeys(ARTICLE_COLUMNS.split(','), '') | dict(
        article_id=aid, source_id=source or aid, source_name=source or aid, source_profile='CENTER',
        original_url=f'https://example.test/{aid}', canonical_url=f'https://example.test/{aid}',
        title='Rada miasta buduje szkoły', body='NEVER_RESEND_PROCESSED_ARTICLE', word_count=300,
        original_language='pl', content_status='COMPLETE', item_kind='ARTICLE', fetch_method='HTTP',
        first_seen_at=stamp, fetched_at=stamp, last_seen_on_homepage_at=stamp)


class SourceClient(PersistingClient):
    def __init__(self, topics=(), links=(), summaries=(), articles=()):
        super().__init__(list(topics), list(links), list(summaries))
        self.rows['articles'] = copy.deepcopy(list(articles))
        self.source_requests = []

    def select_all(self, table, *, columns='*', filters=()):
        if table == 'articles':
            self.source_requests.append(list(filters))
            ids = dict(filters).get('article_id')
            rows = self.rows['articles']
            if ids:
                requested = ids.removeprefix('in.(').removesuffix(')').split(',')
                rows = [r for r in rows if r['article_id'] in requested]
            return copy.deepcopy(rows)
        return super().select_all(table, columns=columns, filters=filters)


class SummaryInputCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / 'articles.db'
        self.conn = open_db(self.db)
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row

    def test_missing_local_ids_are_restored_exactly_once_and_no_remote_writes_are_needed(self):
        client = SourceClient(articles=[source_row('a'), source_row('b')])
        hydrate_articles(self.conn, client, ['a'])
        client.source_requests.clear()
        rows = ai.complete_topic_articles(self.conn, client, ['a', 'b'])
        self.assertEqual({r['article_id'] for r in rows}, {'a', 'b'})
        self.assertEqual(client.source_requests, [[('article_id', 'in.(b)'), ('order', 'article_id.asc')]])
        self.assertEqual(ai.complete_topic_articles(self.conn, client, ['a', 'b']), rows)
        self.assertEqual(len(client.source_requests), 1)
        self.assertEqual(client.upserts, [])
        self.assertEqual(client.updates, [])

    def test_incomplete_remote_result_cannot_commit_partial_recovery(self):
        client = SourceClient(articles=[source_row('a')])
        with self.assertRaises(ArticleRestoreError) as caught:
            hydrate_articles(self.conn, client, ['a', 'missing'])
        self.assertEqual(caught.exception.response_details['missing_article_ids'], ['missing'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM articles').fetchone()[0], 0)

    def test_initial_pull_uses_stable_pagination_for_more_than_one_page(self):
        rows = [source_row(f'a{i:04}') for i in range(1001)]
        class PagedClient(SupabaseRestClient):
            def select(self, table, *, columns='*', filters=(), limit=1000, offset=0, order=None):
                if table != 'articles':
                    return []
                # Unordered LIMIT/OFFSET is allowed to return a different
                # ordering on the next page, repeating a row and losing one.
                current = rows if dict(filters).get('order') == 'article_id.asc' or offset == 0 else rows[::-1]
                return copy.deepcopy(current[offset:offset + limit])
        client = PagedClient('https://example.invalid', 'test-only')
        pull_state(self.db, client)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM articles').fetchone()[0], 1001)

    def test_real_previous_fact_gap_is_classified_before_any_model_call(self):
        articles = [{**a, 'body_original': 'Do not send processed sources.'} for a in REAL['articles']]
        # The logged partial count is real; which IDs are missing is a
        # deliberate reconstruction that guarantees a lone-source gap.
        absent = REAL['facts'][1]['article_ids'][0]
        partial = [a for a in articles if a['article_id'] != absent]
        previous = {'base_summary': {'perspective_version': 1},
                    'perspective_state': {'perspective_facts': copy.deepcopy(REAL['facts'])},
                    'processed_article_ids': [a['article_id'] for a in articles]}
        before = copy.deepcopy(previous)
        with patch.object(ai, 'call_openai') as request, patch.object(ai, 'log'):
            with self.assertRaises(p.MissingFactSourcesError) as caught:
                ai.generate_summary_response({'topic': {'topic_id': REAL['topic_id']},
                    'all_articles': partial, 'new_article_ids': [], 'previous_aggregation': previous}, 'gpt-6-luna')
            request.assert_not_called()
        self.assertIn(absent, caught.exception.response_details['missing_article_ids'])
        diagnostic = ai.parse_failure_for_storage(caught.exception)
        self.assertIn('input_data_error', diagnostic)
        self.assertNotIn('parse_error', diagnostic)
        self.assertEqual(previous, before)
        _, routed = p.route_facts({'facts': []}, articles, REAL['facts'], ai.normalize_generated_text)
        self.assertEqual({f['fact_id'] for f in routed}, {f['fact_id'] for f in REAL['facts']})

    def test_ai_only_restores_old_source_but_buys_only_the_missing_brief(self):
        tid = 'topic_perspectives_school'
        timestamp = datetime.now(timezone.utc).isoformat()
        topics = [{'topic_id': tid, 'headline_pl': '[Polska] Budowa szkół', 'status': 'ACTIVE', 'last_seen_at': timestamp}]
        links = [{'topic_id': tid, 'article_id': aid} for aid in ('a', 'b')]
        prior = brief_stored()
        client = SourceClient(topics, links, [{'topic_id': tid, 'version': 1, 'summary': prior, 'updated_at': timestamp}],
                              [source_row('a'), source_row('b')])
        hydrate_articles(self.conn, client, ['a'])
        client.source_requests.clear()
        with patch.object(ai, 'call_openai', return_value={'brief_paragraphs': BRIEF}) as request, patch.object(ai, 'log'):
            stats = ai.retry_incomplete_summaries(self.db, 'test', client)
            self.assertEqual(stats, {'summaries': 1, 'failed_summaries': 0})
            request.assert_called_once()
            self.assertEqual(request.call_args.kwargs['response_schema_name'], 'perspective_brief')
            self.assertNotIn('NEVER_RESEND_PROCESSED_ARTICLE', json.dumps(request.call_args.args[1]))
            self.assertEqual(ai.retry_incomplete_summaries(self.db, 'test-again', client)['summaries'], 0)
            request.assert_called_once()
        self.assertEqual(client.source_requests, [[('article_id', 'in.(b)'), ('order', 'article_id.asc')]])
        self.assertEqual(client.rows['topic_summaries'][0]['summary']['perspective_state']['facts'], FACTS)

    def test_truly_absent_source_fails_before_ai_without_erasing_the_published_synthesis(self):
        tid = 'topic_perspectives_missing_source'
        stamp = datetime.now(timezone.utc).isoformat()
        prior = brief_stored()
        client = SourceClient([{'topic_id': tid, 'headline_pl': '[Polska] Budowa szkół', 'last_seen_at': stamp}],
            [{'topic_id': tid, 'article_id': aid} for aid in ('a', 'b')],
            [{'topic_id': tid, 'version': 1, 'summary': prior, 'updated_at': stamp}], [source_row('a')])
        hydrate_articles(self.conn, client, ['a'])
        original = copy.deepcopy(client.rows['topic_summaries'])
        with patch.object(ai, 'call_openai') as request, patch.object(ai, 'log'):
            stats = ai.retry_incomplete_summaries(self.db, 'test', client)
        self.assertEqual(stats, {'summaries': 0, 'failed_summaries': 1})
        request.assert_not_called()
        self.assertEqual(client.rows['topic_summaries'], original)
        failure = client.rows['topic_runs'][0]
        self.assertEqual(failure['raw_output']['response_details']['missing_article_ids'], ['b'])


if __name__ == '__main__':
    unittest.main()
