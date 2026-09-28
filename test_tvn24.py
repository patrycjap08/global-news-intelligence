import unittest
from types import SimpleNamespace

import source_tester as st
from article_harvester import _listing_rows, fetch_one


TVN24_URL = "https://tvn24.pl/polska/przykladowy-tytul-st9259408"
TVN24_HTML = """
<html>
  <head>
    <meta name="description" content="Lead artykułu TVN24." />
    <meta property="og:title" content="Przykładowy tytuł TVN24" />
    <link rel="canonical" href="https://tvn24.pl/polska/przykladowy-tytul-st9259408" />
  </head>
  <body>
    <main class="_left-column_example">
      <header><h1>Przykładowy tytuł TVN24</h1>
        <a href="https://tvn24.pl/autorzy/example"><img alt="Autorka Testowa" /></a>
        <a href="https://tvn24.pl/autorzy/example">Autorka Testowa</a>
        <time datetime="2026-09-28T14:57:20.000Z">28.09.2026, 16:57</time>
      </header>
      <strong class="Lead">To jest lead artykułu, który powinien zostać zachowany w pełnym body.</strong>
      <div class="ad-ph">Reklama nie jest treścią.</div>
      <yennefer-island><ul><li>Pierwszy kluczowy fakt pozostający częścią materiału.</li></ul></yennefer-island>
      <p>Pierwszy akapit opisuje najważniejsze fakty i kontekst wydarzenia przedstawionego w materiale.</p>
      <h2>Śródtytuł artykułu</h2>
      <p>Drugi akapit rozwija temat, podaje dane i wyjaśnia, co wydarzyło się według dostępnych informacji.</p>
      <div><h3>DOWIEDZ SIĘ WIĘCEJ:</h3><a href="/polska/inny-material-st123">Powiązany materiał</a></div>
      <div><h3>ZOBACZ TAKŻE:</h3><a href="/plus/program-vc123">Materiał premium</a></div>
      <div class="_article-attribution_"><p>Źródło: tvn24.pl</p><p>Autorka/Autor: Autorka Testowa</p></div>
    </main>
  </body>
</html>
"""

TVN24_SECTION_HTML = """
<main>
  <div class="SectionTeaser">
    <a href="https://tvn24.pl/swiat/pierwszy-material-st9259408" title="Pierwszy materiał">
      <span>Pierwszy materiał</span>
    </a>
  </div>
  <div class="SectionTeaser">
    <a href="https://tvn24.pl/tvnmeteo/swiat/ostrzezenia-imgw-st9259409" title="Ostrzeżenia IMGW">
      <span>Ostrzeżenia IMGW</span>
    </a>
  </div>
  <div class="SectionTeaser">
    <a href="https://eurosport.tvn24.pl/pilka/story_sto23340781/story.shtml" title="Mecz">
      <span>Mecz</span>
    </a>
  </div>
  <div class="SectionTeaser">
    <a href="https://tvn24.pl/plus/programy/test-vc9259410" title="Materiał premium">
      <span>Materiał premium</span>
    </a>
  </div>
</main>
"""


class FakeClient:
    def get(self, url):
        return st.FetchResult(
            url=url,
            status=200,
            final_url=url,
            content_type="text/html",
            body="<main><h1>Redakcja poleca:</h1><p>Za krótka odpowiedź.</p></main>".encode("utf-8"),
        )


class FakeSectionClient:
    def get(self, url, accept=None):
        return st.FetchResult(
            url=url,
            status=200,
            final_url=url,
            content_type="text/html",
            body=TVN24_SECTION_HTML.encode("utf-8"),
        )


class FakePage:
    def __init__(self):
        self.url = TVN24_URL

    def goto(self, url, wait_until, timeout):
        self.url = url
        return SimpleNamespace(status=200)

    def content(self):
        return TVN24_HTML


class TVN24Tests(unittest.TestCase):
    def test_section_discovery_keeps_only_tvn24_story_teasers(self):
        source = {
            "id": "tvn24",
            "homepage": "https://tvn24.pl",
            "discover_homepage": False,
            "section_urls": ["https://tvn24.pl/swiat", "https://tvn24.pl/polska"],
            "candidate_pool_per_section": 30,
            "candidate_include_host_patterns": [r"^tvn24\.pl$"],
            "candidate_include_url_patterns": [r"^/(?:[^/]+/)+[^/]+-st[0-9]+/?$"],
            "candidate_exclude_url_patterns": [r"/(?:tvnmeteo|plus|programy)(?:/|$)"],
        }

        rows, homepage_result, notes = _listing_rows(FakeSectionClient(), source)

        self.assertEqual(homepage_result.status, 200)
        self.assertEqual([row["url"] for row in rows], [
            "https://tvn24.pl/swiat/pierwszy-material-st9259408",
        ])
        self.assertEqual(len(notes), 1)

    def test_extracts_metadata_and_body_without_related_modules(self):
        result = st.FetchResult(
            url=TVN24_URL,
            status=200,
            final_url=TVN24_URL,
            content_type="text/html",
            body=TVN24_HTML.encode("utf-8"),
        )

        extracted = st.extract_article(result, "https://tvn24.pl", include_body=True, source_id="tvn24")

        self.assertEqual(extracted["title"], "Przykładowy tytuł TVN24")
        self.assertEqual(extracted["description"], "Lead artykułu TVN24.")
        self.assertEqual(extracted["author"], "Autorka Testowa")
        self.assertEqual(extracted["published_at"], "2026-09-28T14:57:20.000Z")
        self.assertEqual(extracted["url"], TVN24_URL)
        self.assertIn("To jest lead artykułu", extracted["body"])
        self.assertIn("Pierwszy kluczowy fakt", extracted["body"])
        self.assertNotIn("Powiązany materiał", extracted["body"])
        self.assertNotIn("Materiał premium", extracted["body"])
        self.assertTrue(extracted["body_success"])

    def test_filters_tv24_article_urls_and_titles(self):
        source = {
            "candidate_include_host_patterns": [r"^tvn24\.pl$"],
            "candidate_include_url_patterns": [r"^/(?:[^/]+/)+[^/]+-st[0-9]+/?$"],
            "candidate_exclude_title_patterns": [r"\b(sport|mecz|IMGW|pogoda)\b"],
        }

        self.assertTrue(st.candidate_allowed(source, TVN24_URL, "Ważne informacje"))
        self.assertFalse(st.candidate_allowed(source, "https://eurosport.tvn24.pl/pilka/story_sto123/story.shtml", "Ważne informacje"))
        self.assertFalse(st.candidate_allowed(source, "https://tvn24.pl/polska/material-vc123", "Ważne informacje"))
        self.assertFalse(st.candidate_allowed(source, TVN24_URL, "Mecz reprezentacji"))
        self.assertFalse(st.candidate_allowed(source, TVN24_URL, "Ostrzeżenia IMGW"))

    def test_browser_is_used_when_runtime_marks_tvn24_as_browser_source(self):
        http_extracted = st.extract_article(
            FakeClient().get(TVN24_URL),
            "https://tvn24.pl",
            source_id="tvn24",
        )
        self.assertEqual(http_extracted["title"], "")

        extracted, method = fetch_one(
            FakeClient(),
            FakePage(),
            {"id": "tvn24", "homepage": "https://tvn24.pl", "content_method": "BROWSER"},
            TVN24_URL,
            browser_enabled=True,
        )

        self.assertEqual(method, "BROWSER")
        self.assertEqual(extracted["title"], "Przykładowy tytuł TVN24")
        self.assertTrue(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
