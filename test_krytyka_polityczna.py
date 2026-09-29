import unittest

import source_tester as st


LISTING_HTML = """
<div class="entry-content">
  <div class="article article-main">
    <a href="https://krytykapolityczna.pl/kraj/jaroslaw-zabojstwo-ksiedza-ukraincy-reportaz/"><img src="cover.jpg"></a>
    <h2 class="article-content-title"><a href="https://krytykapolityczna.pl/kraj/jaroslaw-zabojstwo-ksiedza-ukraincy-reportaz/">Jarosław, jaki znam</a></h2>
  </div>
  <div class="now-reading"><a href="https://krytykapolityczna.pl/swiat/rosyjskie-memy/">Rosyjskie memy</a></div>
  <a href="https://krytykapolityczna.pl/temat/reportaz/">Reportaż</a>
  <a href="https://krytykapolityczna.pl/bio/piotr-wojcik/">Piotr Wójcik</a>
  <a href="https://krytykapolityczna.pl/wydawnictwo/katalog/">Katalog</a>
  <a href="https://krytykapolityczna.pl/kraj/jaroslaw-zabojstwo-ksiedza-ukraincy-reportaz/#komentarze">Komentarze</a>
</div>
"""

ARTICLE_HTML = """
<html><body>
  <article id="post-445922" class="post type-post">
    <h1 class="article-page-header-content-title">7 błędów polskiej komunikacji strategicznej</h1>
    <div class="article-single-author">
      <span class="article-single-author-name"><span itemprop="name">Piotr Wójcik</span></span>
    </div>
    <time datetime="2026-09-29T06:00:21+02:00">29.09.2026</time>
    <div class="entry-content article-page-content">
      <div class="article-page-info">1 29.09.2026</div>
      <div class="article-page-text">
        <p>W sytuacji rosnącego zagrożenia działania komunikacyjne państwa wymagają spójności, precyzji i odpowiedzialności. Ten wstęp opisuje najważniejszy problem artykułu.</p>
        <p>Komunikacja strategiczna służy wyjaśnianiu sojusznikom zamiarów, ostrzeganiu przeciwników i przygotowywaniu społeczeństwa na nadchodzące zdarzenia. Powinna być przejrzysta, logiczna i adekwatna do podejmowanych działań.</p>
        <div class="article-page-read-also"><p>Czytaj także Straszenie wojną</p></div>
        <h3>1. Brak spójności przekazu z działaniami</h3>
        <p>Trudno o większy błąd niż sytuacja, w której podejmowane działania nie odpowiadają alarmistycznemu tonowi. Taka niekonsekwencja osłabia zaufanie obywateli i sojuszników oraz utrudnia ocenę rzeczywistych zagrożeń.</p>
        <p>Politycy powinni przedstawiać cele jasno, unikać domysłów i pilnować, aby kolejne komunikaty nie pozostawały ze sobą w sprzeczności. W przeciwnym razie nawet trafne ostrzeżenia tracą wiarygodność. Odbiorcy muszą wiedzieć, co się wydarzyło, jakie są możliwe scenariusze i jakie działania należy podjąć.</p>
        <div class="line-label-slider-wrapper"><p>Za późno na przebudzenie</p></div>
        <div class="product-card"><p class="product-card-title">Książka promocyjna</p></div>
        <div class="donate-widget-container"><h2>Wspieraj nas</h2><p>Wpłacam</p></div>
      </div>
    </div>
  </article>
</body></html>
"""


class KrytykaPolitycznaTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "candidate_include_host_patterns": [r"^krytykapolityczna\.pl$"],
            "candidate_include_url_patterns": [r"^/[^/]+/[^/?#]+/?$"],
            "candidate_exclude_url_patterns": [
                r"^/(?:bio|temat|wydawnictwo|multimedia|o-nas|logowanie|wspieraj|sklep)(?:/|$)"
            ],
        }

    def test_listing_keeps_article_urls_and_rejects_site_modules(self):
        parser = st.PageParser()
        parser.feed(LISTING_HTML)
        accepted = {
            st.canonicalize(link["href"], "https://krytykapolityczna.pl")
            for link in parser.links
            if st.candidate_allowed(self.source, link["href"], link.get("text", ""))
        }

        self.assertIn(
            "https://krytykapolityczna.pl/kraj/jaroslaw-zabojstwo-ksiedza-ukraincy-reportaz/",
            accepted,
        )
        self.assertIn(
            "https://krytykapolityczna.pl/swiat/rosyjskie-memy/",
            accepted,
        )
        self.assertNotIn("https://krytykapolityczna.pl/temat/reportaz/", accepted)
        self.assertNotIn(
            "https://krytykapolityczna.pl/wydawnictwo/katalog/",
            accepted,
        )
        self.assertNotIn(
            "https://krytykapolityczna.pl/bio/piotr-wojcik/",
            accepted,
        )

    def test_article_extracts_clean_body_and_metadata(self):
        result = st.FetchResult(
            url="https://krytykapolityczna.pl/kraj/7-bledow-polskiej-komunikacji-strategicznej/",
            status=200,
            final_url="https://krytykapolityczna.pl/kraj/7-bledow-polskiej-komunikacji-strategicznej/",
            content_type="text/html",
            body=ARTICLE_HTML.encode("utf-8"),
        )
        extracted = st.extract_article(
            result,
            "https://krytykapolityczna.pl",
            include_body=True,
            source_id="krytyka_polityczna",
        )

        self.assertEqual(extracted["title"], "7 błędów polskiej komunikacji strategicznej")
        self.assertEqual(extracted["author"], "Piotr Wójcik")
        self.assertEqual(extracted["published_at"], "2026-09-29T06:00:21+02:00")
        self.assertIn("W sytuacji rosnącego zagrożenia", extracted["description"])
        self.assertIn("Brak spójności przekazu z działaniami", extracted["body"])
        self.assertNotIn("Czytaj także", extracted["body"])
        self.assertNotIn("Za późno na przebudzenie", extracted["body"])
        self.assertNotIn("Wspieraj nas", extracted["body"])
        self.assertGreater(extracted["word_count"], 100)
        self.assertTrue(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
