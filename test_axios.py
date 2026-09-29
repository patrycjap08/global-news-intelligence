import unittest

import source_tester as st


ARTICLE_URL = "https://www.axios.com/2026/09/28/trump-iran-war-sanctions-blockade-nuclear"

LISTING_HTML = """
<main id="main-content">
  <a data-cy="top-table-story-headline" href="/2026/09/28/trump-iran-war-sanctions-blockade-nuclear">Trump offers Iran economic relief for concrete nuclear concessions</a>
  <a href="/2026/09/29/protect-college-sports-act-nil-senate">Senate considers Protect College Sports Act</a>
  <a href="/authors/barak_ravid">Barak Ravid</a>
</main>
"""

ARTICLE_HTML = """
<main id="main-content">
  <h1 data-cy="story-headline">Trump offers Iran economic relief for concrete nuclear concessions</h1>
  <a data-cy="byline-author" href="/authors/barak_ravid">Barak Ravid</a>
  <div data-cy="story-body">
    <span data-schema="smart-brevity">
      <p>President Trump is willing to give Iran sanctions relief and release frozen funds in return for concrete steps regarding the nuclear program, officials say.</p>
      <ul><li>But Trump later said reports of such an offer were untrue.</li></ul>
      <p><strong>Why it matters:</strong> Mediators are trying again this week to strike a deal between the two warring countries while their positions remain far apart.</p>
    </span>
    <div id="piano-container" data-piano-active="true">Subscription wall</div>
    <span data-cy="story-go-deeper-content" class="gated-content"><p>Subscription-gated continuation must not be collected.</p></span>
    <ul data-cy="social-share-bottom"><li>Email</li></ul>
  </div>
</main>
"""


class AxiosTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "candidate_include_host_patterns": [r"^www\.axios\.com$"],
            "candidate_include_url_patterns": [r"^/20[0-9]{2}/[0-9]{2}/[0-9]{2}/[^/?#]+/?$"],
            "candidate_exclude_url_patterns": [r"^/20[0-9]{2}/[0-9]{2}/[0-9]{2}/[^/?#]*(?:sports?|nfl|nba|mlb|nhl|ncaa|football|baseball|basketball|soccer|golf|tennis|olympics|nil)[^/?#]*/?$"],
            "candidate_exclude_title_patterns": [r"\b(sport|sports|nfl|nba|mlb|nhl|ncaa|football|baseball|basketball|soccer|golf|tennis|olympics|nil)\b"],
        }

    def test_listing_keeps_news_and_rejects_sports_and_authors(self):
        parser = st.PageParser()
        parser.feed(LISTING_HTML)
        accepted = [
            st.canonicalize(link["href"], "https://www.axios.com")
            for link in parser.links
            if st.candidate_allowed(
                self.source,
                st.canonicalize(link["href"], "https://www.axios.com") or "",
                link.get("text", ""),
            )
        ]

        self.assertEqual(accepted, [ARTICLE_URL])

    def test_article_extracts_accessible_body_without_gated_continuation(self):
        result = st.FetchResult(
            url=ARTICLE_URL,
            status=200,
            final_url=ARTICLE_URL,
            content_type="text/html",
            body=ARTICLE_HTML.encode("utf-8"),
        )
        extracted = st.extract_article(
            result,
            "https://www.axios.com",
            include_body=True,
            source_id="axios",
        )

        self.assertEqual(extracted["title"], "Trump offers Iran economic relief for concrete nuclear concessions")
        self.assertEqual(extracted["author"], "Barak Ravid")
        self.assertEqual(extracted["published_at"], "2026-09-28")
        self.assertIn("President Trump is willing", extracted["description"])
        self.assertIn("Why it matters:", extracted["body"])
        self.assertNotIn("Subscription-gated continuation", extracted["body"])
        self.assertNotIn("Email", extracted["body"])
        self.assertTrue(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
