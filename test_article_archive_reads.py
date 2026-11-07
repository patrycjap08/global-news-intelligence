"""The startup snapshot must remain complete despite SQL timeouts/row caps."""
import copy
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import call, patch
from urllib.parse import parse_qs, urlsplit

import supabase_client as db
from supabase_sync import ARTICLE_COLUMNS, pull_state
from test_summary_input_completeness import source_row
from test_supabase_availability import http_error, response


class ArchiveAPI:
    """Serve actual HTTP query parameters, including server-side row limits."""
    def __init__(self, rows, cap=None, fail=None):
        self.rows = copy.deepcopy(rows)
        self.cap = cap
        self.fail = fail
        self.calls = []

    def __call__(self, request, **kwargs):
        self.assert_get(request)
        parsed = urlsplit(request.full_url)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        table = parsed.path.rsplit('/', 1)[-1]
        self.calls.append((table, query))
        if table != 'articles':
            return response([])
        if self.fail:
            error = self.fail(query)
            if error:
                raise error
        selected = sorted(self.rows, key=lambda row: row['article_id'])
        condition = query.get('article_id', '')
        if condition.startswith('gt.'):
            selected = [row for row in selected if row['article_id'] > condition[3:]]
        elif condition.startswith('in.('):
            allowed = set(condition[4:-1].split(','))
            selected = [row for row in selected if row['article_id'] in allowed]
        limit = int(query.get('limit', 1000))
        offset = int(query.get('offset', 0))
        if self.cap is not None:
            limit = min(limit, self.cap)
        return response(selected[offset:offset + limit])

    @staticmethod
    def assert_get(request):
        if request.method != 'GET':
            raise AssertionError('The archive repair must never write to Supabase')


class ArticleArchiveReadTests(unittest.TestCase):
    def client(self):
        return db.SupabaseRestClient('https://database.test', 'TEST_ONLY_SECRET')

    def read(self, api, page_size=4):
        with patch.dict(os.environ, {'SUPABASE_ARTICLE_READ_PAGE_SIZE': str(page_size)}), \
             patch.object(db.urllib.request, 'urlopen', side_effect=api), \
             patch.object(db, 'log'):
            return self.client().select_all('articles', columns=ARTICLE_COLUMNS,
                                           filters=[('order', 'article_id.asc')])

    def test_indexed_pages_preserve_all_rows_and_exact_full_bodies(self):
        rows = [source_row(f'a{i:04}') for i in range(13)]
        for row in rows:
            row['body'] = ('Pełna  treść.\n\nDrugi akapit.\t' + row['article_id']) * 100
        original = copy.deepcopy(rows)
        api = ArchiveAPI(rows)
        actual = self.read(api)
        self.assertEqual(actual, original)
        self.assertEqual(rows, original)
        self.assertEqual(len({row['article_id'] for row in actual}), len(rows))
        queries = [query for _, query in api.calls]
        self.assertEqual([q.get('article_id') for q in queries],
                         [None, 'gt.a0003', 'gt.a0007', 'gt.a0011', 'gt.a0012'])
        self.assertTrue(all('offset' not in q for q in queries))
        self.assertTrue(all(q['select'] == ARTICLE_COLUMNS for q in queries))

    def test_project_row_cap_cannot_truncate_a_short_page(self):
        rows = [source_row(f'a{i:04}') for i in range(7)]
        api = ArchiveAPI(rows, cap=2)
        self.assertEqual(self.read(api, page_size=250), rows)
        self.assertEqual(len(api.calls), 5)  # Four pages and an empty EOF page.
        self.assertEqual(api.calls[-1][1]['article_id'], 'gt.a0006')

    def test_sql_timeout_shrinks_same_cursor_without_restarting_or_skipping(self):
        def fail(query):
            if query.get('article_id') == 'gt.a0003' and int(query['limit']) > 2:
                return http_error(500, {'code': '57014', 'message': 'canceling statement due to statement timeout'})
        rows = [source_row(f'a{i:04}') for i in range(9)]
        api = ArchiveAPI(rows, fail=fail)
        with patch.object(db.time, 'sleep') as sleep:
            self.assertEqual(self.read(api), rows)
        sleep.assert_not_called()  # Resize instead of repeating the same heavy query.
        queries = [q for _, q in api.calls]
        self.assertEqual([(q.get('article_id'), q['limit']) for q in queries[:3]],
                         [(None, '4'), ('gt.a0003', '4'), ('gt.a0003', '2')])
        self.assertTrue(all(q['limit'] == '2' for q in queries[2:]))

    def test_persistent_sql_timeout_stops_at_one_row_and_never_returns_partial_data(self):
        api = ArchiveAPI([source_row(f'a{i:04}') for i in range(9)], fail=lambda q: http_error(500, {
            'code': '57014', 'message': 'canceling statement due to statement timeout'})
            if q.get('article_id') else None)
        with patch.object(db.time, 'sleep') as sleep, self.assertRaises(db.SupabaseError) as caught:
            self.read(api)
        self.assertEqual([q['limit'] for _, q in api.calls], ['4', '4', '2', '1'])
        self.assertTrue(all(q['article_id'] == 'gt.a0003' for _, q in api.calls[1:]))
        self.assertEqual(caught.exception.api_code, '57014')
        self.assertEqual(caught.exception.attempts, 1)
        sleep.assert_not_called()

    def test_unrelated_server_error_retains_bounded_retries_without_resizing(self):
        api = ArchiveAPI([], fail=lambda q: http_error(500, {'code': 'XX000', 'message': 'internal error'}))
        with patch.object(db.time, 'sleep') as sleep, self.assertRaises(db.SupabaseError) as caught:
            self.read(api)
        self.assertEqual([q['limit'] for _, q in api.calls], ['4', '4', '4'])
        self.assertEqual(caught.exception.api_code, 'XX000')
        self.assertEqual(caught.exception.attempts, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(2)])

    def test_auth_failure_is_not_mistaken_for_large_pages(self):
        api = ArchiveAPI([], fail=lambda q: http_error(401))
        with self.assertRaises(db.SupabaseError) as caught:
            self.read(api)
        self.assertEqual(caught.exception.http_status, 401)
        self.assertEqual(len(api.calls), 1)

    def test_repeated_missing_or_unordered_ids_stop_instead_of_losing_data(self):
        for bad_page in ([source_row('a0001')], [{'body': 'Missing ID'}],
                         [source_row('a0003'), source_row('a0002')],
                         [source_row('a0002'), source_row('a0002')], {'error': 'unexpected payload'}):
            with self.subTest(page=bad_page), \
                 patch.dict(os.environ, {'SUPABASE_ARTICLE_READ_PAGE_SIZE': '2'}), \
                 patch.object(db.urllib.request, 'urlopen', side_effect=[
                     response([source_row('a0000'), source_row('a0001')]), response(bad_page)]) as request, \
                 patch.object(db, 'log'), self.assertRaises(db.SupabaseError):
                self.client().select_all('articles', filters=[('order', 'article_id.asc')])
            self.assertEqual(request.call_count, 2)

    def test_scoped_article_reads_keep_their_original_query(self):
        api = ArchiveAPI([source_row('a'), source_row('b')])
        with patch.object(db.urllib.request, 'urlopen', side_effect=api):
            actual = self.client().select_all('articles', columns=ARTICLE_COLUMNS,
                filters=[('article_id', 'in.(b)'), ('order', 'article_id.asc')])
        self.assertEqual([row['article_id'] for row in actual], ['b'])
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0][1]['article_id'], 'in.(b)')

    def test_full_startup_snapshot_commits_every_full_record_after_short_pages(self):
        rows = [source_row(f'a{i:04}') for i in range(9)]
        api = ArchiveAPI(rows, cap=2)
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'snapshot.db'
            with patch.object(db.urllib.request, 'urlopen', side_effect=api), patch.object(db, 'log'):
                counts = pull_state(path, self.client())
            with sqlite3.connect(path) as conn:
                saved = conn.execute('select article_id,body,canonical_url,content_hash from articles order by article_id').fetchall()
        self.assertEqual(counts['articles'], len(rows))
        self.assertEqual(saved, [(r['article_id'], r['body'], r['canonical_url'], r['content_hash']) for r in rows])


if __name__ == '__main__':
    unittest.main()
