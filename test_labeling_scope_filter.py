import os
import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import ai_pipeline as ai


class ScopeClient:
    def __init__(self):
        self.writes = []
        self.updates = []
        self.assignments = []

    def upsert(self, table, rows, *, on_conflict):
        self.writes.append((table, rows))
        if table == 'article_topic_assignments':
            self.assignments.extend(rows)

    def update(self, table, values, *, filters):
        self.updates.append((table, values, filters))

    def select_all(self, table, **kwargs):
        return self.assignments if table == 'article_topic_assignments' else []


class LabelingScopeTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / 'articles.db'
        self.client = ScopeClient()
        self.articles = [dict(article_id=str(i), title=title, original_language='pl',
                              body='Treść artykułu ' * 100) for i, title in enumerate([
            'Wynik meczu', 'Prognoza temperatury', 'Życie prywatne gwiazdy',
            'Nowy serial', 'Przepis na ciasto', 'Ranking butów',
            'Powódź wymusza ewakuację mieszkańców', 'Niepewny zakres materiału',
        ])]
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE articles(article_id TEXT PRIMARY KEY, title TEXT, original_language TEXT, body TEXT, topic_hint TEXT, content_status TEXT, word_count INTEGER, fetched_at TEXT)')
            conn.executemany('INSERT INTO articles VALUES(?,?,?,?,?,?,?,?)', [
                (r['article_id'], r['title'], 'pl', r['body'], '', 'COMPLETE', 300,
                 datetime.now(timezone.utc).isoformat()) for r in self.articles])
        self.response = {'decisions': {
            **{str(i): dict(category=category, working_title_pl='', reason='Materiał spoza zakresu')
               for i, category in enumerate(['SPORT', 'WEATHER', 'CELEBRITY', 'ENTERTAINMENT', 'LIFESTYLE', 'OTHER_NON_CORE'])},
            '6': dict(category='KEEP', working_title_pl='[Polska] Powódź wymusza ewakuację mieszkańców kilku gmin', reason=''),
            '7': dict(category='KEEP', working_title_pl='[Polska] Spór o decyzję władz i skutki dla mieszkańców', reason=''),
        }}

    def run_batch(self, response):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(ai, 'call_openai', return_value=response) as model, patch.object(ai, 'log'):
            result = ai._label_pending_batch('run', self.client, self.articles, db_path=self.db)
        return result, model

    def test_exclusions_are_saved_without_candidates_and_are_not_pending_again(self):
        stats, model = self.run_batch(self.response)
        self.assertEqual(stats['excluded'], 6)
        self.assertEqual(stats['candidate_topics'], 2)
        self.assertEqual(stats['labeled_articles'], 2)
        model.assert_called_once()
        schema = model.call_args.kwargs['response_schema']['properties']['decisions']
        self.assertEqual(set(schema['required']), set('01234567'))
        self.assertFalse(schema['additionalProperties'])
        links = [r for table, rows in self.client.writes if table == 'topic_articles' for r in rows]
        self.assertEqual({r['article_id'] for r in links}, {'6', '7'})
        self.assertEqual(len(self.client.updates), 6)
        with sqlite3.connect(self.db) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(ai.pending_articles(conn, self.client, 0), [])
            hints = dict(conn.execute('SELECT article_id, topic_hint FROM articles'))
        self.assertTrue(all(hints[str(i)].startswith('AI_EXCLUDED:') for i in range(6)))
        self.assertEqual(hints['6'], '')

    def test_all_excluded_produces_no_topic_or_assignment_writes(self):
        response = {'decisions': {r['article_id']: dict(category='OTHER_NON_CORE', working_title_pl='', reason='Poza zakresem') for r in self.articles}}
        stats, _ = self.run_batch(response)
        self.assertEqual(stats['candidate_topics'], 0)
        self.assertEqual(stats['excluded'], 8)
        self.assertEqual({t for t, _ in self.client.writes}, {'topic_runs'})

    def test_foreign_or_missing_decision_fails_before_any_article_change_and_preserves_raw_response(self):
        decisions = self.response['decisions']
        for response in [
            {'decisions': {**decisions, 'foreign': dict(category='SPORT', working_title_pl='', reason='Poza zakresem')}},
            {'decisions': {key: value for key, value in decisions.items() if key != '7'}},
        ]:
            with self.subTest(response=response), self.assertRaises(ai.AIResponseParseError) as failure:
                self.run_batch(response)
            self.assertIn('decisions', failure.exception.raw_output)
        self.assertEqual(self.client.updates, [])
        self.assertEqual({t for t, _ in self.client.writes}, {'topic_runs'})
        self.assertTrue(all(rows[0]['status'] == 'FAILED' for _, rows in self.client.writes))
        self.assertTrue(all('raw_response' in rows[0]['raw_output'] for _, rows in self.client.writes))

    def test_main_flow_counts_exclusions_and_uses_local_database(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(ai, 'call_openai', return_value=self.response) as model, patch.object(ai, 'merge_active_topics', return_value={
            'merge_candidates': 0, 'topics_merged': 0, 'merge_failed': 0,
            'local_candidate_groups': 0, 'local_candidate_topics': 0,
            'largest_candidate_group': 0, 'merge_requests': 0,
        }), patch.object(ai, 'normalize_topic_titles', return_value=0), patch.object(ai, 'classify_topic_categories', return_value=0), patch.object(ai, 'retry_incomplete_summaries', return_value={'summaries': 0, 'failed_summaries': 0}), patch.object(ai, 'log'):
            stats = ai.analyze_run(self.db, 'run', self.client)
        self.assertEqual(stats['excluded'], 6)
        self.assertEqual(stats['candidate_topics'], 2)
        model.assert_called_once()
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM articles WHERE topic_hint LIKE 'AI_EXCLUDED:%'").fetchone()[0], 6)


if __name__ == '__main__':
    unittest.main()
