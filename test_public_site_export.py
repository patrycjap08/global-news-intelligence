import csv
import json
import tempfile
import unittest
from pathlib import Path
from export_public_site import load_export, write_site

class PublicExportTests(unittest.TestCase):
    def rows(self):
        return [dict(schema=1, expected_topics=1, exported_at='2026-10-09T10:00:00Z',
            topic=dict(topic_id='topic_1', headline_pl='Wątek', source_count=2),
            articles=[dict(article_id='a1', title='Materiał', body='NEVER_EXPORT_BODY')],
            links=[dict(topic_id='topic_1', article_id='a1')],
            summary=dict(topic_id='topic_1', version=2, summary=dict(base_summary=dict(summary_pl='Synteza', facts=['Fakt']), updates=[dict(status='UPDATED', new_information_pl='Aktualizacja')])),
            history=[])]

    def test_lazy_public_snapshot_and_deterministic_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            index = write_site(self.rows(), path)
            self.assertEqual(index['generation'], write_site(self.rows(), path)['generation'])
            self.assertNotIn('facts', index['summaries'][0]['summary']['base_summary'])
            detail = json.loads((path/index['generation']/'topics/topic_1.json').read_text())
            self.assertEqual(detail['summary']['summary']['base_summary']['facts'], ['Fakt'])
            self.assertEqual(len(detail['summary']['summary']['updates']), 1)
            self.assertNotIn('NEVER_EXPORT_BODY', (path/'index.json').read_text())

    def test_incomplete_export_preserves_previous_index(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            write_site(self.rows(), path)
            old = (path/'index.json').read_bytes()
            rows = self.rows(); rows[0]['expected_topics'] = 2
            with self.assertRaises(ValueError): write_site(rows, path)
            self.assertEqual(old, (path/'index.json').read_bytes())

    def test_csv_export_with_quotes_newlines_and_polish(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'export.csv'
            rows=self.rows();rows[0]['topic']['headline_pl']='Polska: „Nowy”\nWątek'
            with path.open('w',newline='',encoding='utf-8-sig') as handle:
                writer=csv.DictWriter(handle,fieldnames=['payload']);writer.writeheader();writer.writerow({'payload':json.dumps(rows[0],ensure_ascii=False)})
            self.assertEqual(load_export(path), rows)

    def test_reject_path_traversal_and_missing_article(self):
        for change in ('path', 'article'):
            rows=self.rows()
            if change=='path':rows[0]['topic']['topic_id']='../outside'
            else:rows[0]['articles']=[]
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):write_site(rows,Path(folder))

if __name__ == '__main__': unittest.main()
