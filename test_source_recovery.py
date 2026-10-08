import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import article_harvester as ah
import source_tester as st


def response(url, text, status=200):
    return st.FetchResult(url, status, url, 'application/xml', text.encode())


class SourceRecoveryTests(unittest.TestCase):
    def test_rss_guid_never_overrides_article_link(self):
        rows = st.parse_feed('<rss><channel><item><guid isPermaLink="false">123</guid>'
                             '<link>https://news.test/story/123</link></item></channel></rss>',
                             'https://news.test/rss/latest')
        self.assertEqual(rows[0]['url'], 'https://news.test/story/123')

    def test_atom_self_link_is_not_article(self):
        rows = st.parse_feed('<feed><entry><link rel="self" href="/api/1"/>'
                             '<link rel="alternate" href="/story/1"/></entry></feed>',
                             'https://news.test/feed')
        self.assertEqual(rows[0]['url'], 'https://news.test/story/1')

    def test_sitemap_uses_article_loc_and_news_date_not_image_loc(self):
        xml = '<urlset xmlns:image="urn:image" xmlns:news="urn:news"><url>' \
              '<loc>https://news.test/story</loc><image:image><image:loc>https://news.test/a.jpg</image:loc></image:image>' \
              '<news:news><news:publication_date>2026-10-08T12:00:00Z</news:publication_date>' \
              '<news:title>Current story</news:title></news:news></url></urlset>'
        rows, news, index = st.parse_sitemap_entries(xml, 'https://news.test')
        self.assertTrue(news)
        self.assertFalse(index)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], 'https://news.test/story')
        self.assertEqual(rows[0]['published_at'], '2026-10-08T12:00:00Z')

    def test_sitemap_fetches_latest_child_within_budget(self):
        calls = []
        index = '<sitemapindex><sitemap><loc>https://news.test/old.xml</loc><lastmod>2020-01-01</lastmod></sitemap>' \
                '<sitemap><loc>https://news.test/new.xml</loc><lastmod>2026-10-08</lastmod></sitemap></sitemapindex>'
        class Client:
            def get(self, url, **kwargs):
                calls.append(url)
                return response(url, index if url.endswith('index.xml') else
                                '<urlset><url><loc>https://news.test/latest</loc></url></urlset>' if url.endswith('new.xml') else '')
        rows, _ = ah._sitemap_candidates(Client(), {'homepage': 'https://news.test',
                                                  'sitemap_urls': ['https://news.test/index.xml']}, {}, 1, 1)
        self.assertNotIn('https://news.test/old.xml', calls)
        self.assertEqual(rows[0]['url'], 'https://news.test/latest')

    def test_feed_dates_enrich_listing_before_limit(self):
        source = {'homepage': 'https://news.test', 'discovery_method': 'SECTION_HTML'}
        listings = [{'url': 'https://news.test/2020/01/01/old', 'title': 'Old headline'},
                    {'url': 'https://news.test/latest', 'title': 'Current headline with enough characters'}]
        feeds = [{'url': 'https://news.test/latest', 'published_at': 'Thu, 08 Oct 2026 09:57:00 +0300'}]
        with patch.object(ah, '_listing_rows', return_value=(listings, response(source['homepage'], ''), [])), \
             patch.object(ah, '_feed_candidates', return_value=(feeds, [])), \
             patch.object(ah, '_wordpress_api_candidates', return_value=([], [])), \
             patch.object(ah, '_sitemap_candidates', return_value=([], [])):
            _, rows, _ = ah.discover_candidates(None, source, {}, Namespace(browser=False,
                                  max_sitemap_probes=1, max_sitemap_children=1, discovery_limit_per_source=1), None)
        self.assertEqual(rows[0]['url'], 'https://news.test/latest')
        self.assertIn('published_at', rows[0])

    def test_full_feed_body_is_opt_in_and_does_not_duplicate_nested_paragraphs(self):
        body = '<ul><li><p>' + 'public story ' * 60 + '</p></li></ul>'
        feed = '<rss><channel><item><link>https://news.test/story</link><description><![CDATA[' + body + ']]></description></item></channel></rss>'
        class Client:
            def get(self, url, **kwargs):
                return response(url, feed)
        source = {'homepage': 'https://news.test', 'rss_urls': ['https://news.test/rss']}
        rows, _ = ah._feed_candidates(Client(), source, [])
        self.assertNotIn('api_body', rows[0])
        rows, _ = ah._feed_candidates(Client(), dict(source, full_text_feed=True), [])
        self.assertEqual(len(rows[0]['api_body'].split()), 120)
        self.assertEqual(rows[0]['api_method'], 'PUBLISHER_RSS')

    def test_challenge_script_is_not_a_visible_captcha(self):
        html = '<script>var template = "verify you are human";</script><article><p>Actual news</p></article>'
        self.assertFalse(st.detect_policy_flags(html, 200)[1])
        self.assertTrue(st.detect_policy_flags('<h1>Verify you are human</h1>', 403)[1])

    def test_axios_includes_story_beyond_smart_brevity(self):
        html = '<html><h1>Headline</h1><div data-cy="story-body"><div data-schema="smart-brevity">' \
               '<p>Lead.</p></div><div data-cy="story-go-deeper-content"><ul><li><p>' \
               + 'Full public reporting ' * 50 + '</p></li></ul></div></div></html>'
        extracted = st.extract_article(response('https://www.axios.com/story', html), 'https://www.axios.com',
                                       include_body=True, source_id='axios')
        self.assertIn('Full public reporting', extracted['body'])
        self.assertLess(extracted['word_count'], 170)
        self.assertGreater(extracted['word_count'], 100)

    def test_business_insider_selects_body_not_lead(self):
        html = '<html><h1>Headline</h1><article class="article"><section class="main"><p>Short lead</p></section>' \
               '<section class="main whitelistPremium"><p>' + 'Full public reporting ' * 50 + '</p></section></article></html>'
        extracted = st.extract_article(response('https://businessinsider.com.pl/story', html),
                    'https://businessinsider.com.pl', include_body=True, source_id='business_insider_pl')
        self.assertGreater(extracted['word_count'], 100)
        self.assertNotIn('Short lead', extracted['body'])

    def test_kommersant_reads_actual_div_paragraphs_instead_of_related_article(self):
        html = '<html><h1>Headline</h1><article><p>Unrelated sidebar</p></article>' \
               '<div class="article_text_wrapper"><div class="doc-text-block__paragraph">' \
               + 'Public news text ' * 50 + '</div></div></html>'
        extracted = st.extract_article(response('https://www.kommersant.ru/doc/1', html),
                    'https://www.kommersant.ru', include_body=True, source_id='kommersant')
        self.assertGreater(extracted['word_count'], 100)
        self.assertNotIn('Unrelated sidebar', extracted['body'])

    def test_fixed_source_patterns_accept_stories_and_reject_navigation(self):
        _, sources = st.load_config(Path(__file__).with_name('sources.yaml'))
        by_id = {s['id']: s for s in sources}
        for sid, good, bad in [
            ('kommersant', 'https://www.kommersant.ru/doc/9008807', 'https://www.kommersant.ru/fm/player'),
            ('kyiv_post', 'https://www.kyivpost.com/post/86404', 'https://www.kyivpost.com/help'),
            ('ukrinform', 'https://www.ukrinform.net/rubric-ato/4172170-story.html', 'https://www.ukrinform.net/info/policy.html'),
            ('tass', 'https://tass.com/emergencies/2199081', 'https://tass.com/economy'),
            ('times', 'https://www.thetimes.com/uk/politics/article/example', 'https://www.thetimes.com/uk/politics'),
            ('polsat_news', 'https://www.polsatnews.pl/wiadomosc/2026-10-08/news/', 'https://www.polsatnews.pl/wiadomosci/polska/'),
            ('npr', 'https://www.npr.org/2026/10/08/nx-s1-5994868/story', 'https://help.npr.org/article/faq'),
            ('huffpost', 'https://www.huffpost.com/entry/news_n_6ac66088e4b09d2661d2ddd0', 'https://www.huffpost.com/news/'),
            ('bild', 'https://www.bild.de/politik/story-6ac7244be51bfb79beba62b3', 'https://www.bild.de/news/startseite/news-123.bild.html'),
            ('faz', 'https://www.faz.net/aktuell/finanzen/example-201277196.html', 'https://www.faz.net/premium/digitalwirtschaft/'),
        ]:
            with self.subTest(source=sid):
                self.assertTrue(st.candidate_allowed(by_id[sid], good, 'Current story'))
                self.assertFalse(st.candidate_allowed(by_id[sid], bad, 'Navigation'))


if __name__ == '__main__':
    unittest.main()
