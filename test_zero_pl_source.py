import json
import unittest
from pathlib import Path

import article_harvester as ah
import source_tester as st


class ZeroPlSourceTests(unittest.TestCase):
    def test_complete_public_body_excludes_other_stories_and_ads(self):
        url = "https://zero.pl/news/przykladowy-temat"
        lead = "Wprowadzenie do tematu."
        first = "Pierwszy akapit zawiera informacje o wydarzeniu. " * 20
        last = "Ostatni akapit zawiera dalsze ustalenia. " * 20
        html = '<html><head><script type="application/ld+json">' + json.dumps({
            "@type": "NewsArticle", "headline": "Polski tytuł materiału",
            "author": {"@type": "Person", "name": "Anna Testowa"},
            "datePublished": "2026-10-19T12:00:00+00:00",
        }) + '</script><meta name="author" content="Anna Testowa"><link rel="canonical" href="' + url + '"></head><body>' \
            '<nav>MENU NIE JEST TRESCIA</nav><article><h1>Polski tytuł materiału</h1>' \
            '<div class="prose"><p class="post-excerpt">' + lead + '</p><p>' + first + '</p>' \
            '<div class="ad-slot-wrapper"><p>REKLAMA NIE JEST TRESCIA</p></div>' \
            '<h2>Dalsze informacje</h2><ul><li><p>Pojedyncze ustalenie z listy.</p></li></ul>' \
            '<p>Może zainteresuje Cię również:</p><div class="posts-grid">' \
            '<article class="post"><h3>OBCY TYTUL</h3><p>OBCY ARTYKUL</p></article></div>' \
            '<p>' + last + '</p></div></article><footer>STOPKA NIE JEST TRESCIA</footer></body></html>'
        result = st.extract_article(
            st.FetchResult(url, 200, url, "text/html; charset=utf-8", html.encode()),
            "https://zero.pl", include_body=True, source_id="zero_pl",
        )
        self.assertTrue(result["body_success"])
        self.assertEqual(result["url"], url)
        self.assertEqual(result["author"], "Anna Testowa")
        self.assertEqual(result["published_at"], "2026-10-19T12:00:00+00:00")
        self.assertIn(st.clean_text(first), result["body"])
        self.assertTrue(result["body"].endswith(st.clean_text(last)))
        self.assertEqual(result["body"].count("Pojedyncze ustalenie z listy."), 1)
        for excluded in ("REKLAMA", "OBCY", "MENU", "STOPKA", "Może zainteresuje"):
            self.assertNotIn(excluded, result["body"])

    def test_listing_or_shell_without_prose_never_becomes_an_article(self):
        url = "https://zero.pl/news/brak-tresci"
        html = '<h1>Strona bez treści</h1><article class="post"><p>' + "Polecany tekst " * 100 + '</p></article>'
        result = st.extract_article(
            st.FetchResult(url, 200, url, "text/html", html.encode()),
            "https://zero.pl", include_body=True, source_id="zero_pl",
        )
        self.assertFalse(result["body_success"])
        self.assertEqual(result["body"], "")

    def test_source_config_filters_urls_and_uses_polish_window(self):
        _, sources = st.load_config(Path(__file__).with_name("sources.yaml"))
        source = next(s for s in sources if s["id"] == "zero_pl")
        self.assertTrue(source.get("enabled", True))
        self.assertEqual(source["editorial_profile"], "CENTER_RIGHT")
        self.assertEqual(source["discovery_method"], "NEWS_SITEMAP")
        self.assertEqual(source["content_method"], "HTTP_HTML")
        self.assertEqual(ah.effective_top_articles_limit(source, 10), 15)
        self.assertEqual(ah.source_language(source), "pl")
        self.assertTrue(ah._candidate_allowed(source, "https://zero.pl/news/nowa-decyzja", "Nowa decyzja"))
        for url, title in (
            ("https://zero.pl/kategoria/kraj", "Wiadomości z kraju"),
            ("https://zero.pl/szukaj", "Szukaj"),
            ("https://zero.pl/program-tv", "Program TV"),
            ("https://zero.pl.evil.test/news/nowa-decyzja", "Nowa decyzja"),
            ("https://zero.pl/news/relacja-sportowa", "Piłkarz wygrał turniej"),
        ):
            with self.subTest(url=url, title=title):
                self.assertFalse(ah._candidate_allowed(source, url, title))


if __name__ == "__main__":
    unittest.main()
