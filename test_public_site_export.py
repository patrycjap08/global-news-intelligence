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

    def test_perspective_preview_metadata_without_fact_ledger(self):
        rows=self.rows()
        base=rows[0]['summary']['summary']['base_summary']
        base.update(perspective_version=1,coverage_mode='MIXED',shared_available=False,
                    perspective_facts=[{'text_pl':'PRIVATE_LEDGER_NOT_IN_INDEX'}],
                    perspective_sections={'LEFT':[{'text_pl':'LEFT_DETAILS'}]})
        with tempfile.TemporaryDirectory() as folder:
            index=write_site(rows,Path(folder))
            preview=index['summaries'][0]['summary']['base_summary']
            self.assertEqual(preview['perspective_version'],1)
            self.assertIs(preview['shared_available'],False)
            self.assertNotIn('perspective_facts',preview)
            self.assertNotIn('PRIVATE_LEDGER_NOT_IN_INDEX',json.dumps(index))
            detail=json.loads((Path(folder)/index['generation']/'topics/topic_1.json').read_text())
            self.assertEqual(detail['summary']['summary']['base_summary']['perspective_sections'],base['perspective_sections'])

    def test_export_uses_current_fact_state_with_immutable_original_text(self):
        rows=self.rows()
        stored=rows[0]['summary']['summary']
        stored['base_summary'].update(perspective_version=1,coverage_mode='SINGLE_LEFT',shared_available=True)
        original=json.loads(json.dumps(stored['base_summary']))
        stored['perspective_state']={'perspective_version':1,'fact_classification_version':1,'coverage_mode':'MIXED','shared_available':False,
                                     'facts':[],'perspective_facts':[{'text_pl':'NEW_LEDGER'}],
                                     'perspective_sections':{'LEFT':[{'text_pl':'Najnowsza perspektywa.'}]}}
        with tempfile.TemporaryDirectory() as folder:
            index=write_site(rows,Path(folder))
            preview=index['summaries'][0]['summary']['base_summary']
            self.assertEqual(preview['summary_pl'],'Synteza')
            self.assertIs(preview['shared_available'],False)
            self.assertEqual(preview['synthesis_coverage_mode'],'SINGLE_LEFT')
            self.assertEqual(preview['fact_classification_version'],1)
            self.assertNotIn('NEW_LEDGER',json.dumps(index))
            detail=json.loads((Path(folder)/index['generation']/'topics/topic_1.json').read_text())['summary']['summary']
            self.assertEqual(detail['base_summary'],original)
            self.assertEqual(detail['perspective_state'],stored['perspective_state'])

    def test_incomplete_export_preserves_previous_index(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            write_site(self.rows(), path)
            old = (path/'index.json').read_bytes()
            rows = self.rows(); rows[0]['expected_topics'] = 2
            with self.assertRaises(ValueError): write_site(rows, path)
            self.assertEqual(old, (path/'index.json').read_bytes())

    def test_preview_uses_current_text_and_omits_audits_quotes_and_repeated_ledgers(self):
        rows = self.rows()
        stored = rows[0]['summary']['summary']
        stored['current_summary'] = {'topic': {'headline_pl': 'Aktualny tytuł'},
                                     'summary_pl': 'Bieżący opis wydarzenia.', 'publication_version': 2}
        update = {'status': 'NEW_INFORMATION', 'new_information_pl': 'Dokładna treść dla oznaczenia przeczytania.',
                  'generated_at': '2026-10-21', 'perspective_sections': {'COMMON': [{'text_pl': 'DETAIL_ONLY'}]},
                  'novelty_audit': {'private_decision': 'AUDIT_ONLY'}}
        stored.update(latest_update=update, last_analysis=dict(update))
        with tempfile.TemporaryDirectory() as folder:
            index = write_site(rows, Path(folder))
            preview = index['summaries'][0]['summary']
            self.assertEqual(preview['base_summary']['summary_pl'], 'Bieżący opis wydarzenia.')
            self.assertEqual(preview['latest_update']['new_information_pl'], update['new_information_pl'])
            self.assertEqual(preview['latest_update']['section_counts'], {'COMMON': 1})
            self.assertEqual(preview['last_analysis'], {'status': 'NEW_INFORMATION'})
            self.assertNotIn('AUDIT_ONLY', json.dumps(index))
            self.assertNotIn('DETAIL_ONLY', json.dumps(index))
            detail = json.loads((Path(folder) / index['generation'] / 'topics/topic_1.json').read_text())
            self.assertEqual(detail['summary']['summary']['latest_update'], update)

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
