import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ai_pipeline as ai
from test_topic_titles import FakeMergeClient


class EmbeddingDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_preserve_selection_and_distinguish_threshold_and_neighbor_limit(self):
        ids = ['a', 'b', 'c', 'd']
        vectors = [[1., 0.]] * 4
        baseline = ai.build_embedding_candidate_edges(ids, vectors, top_k=1, min_similarity=.88)
        report = {}
        result = ai.build_embedding_candidate_edges(ids, vectors, top_k=1, min_similarity=.88, diagnostics=report)
        self.assertEqual(result, baseline)
        samples = {(row['topic_id_a'], row['topic_id_b']): row for row in report['samples']}
        self.assertEqual(report['compared_pairs'], 6)
        self.assertEqual(report['selected_pair_count'], 3)
        self.assertEqual(samples[('a', 'b')]['bucket'], 'ABOVE_THRESHOLD_OUTSIDE_TOP_K')
        self.assertGreater(samples[('a', 'b')]['rank_a_to_b'], 1)
        self.assertGreater(samples[('a', 'b')]['rank_b_to_a'], 1)
        self.assertTrue(samples[('a', 'd')]['selected_for_ai'])
        below = {}
        self.assertEqual(ai.build_embedding_candidate_edges(
            ['a', 'b'], [[1., 0.], [.86, math.sqrt(1-.86**2)]],
            min_similarity=.88, diagnostics=below,
        ), {})
        self.assertEqual(below['samples'][0]['bucket'], 'BELOW_THRESHOLD')
        self.assertAlmostEqual(below['samples'][0]['similarity'], .86)
        self.assertEqual(below['bucket_pair_counts']['BELOW_THRESHOLD'], 1)

    def test_samples_are_bounded_unique_and_reproducible(self):
        ids = [str(i) for i in range(100)]
        first, second = {}, {}
        for report in [first, second]:
            ai.build_embedding_candidate_edges(ids, [[1., 0.]] * 100, top_k=1, diagnostics=report)
        self.assertEqual(first, second)
        self.assertEqual(len(first['samples']), 40)
        self.assertEqual(sum(first['bucket_pair_counts'].values()), 4950)
        self.assertEqual(len({(r['topic_id_a'], r['topic_id_b']) for r in first['samples']}), 40)

    def test_snapshot_is_exact_api_input_and_does_not_add_api_calls(self):
        topics = [{'topic_id': 'a', 'headline_pl': 'Tytuł A', 'recent_article_titles': ['Nagłówek A']},
                  {'topic_id': 'b', 'headline_pl': 'Tytuł B', 'summary_pl': 'Synteza B'}]
        response = SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1., 0.]) for i in range(2)])
        report = {}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(
            ai, 'TOPIC_MERGE_EMBEDDINGS_ENABLED', True,
        ), patch('openai.OpenAI') as sdk, patch.object(ai, 'log'):
            sdk.return_value.embeddings.create.return_value = response
            ai.build_topic_embedding_candidate_edges(topics, diagnostics=report)
        sdk.return_value.embeddings.create.assert_called_once()
        self.assertEqual(report['samples'][0]['embedding_text_a'], sdk.return_value.embeddings.create.call_args.kwargs['input'][0])
        self.assertEqual(report['samples'][0]['embedding_text_b'], sdk.return_value.embeddings.create.call_args.kwargs['input'][1])
        self.assertEqual(report['samples'][0]['title_a'], 'Tytuł A')

    def test_main_merge_saves_zero_match_report(self):
        client = FakeMergeClient([{'topic_id': key, 'headline_pl': key} for key in 'ab'], [], [])
        def embed(topics, *, diagnostics):
            diagnostics.update({'samples': [], 'threshold': .88, 'selected_pair_count': 0})
            return {}
        with TemporaryDirectory() as folder, patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(
            ai, 'TOPIC_MERGE_EMBEDDINGS_ENABLED', True,
        ), patch.object(ai, 'build_topic_embedding_candidate_edges', side_effect=embed), patch.object(ai, 'log'), patch.object(ai, 'call_openai') as model:
            ai.merge_active_topics(Path(folder)/'db.sqlite3', 'harvest', client, prefer_embeddings=True)
        reports = [row for table, rows, _ in client.upserts if table == 'topic_runs' for row in rows
                   if row['stage'] == 'EMBEDDING_DIAGNOSTICS']
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]['raw_output']['selected_pair_count'], 0)
        model.assert_not_called()

    def test_failed_report_write_preserves_embedding_selection_and_merge(self):
        client = FakeMergeClient([{'topic_id': key, 'headline_pl': key} for key in 'ab'], [], [])
        original_upsert = client.upsert
        def upsert(table, rows, **kwargs):
            if table == 'topic_runs' and rows[0]['stage'] == 'EMBEDDING_DIAGNOSTICS':
                raise RuntimeError('Diagnostic write unavailable')
            return original_upsert(table, rows, **kwargs)
        client.upsert = upsert
        def embed(topics, *, diagnostics):
            diagnostics.update({'samples': [], 'threshold': .88})
            return {('a', 'b'): .95}
        with TemporaryDirectory() as folder, patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(
            ai, 'TOPIC_MERGE_EMBEDDINGS_ENABLED', True,
        ), patch.object(ai, 'build_topic_embedding_candidate_edges', side_effect=embed), patch.object(ai, 'log') as logger, patch.object(
            ai, '_topic_merge_candidate_edges', side_effect=AssertionError('Lexical fallback must not run'),
        ), patch.object(ai, 'call_openai', return_value={'merge_groups': []}) as model:
            stats = ai.merge_active_topics(Path(folder)/'db.sqlite3', 'harvest', client, prefer_embeddings=True)
        model.assert_called_once()
        self.assertEqual(stats['semantic_candidate_edges'], 1)
        self.assertEqual(stats['merge_failed'], 0)
        self.assertTrue(any('Nie zapisano próbek embeddingów' in str(call) for call in logger.call_args_list))


if __name__ == '__main__':
    unittest.main()
