import unittest

import source_tester as st


ARTICLE_URL = (
    "https://www.washingtonpost.com/politics/2026/09/28/"
    "iowa-republicans-feel-heat-try-motivate-frustrated-base/"
)

LISTING_HTML = """
<div class="multi-table-chain hpgrid-max-width ma-auto">
  <a data-pb-local-content-field="web_headline" href="/politics/2026/09/28/iowa-republicans-feel-heat-try-motivate-frustrated-base/">
    In Iowa, Republicans feel the heat and try to motivate a frustrated base
  </a>
  <a data-pb-local-content-field="web_headline" href="/technology/interactive/2026/09/28/a-new-technology-story/">
    A technology story with an interactive presentation
  </a>
  <div data-link-group="opinions">
    <a href="/opinions/interactive/2026/09/28/future-british-prime-minister-travels-through-antebellum-america/">
      An opinion that must not be harvested
    </a>
  </div>
  <a href="/sports/2026/09/28/a-sports-story/">A sports story that must not be harvested</a>
</div>
"""

ARTICLE_HTML = """
<article class="grid-article mb-xxl-ns" data-qa="main">
  <header>
    <h1 data-qa="headline">In Iowa, Republicans feel the heat and try to motivate ‘frustrated’ base</h1>
    <span data-qa="author-byline">By <a rel="author">Liz Goodwin</a></span>
    <time datetime="2026-09-28T10:00:01.000Z">September 28, 2026</time>
  </header>
  <div class="meteredContent">
    <div class="article-body type-text" data-qa="article-body"><p>WEST DES MOINES, Iowa — Sen. Chuck Grassley has heard the frustration from voters and says Republicans need to explain how their agenda addresses it.</p></div>
    <div class="article-body type-text" data-qa="article-body"><p>“I don’t plan on dying in office,” Grassley said, while describing why the party is trying to reconnect with its base before the next election.</p></div>
    <div class="article-footer"><p>Footer promotion must not enter the body.</p></div>
    <div class="comments"><p>Comments must not enter the body.</p></div>
  </div>
</article>
"""


class WashingtonPostTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "candidate_include_host_patterns": [r"^www\.washingtonpost\.com$"],
            "candidate_include_url_patterns": [
                r"^/(?!opinions/)(?:[^/]+/)*20[0-9]{2}/[0-9]{2}/[0-9]{2}/[^/?#]+/?$"
            ],
            "candidate_exclude_url_patterns": [
                r"^/(?:opinions|sports|video|videos|podcasts|graphics)(?:/|$)"
            ],
        }

    def test_listing_rejects_opinions_and_sports(self):
        parser = st.PageParser()
        parser.feed(LISTING_HTML)
        accepted = [
            st.canonicalize(link["href"], "https://www.washingtonpost.com")
            for link in parser.links
            if st.candidate_allowed(
                self.source,
                st.canonicalize(link["href"], "https://www.washingtonpost.com") or "",
                link.get("text", ""),
            )
        ]

        self.assertEqual(len(accepted), 2)
        self.assertIn(ARTICLE_URL, accepted)
        self.assertIn(
            "https://www.washingtonpost.com/technology/interactive/2026/09/28/a-new-technology-story/",
            accepted,
        )
        self.assertNotIn(
            "https://www.washingtonpost.com/opinions/interactive/2026/09/28/future-british-prime-minister-travels-through-antebellum-america/",
            accepted,
        )

    def test_article_extracts_clean_body_and_metadata(self):
        result = st.FetchResult(
            url=ARTICLE_URL,
            status=200,
            final_url=ARTICLE_URL,
            content_type="text/html",
            body=ARTICLE_HTML.encode("utf-8"),
        )
        extracted = st.extract_article(
            result,
            "https://www.washingtonpost.com",
            include_body=True,
            source_id="washington_post",
        )

        self.assertEqual(extracted["title"], "In Iowa, Republicans feel the heat and try to motivate ‘frustrated’ base")
        self.assertEqual(extracted["author"], "Liz Goodwin")
        self.assertEqual(extracted["published_at"], "2026-09-28T10:00:01.000Z")
        self.assertIn("WEST DES MOINES, Iowa", extracted["description"])
        self.assertIn("WEST DES MOINES, Iowa", extracted["body"])
        self.assertNotIn("Footer promotion", extracted["body"])
        self.assertNotIn("Comments must not", extracted["body"])
        self.assertTrue(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
