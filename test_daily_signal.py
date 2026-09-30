import unittest

import source_tester as st


ARTICLE_URL = "https://www.dailysignal.com/2026/09/29/election-2026-texas-ohio-virginia/"

LISTING_HTML = """
<main>
  <a href="/2026/09/29/election-2026-texas-ohio-virginia/">Inside the Key Races in Texas, Ohio, and Virginia</a>
  <a href="/2026/09/29/protect-college-football/">Football story that must not be harvested</a>
  <a href="/author/robert-bluey/">Robert B. Bluey</a>
  <a href="/podcast/2026/09/29/midterm-report/">Podcast episode</a>
</main>
"""

ARTICLE_HTML = """
<main>
  <div class="entry-content element-single-replace single-content">
    <div class="hero-interior article"><h1>On the Ground in 3 Key States: Latest From Texas, Ohio, and Virginia</h1><p><span class="ds-author-list"><a href="/author/robert-bluey/">Robert B. Bluey</a></span></p></div>
    <div class="wp-block-kadence-dynamichtml">
      <p>Virginia is one of the first states to open its polls, and I cast my ballot the day early voting began.</p>
      <p>There is a lot at stake this election year in the commonwealth, particularly proposed constitutional amendments on abortion and marriage.</p>
      <h2>Ohio: Two Toss-Ups in a Red State</h2>
      <p>State reporters are tracking policy debates and candidates who will determine the direction of the country in the coming years.</p>
      <p>Voters and officials said the campaign has become a test of whether local issues can break through national messaging.</p>
      <div class="ds-trending-articles"><p>Trending article must not enter the body.</p></div>
      <div class="author-box"><p>Author biography must not enter the body.</p></div>
      <div class="yarpp-related"><p>Related article must not enter the body.</p></div>
      <div class="newsletter-cta-row"><p>Newsletter signup must not enter the body.</p></div>
    </div>
  </div>
</main>
"""


class DailySignalTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "candidate_include_host_patterns": [r"^www\.dailysignal\.com$"],
            "candidate_include_url_patterns": [r"^/20[0-9]{2}/[0-9]{2}/[0-9]{2}/[^/?#]+/?$"],
            "candidate_exclude_url_patterns": [r"^/(?:author|category|tag|podcast|video|videos)(?:/|$)"],
            "candidate_exclude_title_patterns": [r"\b(sport|sports|nfl|nba|mlb|nhl|ncaa|football|baseball|basketball|soccer|golf|tennis|olympics)\b"],
        }

    def test_source_has_right_editorial_profile(self):
        self.assertEqual(st.infer_editorial_profile({"id": "daily_signal"}), "RIGHT")

    def test_listing_keeps_articles_and_rejects_sports_and_modules(self):
        parser = st.PageParser()
        parser.feed(LISTING_HTML)
        accepted = [
            st.canonicalize(link["href"], "https://www.dailysignal.com")
            for link in parser.links
            if st.candidate_allowed(
                self.source,
                st.canonicalize(link["href"], "https://www.dailysignal.com") or "",
                link.get("text", ""),
            )
        ]

        self.assertEqual(accepted, [ARTICLE_URL])

    def test_article_extracts_clean_daily_signal_body_and_metadata(self):
        result = st.FetchResult(
            url=ARTICLE_URL,
            status=200,
            final_url=ARTICLE_URL,
            content_type="text/html",
            body=ARTICLE_HTML.encode("utf-8"),
        )
        extracted = st.extract_article(
            result,
            "https://www.dailysignal.com",
            include_body=True,
            source_id="daily_signal",
        )

        self.assertEqual(extracted["title"], "On the Ground in 3 Key States: Latest From Texas, Ohio, and Virginia")
        self.assertEqual(extracted["author"], "Robert B. Bluey")
        self.assertIn("Virginia is one of the first", extracted["body"])
        self.assertIn("Ohio: Two Toss-Ups", extracted["body"])
        self.assertNotIn("Trending article", extracted["body"])
        self.assertNotIn("Author biography", extracted["body"])
        self.assertNotIn("Related article", extracted["body"])
        self.assertNotIn("Newsletter signup", extracted["body"])
        self.assertTrue(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
