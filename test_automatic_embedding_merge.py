import copy
import math
import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import ai_pipeline as ai
from test_topic_titles import FakeMergeClient


class AutomaticEmbeddingMergeTests(unittest.TestCase):
    def test_chain_merges_without_ai_and_preserves_synthesis_and_all_articles(self):
        topics = [{'topic_id': key, 'headline_pl': '[Polska] Protest lekarzy w Krakowie', 'status': 'ACTIVE',
                   'first_seen_at': '2026-10-07T00:00:00+00:00', 'last_seen_at': '2026-10-07T12:00:00+00:00'}
                  for key in 'abc']
        links = [{'topic_id': key, 'article_id': 'article_'+key} for key in 'abc']
        summaries = [{'topic_id': 'b', 'summary': {'base_summary': {'summary_pl': 'Oryginalna synteza'}, 'updates': [{'text': 'Stara aktualizacja'}]}}]
        original = copy.deepcopy(summaries)
        client = FakeMergeClient(topics, links, summaries)
        moved = {}
        with TemporaryDirectory() as folder:
            db = Path(folder)/'articles.sqlite3'
            conn = sqlite3.connect(db)
            conn.execute('CREATE TABLE articles(article_id TEXT, title TEXT, source_id TEXT)')
            conn.executemany('INSERT INTO articles VALUES(?,?,?)', [('article_'+key, 'Nagłówek '+key, 'source_'+key) for key in 'abc'])
            conn.commit(); conn.close()
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(ai, 'TOPIC_MERGE_EMBEDDINGS_ENABLED', True), patch.object(
                ai, 'build_topic_embedding_candidate_edges', return_value={('a','b'):.9, ('b','c'):.87},
            ), patch.object(ai, 'call_openai', side_effect=AssertionError('No AI merge verification')), patch.object(ai, 'log'):
                stats = ai.merge_active_topics(db, 'run', client, prefer_embeddings=True, merged_article_ids_by_topic=moved)
        self.assertEqual(stats['topics_merged'], 3)
        self.assertEqual(stats['merge_requests'], 0)
        self.assertEqual(set(moved['b']), {'article_a', 'article_c'})
        self.assertEqual(client.rows['topic_summaries'], original)
        saved_links = [row for table, rows, _ in client.upserts if table == 'topic_articles' for row in rows]
        self.assertEqual({row['article_id'] for row in saved_links}, {'article_a','article_b','article_c'})
        self.assertEqual({row['topic_id'] for row in saved_links}, {'b'})
        journal = [row for table, rows, _ in client.upserts if table == 'topic_runs' for row in rows]
        self.assertEqual(journal[0]['stage'], 'EMBEDDING_MERGE')
        self.assertAlmostEqual(journal[0]['raw_output']['minimum_edge_similarity'], .87)
        self.assertEqual({t['topic_id'] for t in client.rows['topics'] if t['status']=='MERGED'}, {'a','c'})

    def test_automatic_component_is_not_split_at_old_ai_batch_size(self):
        topics = [{'topic_id': str(i), 'headline_pl': str(i)} for i in range(100)]
        client = FakeMergeClient(topics, [], [])
        with TemporaryDirectory() as folder, patch.dict(os.environ, {'OPENAI_API_KEY': 'test'}), patch.object(
            ai, 'TOPIC_MERGE_EMBEDDINGS_ENABLED', True,
        ), patch.object(ai, 'build_topic_embedding_candidate_edges', return_value={(str(i),str(i+1)):.9 for i in range(99)}), patch.object(
            ai, 'call_openai', side_effect=AssertionError('No merge verification'),
        ), patch.object(ai, 'log'):
            stats = ai.merge_active_topics(Path(folder)/'db', 'run', client, prefer_embeddings=True)
        self.assertEqual(stats['largest_candidate_group'], 100)
        self.assertEqual(stats['local_candidate_groups'], 1)
        self.assertEqual(stats['merge_requests'], 0)

    def test_diagnostic_bands_cover_all_thirteen_ranges_without_changing_selection(self):
        for n in range(30,43):
            score = n/50 + .005
            report = {}
            vectors = [[1.,0.], [score,math.sqrt(1-score**2)]]
            with self.subTest(score=score):
                result = ai.build_embedding_candidate_edges(['a','b'],vectors,diagnostics=report)
                self.assertEqual(result,{})
                sample = report['score_band_samples'][0]
                self.assertAlmostEqual(sample['band_lower'],n/50)
                self.assertAlmostEqual(sample['similarity'],score)
                self.assertEqual(report['score_band_pair_counts'][str(n/50)],1)
                self.assertEqual(report['score_band_floor'],.6)
        report = {}
        score=.605
        ai.build_embedding_candidate_edges([str(i) for i in range(15)],
            [[1.,0.]]*7+[[score,math.sqrt(1-score**2)]]*8,diagnostics=report)
        self.assertEqual(len(report['score_band_samples']),5)
        self.assertEqual(report['score_band_pair_counts']['0.6'],56)
        self.assertEqual(len({(r['topic_id_a'],r['topic_id_b']) for r in report['score_band_samples']}),5)

    def test_valid_title_of_newly_merged_topic_is_still_sent_for_ai_editing(self):
        client = FakeMergeClient([{'topic_id':'b','headline_pl':'[Polska] Protest lekarzy w Krakowie'}],[],[])
        with patch.object(ai,'call_openai',return_value={'titles':[{'topic_id':'b','title_pl':'[Polska] Rozwój protestu lekarzy w Krakowie'}]}) as model, patch.object(ai,'log'):
            ai.normalize_topic_titles(client,forced_topic_ids={'b'})
        model.assert_called_once()
        self.assertEqual(model.call_args.args[1]['topics'][0]['topic_id'],'b')


if __name__ == '__main__':
    unittest.main()
