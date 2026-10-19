import copy
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import ai_pipeline as ai
import compare_topic_embeddings as compare


class ReadClient:
    def __init__(self, count=8):
        self.calls = []
        self.rows = {
            'topics': [{'topic_id': tid, 'headline_pl': f'[Francja] Temat {i}', 'status': 'ACTIVE',
                        'updated_at': '2026-10-19T18:00:00Z'} for i, tid in enumerate(compare.DEFAULT_TOPIC_IDS[:count])],
            'topic_summaries': [{'topic_id': tid, 'base_topic': {'what_happened_one_sentence_pl': f'Krótki opis {i}.'},
                                 'base_text': 'Synteza. ' * 500, 'version': 2, 'base_format': 1}
                                for i, tid in enumerate(compare.DEFAULT_TOPIC_IDS[:count])],
            'topic_articles': [{'topic_id': tid, 'article_id': f'a{i}'}
                               for i, tid in enumerate(compare.DEFAULT_TOPIC_IDS[:count])],
            'articles': [{'article_id': f'a{i}', 'title': f'Nagłówek {i}',
                          'published_at': '2026-10-19T17:00:00Z', 'fetched_at': '2026-10-19T18:00:00Z'}
                         for i in range(count)],
        }

    def select(self, table, **kwargs):
        self.calls.append((table, kwargs))
        return copy.deepcopy(self.rows[table])


class EmbeddingComparisonTests(unittest.TestCase):
    def topics(self):
        return compare.load_topics(ReadClient(), list(compare.DEFAULT_TOPIC_IDS))

    def report(self):
        topics = self.topics()
        records, texts = compare.prepare_inputs(topics)
        vectors = [[1., 0.] for _ in texts]
        vectors[records[-1]['embedding_index']] = [0., 1.]
        return compare.build_report(topics, records, vectors, {'total_tokens': 42}, 'snapshot-start')

    def test_fetch_only_selected_metadata_and_preserve_production_headline_ordering(self):
        client = ReadClient(2)
        tid = compare.DEFAULT_TOPIC_IDS[0]
        client.rows['topic_articles'] += [{'topic_id': tid, 'article_id': f'b{i}'} for i in range(6)]
        client.rows['articles'] += [{'article_id': f'b{i}', 'title': f'Nowy {i}', 'published_at': None,
                                    'fetched_at': f'2026-10-19T19:0{i}:00Z'} for i in range(6)]
        rows = compare.load_topics(client, list(compare.DEFAULT_TOPIC_IDS[:2]))
        self.assertEqual(rows[0]['recent_article_titles'], [f'Nowy {i}' for i in (5, 4, 3, 2, 1)])
        for table, settings in client.calls:
            self.assertNotEqual(settings['columns'], '*')
            self.assertNotIn('body', settings['columns'])
            self.assertNotIn('original_text', settings['columns'])
            self.assertEqual(len(settings['filters']), 1)
        self.assertIn('summary->base_summary->topic', compare.SUMMARY_COLUMNS)
        self.assertNotIn('summary->perspective_state', compare.SUMMARY_COLUMNS)
        self.assertEqual(rows[0]['summary_pl'], ('Synteza. ' * 500).strip()[:ai.TOPIC_MERGE_SUMMARY_CHAR_LIMIT])

    def test_missing_topic_description_or_article_metadata_fail_without_fallback(self):
        for missing in ('topic', 'description', 'article'):
            client = ReadClient(2)
            if missing == 'topic':
                client.rows['topics'].pop()
            elif missing == 'description':
                client.rows['topic_summaries'][0]['base_topic'] = {}
            else:
                client.rows['articles'].pop()
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                compare.load_topics(client, list(compare.DEFAULT_TOPIC_IDS[:2]))
        legacy = ReadClient(2)
        row = legacy.rows['topic_summaries'][0]
        row['legacy_topic'] = row.pop('base_topic')
        row['legacy_text'] = row.pop('base_text')
        self.assertEqual(compare.load_topics(legacy, list(compare.DEFAULT_TOPIC_IDS[:2]))[0]['what_happened_one_sentence_pl'], 'Krótki opis 0.')

    def test_variant_a_is_exact_production_text_b_contains_only_title_and_description(self):
        topics = self.topics()
        records, texts = compare.prepare_inputs(topics)
        self.assertEqual(len(records), 16)
        self.assertEqual(len(texts), 16)
        for row in records:
            topic = next(t for t in topics if t['topic_id'] == row['topic_id'])
            self.assertEqual(texts[row['embedding_index']], row['text'])
            if row['variant'] == 'current':
                self.assertEqual(row['text'], ai._topic_embedding_text(topic))
                self.assertIn('Synteza wątku:', row['text'])
                self.assertLessEqual(len(row['text']), 1800)
            else:
                self.assertEqual(row['text'], f"Tytuł wątku: {topic['headline_pl']}\nOpis: {topic['what_happened_one_sentence_pl']}")
                self.assertNotIn('Synteza.', row['text'])
                self.assertNotIn('Nagłówek', row['text'])
        same = [dict(topics[0], summary_pl='', recent_article_titles=[])]
        records, texts = compare.prepare_inputs(same)
        self.assertEqual(len(texts), 1)
        self.assertEqual([r['embedding_index'] for r in records], [0, 0])

    def test_one_embedding_request_with_identical_model_and_dimensions_and_exact_indexes(self):
        sdk = Mock()
        vectors = [[float(i + 1)] * ai.TOPIC_MERGE_EMBEDDING_DIMENSIONS for i in range(16)]
        sdk.embeddings.create.return_value = SimpleNamespace(data=[SimpleNamespace(index=i, embedding=vectors[i])
            for i in reversed(range(16))], usage=SimpleNamespace(prompt_tokens=123, total_tokens=123))
        texts = [f'Tekst {i}' for i in range(16)]
        result, usage = compare.request_vectors(sdk, texts)
        sdk.embeddings.create.assert_called_once_with(input=texts, model=ai.TOPIC_MERGE_EMBEDDING_MODEL,
                                                       dimensions=ai.TOPIC_MERGE_EMBEDDING_DIMENSIONS)
        self.assertEqual(result, vectors)
        self.assertEqual(usage['total_tokens'], 123)
        sdk.embeddings.create.return_value.data[-1].index = 1
        with self.assertRaisesRegex(ValueError, 'dokładnie'):
            compare.request_vectors(sdk, texts)
        sdk.embeddings.create.return_value = SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.] * ai.TOPIC_MERGE_EMBEDDING_DIMENSIONS)])
        with self.assertRaisesRegex(ValueError, 'niepoprawne'):
            compare.request_vectors(sdk, ['one'])

    def test_all_28_pairs_are_saved_even_below_sampling_floor_and_groups_cover_all_topics(self):
        report = self.report()
        self.assertEqual(len(report['pairs']), 28)
        self.assertEqual(report['threshold'], .78)
        self.assertTrue(all(pair['threshold'] == .78 for pair in report['pairs']))
        self.assertEqual(len({(p['topic_id_a'], p['topic_id_b']) for p in report['pairs']}), 28)
        low = [p for p in report['pairs'] if p['title_description'] == 0]
        self.assertEqual(len(low), 7)
        self.assertTrue(all(p['current'] == 1 and p['difference'] == -1 for p in low))
        simulation = report['simulations']['0.78']
        self.assertEqual(simulation['current']['group_count'], 1)
        self.assertEqual(simulation['title_description']['group_count'], 2)
        for variants in report['simulations'].values():
            for result in variants.values():
                ids = [tid for group in result['groups'] for tid in group]
                self.assertEqual(len(ids), 8)
                self.assertEqual(set(ids), set(compare.DEFAULT_TOPIC_IDS))

    def test_generation_boundaries_remain_even_for_identical_vectors(self):
        topics = self.topics()
        topics[-1]['generation'] = 'legacy'
        records, texts = compare.prepare_inputs(topics)
        report = compare.build_report(topics, records, [[1., 0.]] * len(texts), {}, 'start')
        self.assertEqual(sum(not p['same_generation'] for p in report['pairs']), 7)
        self.assertEqual(report['simulations']['0.82']['current']['group_count'], 2)

    def test_report_outputs_reproduce_inputs_scores_and_escape_html_without_external_assets(self):
        report = self.report()
        attack = '</script><script>alert(1)</script>'
        report['topics'][0]['headline_pl'] = attack
        with TemporaryDirectory() as folder:
            path = Path(folder)
            compare.write_report(report, path)
            saved = json.loads((path / 'report.json').read_text())
            self.assertEqual(saved, report)
            with (path / 'pairs.csv').open(encoding='utf-8-sig') as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 28)
            html = (path / 'report.html').read_text()
            self.assertNotIn(attack, html)
            self.assertNotIn('__REPORT_JSON__', html)
            self.assertNotIn('https://', html)
            self.assertIn('type="range"', html)

    def test_topic_selection_defaults_validation_and_shell_safe_workflow(self):
        self.assertEqual(compare.parse_topic_ids(''), list(compare.DEFAULT_TOPIC_IDS))
        self.assertEqual(compare.parse_topic_ids('a,b a\nb'), ['a', 'b'])
        for value in ('a', 'a,', 'a b)or(secret)', 'a $(whoami)', ' '.join(f't{i}' for i in range(21))):
            with self.subTest(value=value), self.assertRaises(ValueError):
                compare.parse_topic_ids(value)
        workflow = (Path(__file__).parent / '.github/workflows/embedding-comparison.yml').read_text()
        self.assertIn('branches: [diagnostics/embedding-france-20261019]', workflow)
        self.assertNotIn('branches: [main]', workflow)
        self.assertIn('--topic-ids "$TOPIC_IDS"', workflow)
        for mutation in ('news_pipeline.py', 'supabase_sync.py', 'export_public_site.py'):
            self.assertNotIn(mutation, workflow)

    def test_cli_reads_and_creates_reports_without_any_database_writes(self):
        client = ReadClient()
        sdk = Mock()
        sdk.embeddings.create.return_value = SimpleNamespace(data=[SimpleNamespace(index=i,
            embedding=[1.] * ai.TOPIC_MERGE_EMBEDDING_DIMENSIONS) for i in range(16)], usage=None)
        with TemporaryDirectory() as folder, patch('sys.argv', ['compare', '--output', folder]), \
             patch.object(compare, 'SupabaseRestClient', return_value=client), \
             patch.object(ai, 'openai_api_key', return_value='fake'), \
             patch('openai.OpenAI', return_value=sdk), patch('builtins.print'):
            self.assertEqual(compare.main(), 0)
            self.assertEqual(len(json.loads((Path(folder) / 'report.json').read_text())['pairs']), 28)
            self.assertEqual(sdk.embeddings.create.call_count, 1)


if __name__ == '__main__':
    unittest.main()
