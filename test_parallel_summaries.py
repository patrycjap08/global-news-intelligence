import os
import sqlite3
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import ai_pipeline as ai
from test_topic_titles import FakeMergeClient


class ParallelSummaryTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / 'articles.sqlite3'
        self.topics = []
        links, articles = [], []
        for count in range(2, 9):
            key = 't' + str(count)
            self.topics.append({'topic_id': key, 'headline_pl': key, 'status': 'ACTIVE',
                                'last_seen_at': '2026-10-08T12:00:00Z'})
            for index in range(count):
                aid = key + '-' + str(index)
                links.append({'topic_id': key, 'article_id': aid})
                articles.append((aid, 'source-' + str(index % 2), 'CENTER'))
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE articles (article_id TEXT PRIMARY KEY, source_id TEXT, source_profile TEXT)')
            conn.executemany('INSERT INTO articles VALUES(?,?,?)', articles)
        self.client = FakeMergeClient(self.topics, links, [])
        self.client.rows['article_topic_assignments'] = []

    def execute(self, generate, persist, concurrency='5'):
        with patch.dict(os.environ, {'AI_SUMMARY_CONCURRENCY': concurrency}), \
             patch.object(ai, 'now', return_value='2026-10-08T12:00:00Z'), \
             patch.object(ai, 'build_bounded_summary_input', side_effect=lambda base, *args: (base, 0, 'test')), \
             patch.object(ai, 'generate_summary_response', side_effect=generate), \
             patch.object(ai, 'persist_summary', side_effect=persist), patch.object(ai, 'log'):
            return ai.retry_incomplete_summaries(self.db, 'run', self.client)

    def test_five_in_flight_and_next_job_starts_after_fast_result_is_saved(self):
        releases = {t['topic_id']: threading.Event() for t in self.topics}
        started = {key: threading.Event() for key in releases}
        saved_fast = threading.Event()
        active = peak = 0
        lock = threading.Lock()
        submitted, saved, worker_threads = [], [], []
        errors = []
        coordinator = threading.get_ident()

        def generate(payload, model):
            nonlocal active, peak
            key = payload['topic']['topic_id']
            with lock:
                active += 1
                peak = max(peak, active)
                worker_threads.append(threading.get_ident())
            started[key].set()
            try:
                if not releases[key].wait(5):
                    raise RuntimeError('Test worker did not receive release')
                return {'update': {'status': 'NEW_INFORMATION'}}
            finally:
                with lock:
                    active -= 1

        def persist(client, **kwargs):
            self.assertEqual(threading.get_ident(), coordinator)
            saved.append(kwargs['topic_id'])
            if kwargs['topic_id'] == 't4':
                saved_fast.set()

        def controller():
            try:
                for key in ['t8', 't7', 't6', 't5', 't4']:
                    if not started[key].wait(3):
                        raise AssertionError('Five jobs were not running simultaneously')
                if started['t3'].is_set():
                    raise AssertionError('More than five jobs were submitted')
                releases['t4'].set()
                if not saved_fast.wait(3) or not started['t3'].wait(3):
                    raise AssertionError('Free slot was not refilled after immediate persistence')
                if releases['t8'].is_set():
                    raise AssertionError('Refill waited for slow jobs')
            except Exception as exc:
                errors.append(exc)
            finally:
                for release in releases.values():
                    release.set()

        # Payload preparation, like SQLite and writes, must stay on coordinator.
        original_build = lambda base, *args: (submitted.append(base['topic']['topic_id']) or base, 0, 'test')
        controller_thread = threading.Thread(target=controller)
        controller_thread.start()
        with patch.dict(os.environ, {'AI_SUMMARY_CONCURRENCY': '5'}), \
             patch.object(ai, 'now', return_value='2026-10-08T12:00:00Z'), \
             patch.object(ai, 'build_bounded_summary_input', side_effect=original_build), \
             patch.object(ai, 'generate_summary_response', side_effect=generate), \
             patch.object(ai, 'persist_summary', side_effect=persist), patch.object(ai, 'log'):
            stats = ai.retry_incomplete_summaries(self.db, 'run', self.client)
        controller_thread.join(3)
        self.assertFalse(controller_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(peak, 5)
        self.assertNotIn(coordinator, worker_threads)
        self.assertEqual(submitted, ['t8', 't7', 't6', 't5', 't4', 't3', 't2'])
        self.assertEqual(saved[0], 't4')
        self.assertEqual(stats, {'summaries': 7, 'failed_summaries': 0})

    def test_failure_does_not_stop_other_jobs_and_retry_only_processes_unsaved_topic(self):
        attempts, saved = [], []
        def generate(payload, model):
            key = payload['topic']['topic_id']
            attempts.append(key)
            if key == 't8' and attempts.count('t8') == 1:
                raise RuntimeError('Simulated exhausted API retries')
            return {'update': {'status': 'NEW_INFORMATION'}}
        def persist(client, **kwargs):
            saved.append(kwargs['topic_id'])
            client.rows['topic_summaries'].append({'topic_id': kwargs['topic_id'],
                'summary': {'summary_pl': 'Saved'}, 'updated_at': '2026-10-08T12:00:00Z'})
        first = self.execute(generate, persist)
        self.assertEqual(first, {'summaries': 6, 'failed_summaries': 1})
        self.assertEqual(len(saved), 6)
        second = self.execute(generate, persist)
        self.assertEqual(second, {'summaries': 1, 'failed_summaries': 0})
        self.assertEqual(attempts.count('t8'), 2)
        self.assertEqual(len(attempts), 8)

    def test_duplicate_topic_is_generated_once_and_concurrency_one_is_supported(self):
        self.client.rows['topics'].append(dict(self.topics[-1]))
        generated, saved = [], []
        def generate(payload, model):
            generated.append(payload['topic']['topic_id'])
            return {'update': {'status': 'NEW_INFORMATION'}}
        stats = self.execute(generate, lambda client, **kw: saved.append(kw['topic_id']), concurrency='1')
        self.assertEqual(generated, ['t8', 't7', 't6', 't5', 't4', 't3', 't2'])
        self.assertEqual(saved, generated)
        self.assertEqual(stats['summaries'], 7)


if __name__ == '__main__':
    unittest.main()
