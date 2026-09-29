import unittest

import source_tester as st


ARTICLE_URL = (
    "https://businessinsider.com.pl/gospodarka/"
    "nie-bedzie-prezentow-przed-wyborami-andrzej-domanski-zapewnia/nlg4013"
)

LISTING_HTML = """
<section class="main singleSectionHorizontal">
  <div class="list-driver" data-section="bi2_driver_hp">
    <a href="https://businessinsider.com.pl/firmy/paliwo-drozeje-lotniska-i-linie-bija-rekordy-zbliza-sie-punkt-krytyczny/r9nvbhc" class="list-item item--xl">
      <h3 class="item_title">Ceny paliw szaleją, ale linie lotnicze biją rekordy</h3>
      <time class="item_time" datetime="2026-09-29T03:36:00.000Z">dzisiaj</time>
      <span class="item_author">Grzegorz Kowalczyk</span>
    </a>
    <a href="https://businessinsider.com.pl/prawo/podatki/sprzedales-krypto-przed-blokada-zondacrypto/0nz36v1" class="list-item item--m">
      <h3 class="item_title">Fiskus żąda podatku od klientów</h3>
    </a>
  </div>
</section>
"""

ARTICLE_HTML = """
<section class="main">
  <div class="article_header">
    <div class="breadcrumbs">Business Insider Gospodarka</div>
    <h1 class="article_title">Nie będzie prezentów przed wyborami</h1>
    <div class="article-author_container--top" data-section="author-top">
      <div class="article-author_text">Opracowanie: Mateusz Madejski</div>
    </div>
    <time datetime="2026-09-29T05:35:25.000Z">29 września 2026</time>
    <section class="article-share"><p>Udostępnij artykuł</p></section>
  </div>
  <div class="article_lead"><p class="article_p" data-section="detail-body">Minister przedstawił stanowisko rządu w sprawie wydatków publicznych i planowanego budżetu.</p></div>
  <p class="article_p" data-section="detail-body">W rozmowie wyjaśnił, że dodatkowe transfery muszą być oceniane pod kątem stabilności finansów państwa. Decyzje budżetowe mają uwzględniać sytuację gospodarczą oraz potrzeby obywateli.</p>
  <h2>Plan finansowy</h2>
  <p class="article_p" data-section="detail-body">Resort zapowiada ostrożne podejście do nowych zobowiązań. Priorytetem pozostaje utrzymanie wiarygodności kraju i realizacja wcześniej przyjętych programów inwestycyjnych.</p>
  <div class="article_image"><p>Minister Andrzej Domański | Foto: East News</p></div>
  <div class="article-related"><p>Polecany materiał</p></div>
  <div class="continue-prompt"><p>Zamknij</p></div>
</section>
"""


class BusinessInsiderTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "candidate_include_host_patterns": [r"^(?:www\.)?businessinsider\.com\.pl$"],
            "candidate_include_url_patterns": [r"^/(?:[^/]+/){2,3}[^/?#]+/?$"],
            "candidate_exclude_url_patterns": [r"^/(?:autorzy|wideo|video|podcast|sport)(?:/|$)"],
        }

    def test_listing_url_patterns_keep_both_article_shapes(self):
        parser = st.PageParser()
        parser.feed(LISTING_HTML)
        accepted = [
            link["href"] for link in parser.links
            if st.candidate_allowed(self.source, link["href"], link.get("text", ""))
        ]

        self.assertEqual(len(accepted), 2)
        self.assertTrue(st.candidate_allowed(self.source, ARTICLE_URL, "Artykuł"))
        self.assertFalse(st.candidate_allowed(self.source, "https://businessinsider.com.pl/autorzy/test", "Autor"))
        self.assertFalse(st.candidate_allowed(self.source, "https://businessinsider.com.pl/sport/mecz/test/abc123", "Mecz"))

    def test_article_extracts_clean_metadata_and_body(self):
        result = st.FetchResult(
            url=ARTICLE_URL,
            status=200,
            final_url=ARTICLE_URL,
            content_type="text/html",
            body=ARTICLE_HTML.encode("utf-8"),
        )
        extracted = st.extract_article(
            result,
            "https://businessinsider.com.pl",
            include_body=True,
            source_id="business_insider_pl",
        )

        self.assertEqual(extracted["title"], "Nie będzie prezentów przed wyborami")
        self.assertEqual(extracted["author"], "Mateusz Madejski")
        self.assertEqual(extracted["published_at"], "2026-09-29T05:35:25.000Z")
        self.assertIn("Minister przedstawił stanowisko", extracted["description"])
        self.assertIn("Plan finansowy", extracted["body"])
        self.assertNotIn("Udostępnij artykuł", extracted["body"])
        self.assertNotIn("Minister Andrzej Domański | Foto", extracted["body"])
        self.assertNotIn("Polecany materiał", extracted["body"])
        self.assertNotIn("Zamknij", extracted["body"])
        self.assertTrue(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
