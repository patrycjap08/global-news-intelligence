"""Recovery regressions from the October 28 source audit, without networking."""
from argparse import Namespace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import article_harvester as h
import audit_harvest_sources as audit
import source_tester as st


def response(url, text='', status=200):
    return st.FetchResult(url, status, url, 'text/html; charset=utf-8', text.encode())


class SourceRecoveryAuditTests(unittest.TestCase):
    def setUp(self):
        self.sources = {s['id']: s for s in st.load_config(Path(__file__).with_name('sources.yaml'))[1]}
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / 'articles.sqlite3'
        self.conn = h.open_db(self.db)
        self.addCleanup(self.conn.close)

    def args(self, count=1):
        return Namespace(browser=False, max_sitemap_probes=1, max_sitemap_children=1,
                         discovery_limit_per_source=10, top_articles_per_source=count,
                         daily_max_articles_per_source=0, retry_failed=False, retry_rejected=False)

    def test_configured_feeds_survive_an_unreadable_homepage(self):
        cases = [('polsat_news', 'https://www.polsatnews.pl/wiadomosc/2026-10-28/nowa-decyzja-rzadu/'),
                 ('do_rzeczy', 'https://dorzeczy.pl/kraj/963549/nowa-decyzja-rzadu.html'),
                 ('npr', 'https://www.npr.org/2026/10/28/nx-s1-6020425/federal-reserve-interest-rates-inflation'),
                 ('kyiv_independent', 'https://kyivindependent.com/new-government-decision/')]
        for sid, article_url in cases:
            source = self.sources[sid]
            self.assertTrue(source['rss_urls'])
            feed_url = source['rss_urls'][0]
            feed = f'<rss><channel><item><title>Nowa decyzja rządu</title><link>{article_url}</link></item></channel></rss>'
            class Client:
                def get(self, url, **kwargs):
                    return response(url, feed) if url == feed_url else response(url, '<h1>Forbidden</h1>', 403)
            with self.subTest(source=sid):
                home, candidates, _ = h.discover_candidates(Client(), source, {}, self.args(), None)
                self.assertEqual(home.status, 403)
                self.assertEqual([c['url'] for c in candidates], [article_url])

    def test_reuters_uses_configured_news_map_when_homepage_and_robots_are_blocked(self):
        source = self.sources['reuters']
        url = 'https://www.reuters.com/world/europe/new-government-decision-2026-10-28/'
        sitemap = f'<urlset xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"><url><loc>{url}</loc><news:news><news:title>Government decision</news:title><news:publication_date>2026-10-28</news:publication_date></news:news></url></urlset>'
        class Client:
            def get(self, endpoint, **kwargs):
                return response(endpoint, sitemap) if endpoint == source['sitemap_urls'][0] else response(endpoint, 'Unauthorized', 401)
        _, candidates, _ = h.discover_candidates(Client(), source, {}, self.args(), None)
        self.assertEqual([c['url'] for c in candidates], [url])

    def test_publisher_full_rss_recovers_article_without_reading_a_blocked_webpage(self):
        for sid, path in [('meduza', '/news/2026/10/28/government-decision'),
                          ('daily_signal', '/2026/10/28/government-decision/')]:
            source = self.sources[sid]
            url = source['homepage'] + path
            body = 'The government announced a new decision about public investment. ' * 16
            feed = f'<rss><channel><item><title>Government decision</title><link>{url}</link><description><![CDATA[<p>{body}</p>]]></description></item></channel></rss>'
            calls = []
            class Client:
                def get(self, endpoint, **kwargs):
                    calls.append(endpoint)
                    return response(endpoint, feed) if endpoint == source['rss_urls'][0] else response(endpoint, 'Forbidden', 403)
            # A remembered short extraction must not suppress the now-available
            # full first-party RSS text, and no retry_rejected switch is needed.
            h.save_rejection(self.conn, sid, url, 'Government decision', 20, '', 'TOO_SHORT', h.utc_now())
            with self.subTest(source=sid), patch.object(st, 'HttpClient', return_value=Client()):
                counts = h.harvest_source(self.conn, 'test', source, {}, self.args(), None)
                self.assertEqual(counts['valid'], 1)
                self.assertEqual(counts['failed'], 0)
                self.assertNotIn(url, calls)
                saved = self.conn.execute('SELECT fetch_method,body FROM articles WHERE source_id=?', (sid,)).fetchone()
                self.assertEqual(saved['fetch_method'], 'PUBLISHER_RSS')
                self.assertEqual(saved['body'], st.clean_text(body))

    def test_meduza_reads_material_body_without_a_related_story_or_navigation(self):
        body = 'Rząd przyjął nowe przepisy dotyczące budowy szkół i finansowania samorządów. ' * 15
        html = '<html><h1>Nowe przepisy</h1><div class="GeneralMaterial-module-body"><p>' + body + '</p>' \
               '<div class="RelatedMaterial-module-root"><article><h2>UNRELATED_STORY</h2><p>UNRELATED_TEXT</p></article></div></div></html>'
        result = st.extract_article(response('https://meduza.io/news/2026/10/28/decision', html),
                                    'https://meduza.io', include_body=True, source_id='meduza')
        self.assertEqual(result['body'], st.clean_text(body))
        self.assertTrue(result['body_success'])
        missing = st.extract_article(response('https://meduza.io/news/2026/10/28/decision',
            '<h1>News</h1><article><h2>Related story</h2><p>' + body + '</p></article>'),
            'https://meduza.io', include_body=True, source_id='meduza')
        self.assertEqual(missing['body'], '')

    def test_profiles_and_liveblogs_do_not_consume_the_article_window(self):
        for sid, good, bad in [
            ('kyiv_independent', '/new-government-decision/', ['/author/abbey/', '/tag/politics/', '/news-archive/']),
            ('le_monde', '/international/article/2026/10/28/decision_123_3210.html', ['/international/live/2026/10/28/events_123.html']),
            ('el_pais', '/internacional/2026-10-28/decision.html', ['/internacional/2026-10-28/elecciones-en-directo.html']),
        ]:
            source = self.sources[sid]
            with self.subTest(source=sid):
                self.assertTrue(st.candidate_allowed(source, source['homepage'] + good))
                for path in bad:
                    self.assertFalse(st.candidate_allowed(source, source['homepage'] + path))

    def test_paid_preview_is_not_reported_as_short_news_or_retried_in_browser(self):
        preview = 'This article is available only to subscribers. ' * 8
        html = '<html><h1>Important decision</h1><script type="application/ld+json">' \
               + json.dumps({'@type':'NewsArticle', 'isAccessibleForFree':False}) + '</script><article><p>' + preview + '</p></article></html>'
        source = self.sources['times']
        with patch.object(st, 'browser_navigate') as browser:
            class Client:
                def get(self, url): return response(url, html)
            result, _ = h.fetch_one(Client(), object(), source, source['homepage'] + '/uk/article/story', True)
        browser.assert_not_called()
        self.assertEqual(h.classify_item(result)[1], 'PAYWALL')
        self.assertFalse(result['body_success'])
        # Some sites mark the whole section as subscriber-only even when
        # the complete public article is present. Preserve that visible text.
        long = html.replace(preview, preview * 4)
        extracted = st.extract_article(response(source['homepage'], long), source['homepage'], include_body=True)
        self.assertTrue(extracted['body_success'])

    def test_blocked_failed_and_captcha_responses_increment_persisted_failure_count(self):
        source = {'id':'test','name':'Test','homepage':'https://example.test'}
        candidates = [{'url':source['homepage'] + suffix} for suffix in ('/blocked','/missing','/captcha')]
        class Client:
            def get(self, url):
                if url.endswith('/blocked'): return response(url, '<h1>Forbidden</h1>', 403)
                if url.endswith('/missing'): return response(url, '<h1>Not found</h1><p>' + 'Error text ' * 100 + '</p>', 404)
                return response(url, '<h1>Verify you are human</h1>', 403)
        with patch.object(st, 'HttpClient', return_value=Client()), patch.object(h, 'discover_candidates',
                return_value=(response(source['homepage']),candidates,[])):
            result = h.harvest_source(self.conn, 'test', source, {}, self.args(3), None)
        self.assertEqual(result['failed'], 3)
        self.assertEqual(result['valid'], 0)
        saved = self.conn.execute('SELECT failed_count,notes FROM source_run_results').fetchone()
        self.assertEqual(saved['failed_count'], 3)
        self.assertIn('BLOCKED:1', saved['notes'])
        self.assertIn('CAPTCHA:1', saved['notes'])
        self.assertIn('FAILED:1', saved['notes'])

    def test_discovery_exception_is_visible_in_database_source_statistics(self):
        source = {'id':'test','name':'Test','homepage':'https://example.test'}
        db = Path(self.folder.name) / 'source-error.sqlite3'
        argv = ['article_harvester.py','--db',str(db),'--runtime-config',str(Path(self.folder.name)/'none.yml')]
        with patch('sys.argv', argv), patch.object(st, 'load_config', return_value=({}, [source])), \
             patch.object(h, 'harvest_source', side_effect=RuntimeError('Source discovery failed')), \
             patch.object(h, 'export_files'), patch.object(h, 'log'):
            h.main()
        with sqlite3.connect(db) as conn:
            self.assertEqual(conn.execute('SELECT failed_count FROM source_run_results').fetchone()[0], 1)

    def test_empty_discovery_is_counted_and_explained_in_source_statistics(self):
        source = {'id':'test','name':'Test','homepage':'https://example.test'}
        for status in (200, 403):
            with self.subTest(status=status), patch.object(h, 'discover_candidates', return_value=(
                    response(source['homepage'], status=status), [], ['no_candidates'])):
                result = h.harvest_source(self.conn, str(status), source, {}, self.args(), None)
            self.assertEqual(result['failed'], 1)
            self.assertIn('discovery_failed=no_eligible_candidates', result['notes'])
            row = self.conn.execute('SELECT failed_count,notes FROM source_run_results WHERE run_id=?',
                                    (str(status),)).fetchone()
            self.assertEqual(row['failed_count'], 1)

    def test_unavailable_configured_discovery_endpoints_are_reported(self):
        source = {'homepage':'https://example.test', 'rss_urls':['https://example.test/rss'],
                  'sitemap_urls':['https://example.test/news.xml']}
        class Client:
            def get(self, url, **kwargs): return response(url, '<h1>Forbidden</h1>', 403)
        _, feed_notes = h._feed_candidates(Client(), source, [])
        _, map_notes = h._sitemap_candidates(Client(), source, {}, 1, 1)
        self.assertIn('rss_unavailable=https://example.test/rss (HTTP 403)', feed_notes)
        self.assertIn('sitemap_unavailable=https://example.test/news.xml (HTTP 403)', map_notes)

    def test_times_has_a_direct_news_map_when_homepage_and_robots_fail(self):
        source = self.sources['times']
        endpoint = 'https://www.thetimes.com/sitemaps/news'
        story = source['homepage'] + '/uk/politics/article/public-report'
        class Client:
            def get(self, url, **kwargs):
                return response(url, '<urlset><url><loc>' + story + '</loc></url></urlset>') \
                    if url == endpoint else response(url, '<h1>Unavailable</h1>', 403)
        _, rows, _ = h.discover_candidates(Client(), source, {}, self.args(), None)
        self.assertEqual([row['url'] for row in rows], [story])

    def test_times_empty_article_cannot_be_filled_with_navigation_and_footer(self):
        url = self.sources['times']['homepage'] + '/uk/article/report'
        html = '<h1>Report</h1><nav><p>' + 'NAVIGATION ' * 200 + '</p></nav>' \
               '<script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":false}</script>' \
               '<article id="article-main"><div class="article-content-wrapper"></div></article>' \
               '<footer><p>' + 'SUBSCRIBE ' * 100 + '</p></footer>'
        item = st.extract_article(response(url, html), url, include_body=True, source_id='times')
        self.assertEqual(item['body'], '')
        self.assertFalse(item['body_success'])
        self.assertEqual(h.classify_item(item)[1], 'PAYWALL')
        public_body = 'Public reporting about the new government decision. ' * 20
        html = html.replace('<div class="article-content-wrapper"></div>',
                            '<div class="article-content-wrapper"><p>' + public_body + '</p></div>')
        item = st.extract_article(response(url, html), url, include_body=True, source_id='times')
        self.assertEqual(item['body'], st.clean_text(public_body))
        self.assertTrue(item['body_success'])

    def test_figaro_keeps_story_and_lead_without_subscription_and_follow_widgets(self):
        body = 'Public reporting about the new decision. ' * 20
        html = '<h1>News</h1><article><p class="fig-standfirst">A short lead.</p>' \
               '<div class="fig-follow-google"><p>FOLLOW_WIDGET</p></div>' \
               '<div class="fig-tooltip"><p>SUBSCRIBE_TOOLTIP</p></div>' \
               '<div class="fig-content-body"><p>' + body + '</p>' \
               '<p class="fig-body-cta-link">PROMOTIONAL_LINK</p></div></article>'
        url = self.sources['le_figaro']['homepage'] + '/international/report-20261028'
        item = st.extract_article(response(url, html), url, include_body=True, source_id='le_figaro')
        self.assertEqual(item['body'], 'A short lead. ' + st.clean_text(body))
        self.assertTrue(item['body_success'])
        missing = html.replace('fig-content-body', 'no-story-body')
        item = st.extract_article(response(url, missing), url, include_body=True, source_id='le_figaro')
        self.assertEqual(item['body'], '')

    def test_short_replacement_queue_stops_after_one_extra_window(self):
        source = {'id':'test','name':'Test','homepage':'https://example.test'}
        candidates = [{'url':source['homepage'] + '/story-' + str(i)} for i in range(100)]
        short = {'status':200, 'title':'Short news', 'body':'Too short.', 'word_count':2, 'body_success':False}
        with patch.object(h, 'discover_candidates', return_value=(response(source['homepage']), candidates, [])), \
             patch.object(h, 'fetch_one', return_value=(short, 'HTTP_HTML')) as fetch:
            result = h.harvest_source(self.conn, 'test', source, {}, self.args(2), None)
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual(result['discovered'], 4)
        self.assertEqual(result['rejected_short'], 4)
        self.assertIn('short_followup_limit_reached=2', result['notes'])

    def test_cached_short_rejections_cannot_expand_the_queue_indefinitely(self):
        source = {'id':'test','name':'Test','homepage':'https://example.test'}
        candidates = [{'url':source['homepage'] + '/story-' + str(i)} for i in range(100)]
        short = {'status':200, 'title':'Short news', 'body':'Too short.', 'word_count':2, 'body_success':False}
        for candidate in candidates[:8]:
            h.save_article(self.conn, 'old', source, candidate['url'], short, 'HTTP_HTML', h.utc_now())
        with patch.object(h, 'discover_candidates', return_value=(response(source['homepage']), candidates, [])), \
             patch.object(h, 'fetch_one') as fetch:
            result = h.harvest_source(self.conn, 'test', source, {}, self.args(2), None)
        fetch.assert_not_called()
        self.assertEqual(result['skipped_rejected'], 4)
        self.assertEqual(result['discovered'], 4)

    def test_section_replacements_are_bounded_and_stay_in_the_original_section(self):
        source = {'id':'test','name':'Test','homepage':'https://example.test', 'top_articles_per_section':1}
        candidates = [{'url':source['homepage'] + '/story-' + str(i), 'section_key':str(i % 2)} for i in range(100)]
        short = {'status':200, 'title':'Short news', 'body':'Too short.', 'word_count':2, 'body_success':False}
        with patch.object(h, 'discover_candidates', return_value=(response(source['homepage']), candidates, [])), \
             patch.object(h, 'fetch_one', return_value=(short, 'HTTP_HTML')) as fetch:
            result = h.harvest_source(self.conn, 'test', source, {}, self.args(2), None)
        self.assertEqual([call.args[3] for call in fetch.call_args_list], [c['url'] for c in candidates[:4]])
        self.assertEqual(result['fetched'], 4)
        self.assertIn('short_followup_limit_reached=2', result['notes'])

    def test_short_replacement_can_be_disabled_per_source(self):
        source = {'id':'test','name':'Test','homepage':'https://example.test', 'max_short_followups':0}
        candidates = [{'url':source['homepage'] + '/story-' + str(i)} for i in range(10)]
        short = {'status':200, 'title':'Short news', 'body':'Too short.', 'word_count':2, 'body_success':False}
        with patch.object(h, 'discover_candidates', return_value=(response(source['homepage']), candidates, [])), \
             patch.object(h, 'fetch_one', return_value=(short, 'HTTP_HTML')) as fetch:
            result = h.harvest_source(self.conn, 'test', source, {}, self.args(2), None)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('short_followup_limit_reached=0', result['notes'])

    def test_diagnostic_probe_is_bounded_and_never_saves_articles_or_full_bodies(self):
        source = {'id':'test','name':'Test','homepage':'https://example.test'}
        text = 'PUBLIC_FEED_BODY ' * 150
        candidates = [{'url':'https://example.test/feed-story','api_body':text,'api_title':'Feed story','api_method':'PUBLISHER_RSS'},
                      {'url':'https://example.test/http-story'}, {'url':'https://example.test/not-to-be-fetched'}]
        with patch.object(h, 'discover_candidates', return_value=(response(source['homepage']),candidates,[])), \
             patch.object(h, 'fetch_one', return_value=({'title':'Story','status':200,'body_success':True,
                 'word_count':150,'body':'NEVER_EXPORT_SOURCE_BODY'},'HTTP_HTML')) as fetch, \
             patch.object(h, 'open_db') as database, patch.object(h, 'save_article') as save:
            result = audit.audit_source(source, {}, probes=2)
        self.assertEqual(result['candidate_count'], 3)
        self.assertEqual(len(result['articles']), 2)
        fetch.assert_called_once()
        database.assert_not_called()
        save.assert_not_called()
        self.assertNotIn('PUBLIC_FEED_BODY', json.dumps(result))
        self.assertNotIn('NEVER_EXPORT_SOURCE_BODY', json.dumps(result))

    def test_diagnostic_cli_cannot_reenable_a_disabled_source(self):
        with patch('sys.argv', ['audit_harvest_sources.py','--source','rt']), \
             patch.object(audit, 'audit_source') as probe:
            with self.assertRaises(SystemExit) as caught:
                audit.main()
        self.assertEqual(caught.exception.code, 2)
        probe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
