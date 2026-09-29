import unittest

import source_tester as st


ONET_URL = (
    "https://wiadomosci.onet.pl/swiat/ataki-w-ukrainie-"
    "alert-rcb-w-polsce-i-alarmy-w-kijowie-podsumowanie-nocy/lenfbl7"
)

ONET_ARTICLE_HTML = """
<html><head>
  <meta name="description" content="Lead Onetu o wydarzeniu." />
  <link rel="canonical" href="https://wiadomosci.onet.pl/swiat/test/lenfbl7" />
</head><body>
  <section class="main">
    <article class="ods-article-lead">
      <h1 class="ods-m-labeled-h1__text">Tytuł artykułu Onetu</h1>
      <div data-section="author-top">
        <div class="ods-m-author-authorship__author-item">
          <a>Dziennikarze Onet Wiadomości</a>
        </div>
        <div class="ods-m-author-authorship__author-item">
          <a>Patrycja Klimek</a>
        </div>
      </div>
      <time datetime="2026-09-29T05:50:22+0200">29 września 2026</time>
      <div class="ods-c-share-buttons-wrapper">
        <div class="ods-c-share-buttons-wrapper__share"><p>Udostępnij artykuł</p></div>
        <div class="ods-c-share-buttons-wrapper__content">
          <section class="ods-a-lead"><p class="ods-a-lead-text">Lead artykułu.</p></section>
          <div class="ods-o-inline-tts-player-wrapper"><h4>Posłuchaj artykułu</h4></div>
          <p>Główny akapit zawiera najważniejsze informacje i kontekst wydarzenia.</p>
          <h2>Śródtytuł</h2>
          <p>Drugi akapit rozwija opis sprawy i przedstawia jej aktualny stan.</p>
        </div>
      </div>
    </article>
  </section>
</body></html>
"""


class OnetTests(unittest.TestCase):
    def test_candidate_filters_keep_only_onet_news_articles(self):
        source = {
            "candidate_include_host_patterns": [r"^wiadomosci\.onet\.pl$"],
            "candidate_include_url_patterns": [r"^/(?:[^/]+/){2}[^/?#]+/?$"],
            "candidate_exclude_url_patterns": [r"^/(?:autorzy|wideo|podcast)(?:/|$)"],
        }

        self.assertTrue(st.candidate_allowed(source, ONET_URL, "Ważny artykuł"))
        self.assertFalse(st.candidate_allowed(source, "https://przegladsportowy.onet.pl/pilka-nozna/test/abc123", "Mecz"))
        self.assertFalse(st.candidate_allowed(source, "https://wiadomosci.onet.pl/autorzy/patrycja-klimek", "Patrycja Klimek"))
        self.assertFalse(st.candidate_allowed(source, "https://wiadomosci.onet.pl/swiat", "Świat"))

    def test_extracts_onet_metadata_and_body_without_modules(self):
        result = st.FetchResult(
            url=ONET_URL,
            status=200,
            final_url=ONET_URL,
            content_type="text/html",
            body=ONET_ARTICLE_HTML.encode("utf-8"),
        )

        extracted = st.extract_article(result, "https://www.onet.pl", include_body=True, source_id="onet")

        self.assertEqual(extracted["title"], "Tytuł artykułu Onetu")
        self.assertEqual(extracted["description"], "Lead Onetu o wydarzeniu.")
        self.assertEqual(extracted["author"], "Dziennikarze Onet Wiadomości, Patrycja Klimek")
        self.assertEqual(extracted["published_at"], "2026-09-29T05:50:22+0200")
        self.assertIn("Główny akapit", extracted["body"])
        self.assertNotIn("Udostępnij artykuł", extracted["body"])
        self.assertNotIn("Posłuchaj artykułu", extracted["body"])
        self.assertTrue(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
