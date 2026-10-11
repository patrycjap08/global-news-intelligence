from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import article_harvester as ah
import supabase_sync as sync

class ForeignKeyClient:
    def __init__(self, existing=()):
        self.articles=set(existing); self.sent=[]
    def upsert(self, table, rows, *, on_conflict):
        if table=='articles':self.articles.update(r['article_id'] for r in rows)
        if table=='run_articles':
            for row in rows:
                if row['article_id'] not in self.articles:raise AssertionError('Missing article parent')
        self.sent.append((table,rows))

class HarvestSyncIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.db=Path(self.folder.name)/'articles.sqlite3'
        self.conn=ah.open_db(self.db);self.addCleanup(self.conn.close)
        self.run='run';self.stamp='2026-10-11T16:02:26+00:00'
        self.conn.execute("INSERT INTO harvest_runs(run_id,started_at,status) VALUES(?,?,?)",(self.run,self.stamp,'COMPLETE'))
        self.source=dict(id='source',name='Źródło',homepage='https://news.test')

    def save(self, when=None):
        return ah.save_article(self.conn,self.run,self.source,'https://news.test/redirect',
                              dict(url='https://news.test/article',title='Nowy materiał',body='Treść '*150,
                                   body_success=True,word_count=150,status=200),'HTTP',when or self.stamp)[0]

    def test_repeated_canonical_listing_does_not_erase_fetched_flag(self):
        args=Namespace(top_articles_per_source=10,daily_max_articles_per_source=0,retry_rejected=False,retry_failed=False,browser=False)
        candidates=[dict(url='https://news.test/redirect'),dict(url='https://news.test/article')]
        extraction=dict(url='https://news.test/article',title='Nowy materiał',body='Treść '*150,body_success=True,word_count=150,status=200)
        with patch.object(ah,'discover_candidates',return_value=(Namespace(status=200),candidates,[])), \
             patch.object(ah,'fetch_one',return_value=(extraction,'HTTP')) as fetch,patch.object(ah,'utc_now',return_value=self.stamp):
            ah.harvest_source(self.conn,self.run,self.source,{},args,None)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(self.conn.execute('SELECT fetched_now FROM run_articles').fetchone()[0],1)
        self.conn.commit()
        client=ForeignKeyClient();counts=sync.push_run(self.db,self.run,client)
        self.assertEqual(counts['articles'],1);self.assertEqual(counts['run_articles'],1)

    def test_legacy_downgraded_flag_still_uploads_new_parent_before_links(self):
        aid=self.save();self.conn.execute('UPDATE run_articles SET fetched_now=0');self.conn.commit()
        client=ForeignKeyClient();counts=sync.push_run(self.db,self.run,client)
        self.assertEqual(counts['articles'],1)
        self.assertIn(aid,client.articles)
        tables=[table for table,_ in client.sent]
        self.assertLess(tables.index('articles'),tables.index('run_articles'))
        sync.push_run(self.db,self.run,client) # repeated synchronization is safe

    def test_existing_article_is_not_uploaded_again(self):
        aid=self.save('2026-10-10T16:00:00Z');self.conn.execute('UPDATE run_articles SET fetched_now=0');self.conn.commit()
        client=ForeignKeyClient([aid]);counts=sync.push_run(self.db,self.run,client)
        self.assertEqual(counts['articles'],0);self.assertEqual(counts['run_articles'],1)

    def test_missing_local_parent_fails_before_any_remote_write(self):
        self.conn.execute('INSERT INTO run_articles(run_id,article_id) VALUES(?,?)',(self.run,'missing'));self.conn.commit()
        client=ForeignKeyClient()
        with self.assertRaisesRegex(RuntimeError,'brak lokalnych artykułów'):sync.push_run(self.db,self.run,client)
        self.assertEqual(client.sent,[])

if __name__=='__main__':unittest.main()
