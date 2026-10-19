import math
import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import ai_pipeline as ai
from test_topic_titles import FakeMergeClient


class FocusedEmbeddingTests(unittest.TestCase):
    def test_only_new_to_new_and_new_to_existing_pairs_are_computed(self):
        ids = ['old_a', 'new_a', 'old_b', 'new_b', 'old_c']
        vectors = [[math.cos(i / 50), math.sin(i / 50)] for i in range(5)]
        diagnostics = {}
        with patch.object(ai, '_cosine_similarity', wraps=ai._cosine_similarity) as cosine:
            edges = ai.build_embedding_candidate_edges(ids, vectors, focus_topic_ids={'new_a', 'new_b'}, diagnostics=diagnostics)
        expected = {tuple(sorted((a, b))) for i, a in enumerate(ids) for b in ids[i + 1:]
                    if a.startswith('new') or b.startswith('new')}
        self.assertEqual(set(edges), expected)
        self.assertEqual(len(expected), 7)
        self.assertEqual(cosine.call_count, 14)  # Both neighbor directions, no existing/existing cosine.
        self.assertEqual(diagnostics['compared_pairs'], 7)
        self.assertEqual(diagnostics['comparison_scope'], 'NEW_TOPICS')
        self.assertTrue(all(row['topic_id_a'].startswith('new') or row['topic_id_b'].startswith('new')
                            for row in diagnostics['samples'] + diagnostics['score_band_samples']))
        all_pairs = ai.build_embedding_candidate_edges(ids, vectors)
        self.assertEqual(len(all_pairs), 10)

    def test_empty_focus_skips_embedding_api_and_ukraine_threshold_is_unchanged(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch('openai.OpenAI') as sdk:
            self.assertEqual(ai.build_topic_embedding_candidate_edges(
                [{'topic_id': 'old_a'}, {'topic_id': 'old_b'}], focus_topic_ids=set()), {})
            sdk.assert_not_called()
        edges = ai.build_embedding_candidate_edges(['new', 'old', 'other'], [[1, 0], [.8, .6], [.8, .6]],
                                                   focus_topic_ids={'new'}, ukraine_ids={'new', 'old'})
        self.assertEqual(set(edges), {('new', 'old')})

    def test_only_related_group_merges_and_focus_follows_retained_old_identity(self):
        topics = [{'topic_id': key, 'headline_pl': '[Polska] Decyzja władz', 'status': 'ACTIVE'} for key in 'abcd']
        links = [{'topic_id': key, 'article_id': key} for key in 'abcd']
        client = FakeMergeClient(topics, links, [{'topic_id': 'b', 'summary': {'summary_pl': 'Zachowana synteza'}}])
        focus = {'a'}
        with TemporaryDirectory() as folder:
            db = Path(folder) / 'db'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE articles(article_id TEXT,title TEXT,source_id TEXT)')
                conn.executemany('INSERT INTO articles VALUES(?,?,?)', [(k, 'Nagłówek ' + k, k) for k in 'abcd'])
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(
                ai, 'build_topic_embedding_candidate_edges', return_value={('a', 'b'): .9, ('c', 'd'): .99},
            ), patch.object(ai, 'log'):
                stats = ai.merge_active_topics(db, 'run', client, prefer_embeddings=True, focus_topic_ids=focus)
        self.assertEqual(stats['topics_merged'], 2)
        self.assertEqual(focus, {'b'})
        self.assertEqual({t['topic_id'] for t in topics if t['status'] == 'MERGED'}, {'a'})
        self.assertEqual(client.rows['topic_summaries'][0]['summary']['summary_pl'], 'Zachowana synteza')

    def test_pipeline_passes_new_ids_then_retained_ids_to_final_check_only_when_requested(self):
        zero = {k: 0 for k in ('merge_candidates', 'topics_merged', 'merge_failed', 'local_candidate_groups',
                               'local_candidate_topics', 'largest_candidate_group', 'merge_requests')}
        for scoped in (False, True):
            seen = []
            def label(*args, **kwargs):
                if scoped:
                    kwargs['created_topic_ids'].add('new')
                else:
                    self.assertNotIn('created_topic_ids', kwargs)
                return {'labeled_articles': 1, 'candidate_topics': 1, 'label_needs_review': 0, 'excluded': 0}
            def merge(*args, **kwargs):
                if scoped:
                    self.assertEqual(kwargs['focus_topic_ids'], {'new'})
                    kwargs['focus_topic_ids'].clear()
                    kwargs['focus_topic_ids'].add('retained')
                else:
                    self.assertNotIn('focus_topic_ids', kwargs)
                return dict(zero)
            def final(*args, **kwargs):
                seen.append(kwargs.get('focus_topic_ids'))
                return {'summaries': 0, 'failed_summaries': 0}
            with self.subTest(scoped=scoped), TemporaryDirectory() as folder, patch.dict(
                os.environ, {'OPENAI_API_KEY': 'test'},
            ), patch.object(ai, 'pending_articles', return_value=[{'article_id': 'a'}]), patch.object(
                ai, '_label_pending_batch', side_effect=label,
            ), patch.object(ai, 'merge_active_topics', side_effect=merge), patch.object(
                ai, 'merge_existing_summaries', side_effect=final,
            ), patch.object(ai, 'normalize_topic_titles', return_value=0), patch.object(
                ai, 'classify_topic_categories', return_value=0,
            ), patch.object(ai, 'retry_incomplete_summaries', return_value={'summaries': 0, 'failed_summaries': 0}), patch.object(ai, 'log'):
                ai.analyze_run(Path(folder) / 'db', 'run', object(), new_topics_only=scoped)
            self.assertEqual(seen, [{'retained'}] if scoped else [None])


if __name__ == '__main__':
    unittest.main()
