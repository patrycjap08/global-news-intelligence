import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import ai_pipeline as ai
from test_topic_titles import FakeMergeClient


class SummaryQueueTests(unittest.TestCase):
    def run_queue(self, topics, articles, links, summaries=(), assignments=(), forced=None, clock=None):
        client = FakeMergeClient(topics, links, list(summaries))
        client.rows['article_topic_assignments'] = list(assignments)
        with TemporaryDirectory() as folder:
            db = Path(folder) / 'articles.sqlite3'
            conn = sqlite3.connect(db)
            conn.execute('CREATE TABLE articles (article_id TEXT PRIMARY KEY, source_id TEXT, source_profile TEXT)')
            conn.executemany('INSERT INTO articles VALUES(?,?,?)', articles)
            conn.commit()
            conn.close()
            with patch.object(ai, 'build_bounded_summary_input', return_value=({}, 0, 'test')), patch.object(
                ai, 'generate_summary_response', return_value={'update': {'status': 'NEW_INFORMATION'}},
            ) as generate, patch.object(ai, 'persist_summary') as persist, patch.object(ai, 'log') as logger, patch.object(ai, 'now', **({'side_effect': clock} if clock else {'return_value': '2026-10-07T12:00:00Z'})):
                stats = ai.retry_incomplete_summaries(db, 'saved_run', client, forced_new_article_ids_by_topic=forced)
        return stats, generate, persist, logger

    def test_five_multisource_topics_are_generated_and_three_single_source_topics_are_explained(self):
        topics = [{'topic_id': str(i), 'headline_pl': f'Temat {i}', 'last_seen_at': '2026-10-07T12:00:00Z'} for i in range(8)]
        links = [{'topic_id': str(i), 'article_id': f'{i}-{j}'} for i in range(8) for j in range(2)]
        articles = [(f'{i}-{j}', f'source-{j}' if i < 5 else 'same-source', 'CENTER') for i in range(8) for j in range(2)]
        forced = {str(i): [f'{i}-1'] for i in range(8)}
        stats, generate, persist, logger = self.run_queue(topics, articles, links, forced=forced)
        self.assertEqual(stats, {'summaries': 5, 'failed_summaries': 0})
        self.assertEqual(generate.call_count, 5)
        self.assertEqual({call.kwargs['topic_id'] for call in persist.call_args_list}, set('01234'))
        for i in range(5, 8):
            self.assertTrue(any(f'Temat {i}: artykuły pochodzą tylko z jednego źródła' in str(call) for call in logger.call_args_list))

    def test_explicit_merge_articles_are_analyzed_despite_old_assignment_timestamp(self):
        topics = [{'topic_id': 'retained', 'headline_pl': 'Zachowany wątek', 'last_seen_at': '2026-10-07T12:00:00Z'}]
        articles = [('a', 'first', 'CENTER'), ('b', 'second', 'CENTER')]
        links = [{'topic_id': 'retained', 'article_id': aid} for aid in 'ab']
        summaries = [{'topic_id': 'retained', 'summary': {'summary_pl': 'Starsza synteza'}, 'updated_at': '2026-10-05T14:00:00+00:00'}]
        assignments = [{'topic_id': 'retained', 'article_id': aid, 'created_at': '2026-10-05T13:00:00+00:00'} for aid in 'ab']
        stats, _, persist, _ = self.run_queue(topics, articles, links, summaries, assignments, forced={'retained': ['b']})
        self.assertEqual(stats['summaries'], 1)
        self.assertEqual(persist.call_args.kwargs['new_article_ids'], ['b'])

    def test_age_limit_blocks_old_first_synthesis_and_old_update_even_if_forced(self):
        topics = [{'topic_id': key, 'headline_pl': 'Wątek ' + key, 'last_seen_at': date}
                  for key, date in [('old-first', '2026-10-05T11:59:59Z'),
                                    ('old-update', '2026-10-05T11:59:59Z'),
                                    ('boundary', '2026-10-05T12:00:00Z'),
                                    ('recent', '2026-10-05T12:00:01Z'),
                                    ('missing', None), ('invalid', 'bad-date')]]
        links = [{'topic_id': t['topic_id'], 'article_id': t['topic_id'] + str(j)} for t in topics for j in range(2)]
        articles = [(link['article_id'], 'source-' + link['article_id'][-1], 'CENTER') for link in links]
        summaries = [{'topic_id': 'old-update', 'summary': {'summary_pl': 'Istniejąca synteza'}, 'updated_at': '2026-10-01T12:00:00Z'}]
        forced = {t['topic_id']: [t['topic_id'] + '1'] for t in topics}
        stats, generate, persist, logger = self.run_queue(topics, articles, links, summaries=summaries, forced=forced)
        self.assertEqual(stats['summaries'], 2)
        self.assertEqual(generate.call_count, 2)
        self.assertEqual({call.kwargs['topic_id'] for call in persist.call_args_list}, {'boundary', 'recent'})
        self.assertTrue(any('Wątek old-first: poza oknem 48 godzin' in str(call) for call in logger.call_args_list))

    def test_topic_expiring_while_waiting_is_not_sent_to_ai(self):
        topics = [{'topic_id': 'topic', 'headline_pl': 'Wątek', 'last_seen_at': '2026-10-05T12:01:00Z'}]
        articles = [('a', 'one', 'CENTER'), ('b', 'two', 'CENTER')]
        links = [{'topic_id': 'topic', 'article_id': key} for key in 'ab']
        stats, generate, persist, logger = self.run_queue(topics, articles, links,
            clock=['2026-10-07T12:00:00Z', '2026-10-07T12:02:00Z'])
        self.assertEqual(stats['summaries'], 0)
        generate.assert_not_called()
        persist.assert_not_called()
        self.assertTrue(any('po oczekiwaniu w kolejce' in str(call) for call in logger.call_args_list))

    def test_normal_pipeline_passes_moved_articles_to_final_summary_stage(self):
        merge_stats = {key: 0 for key in ('merge_candidates', 'topics_merged', 'merge_failed', 'local_candidate_groups', 'local_candidate_topics', 'largest_candidate_group', 'merge_requests')}
        def merge(*args, **kwargs):
            kwargs['merged_article_ids_by_topic']['retained'] = ['moved']
            return merge_stats
        with TemporaryDirectory() as folder, patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(
            ai, 'pending_articles', return_value=[],
        ), patch.object(ai, 'merge_active_topics', side_effect=merge), patch.object(ai, 'normalize_topic_titles', return_value=0), patch.object(
            ai, 'classify_topic_categories', return_value=0,
        ), patch.object(ai, 'retry_incomplete_summaries', return_value={'summaries': 1, 'failed_summaries': 0}) as retry, patch.object(ai, 'log'):
            result = ai.analyze_run(Path(folder) / 'articles.sqlite3', 'run', object())
        self.assertEqual(retry.call_args.kwargs['forced_new_article_ids_by_topic'], {'retained': ['moved']})
        self.assertEqual(result['summaries'], 1)


if __name__ == '__main__':
    unittest.main()
