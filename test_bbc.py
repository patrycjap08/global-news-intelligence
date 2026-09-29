import unittest

import source_tester as st


ARTICLE_URL = "https://www.bbc.com/news/articles/cm5y5nynl75ko"

LISTING_HTML = """
<main id="bbc-main">
  <a href="/news/articles/cm5y5nynl75ko">OpenAI scraps rollout of new model over safety concerns</a>
  <a href="/news/live/c65y7nl29k0et">Live updates that must not be harvested</a>
  <a href="/news/videos/c6lymekx0repo">Video that must not be harvested</a>
  <a href="/sport/football/articles/ckz7zxzdwl7lo">Football result that must not be harvested</a>
</main>
"""

ARTICLE_HTML = """
<main id="bbc-main">
  <article>
    <div data-component="headline-block"><h1>OpenAI scraps rollout of new model over safety concerns</h1></div>
    <div data-component="byline-block">
      <div data-testid="byline-contributors"><div data-testid="byline-contributors-contributor-0"><div><span class="AuthorName">Osmond Chia</span><span data-testid="byline-contributors-contributor-0-role-location">Business reporter</span></div></div></div>
      <time datetime="2026-09-29T04:30:13.730Z">3 hours ago</time>
    </div>
    <div data-component="image-block"><figure><figcaption>Image caption must not enter the body.</figcaption></figure></div>
    <div data-component="layout-block">
      <p>OpenAI will not release its new AI model due to safety concerns, the company confirmed on Tuesday.</p>
      <p>The AI system did not meet the company’s standards for scope, authorisation and communication with users.</p>
      <h2>Australia hacks</h2>
      <p>Recent incidents have intensified the debate around the risks posed by advanced technology and autonomous agents.</p>
      <p>Officials said better safeguards and clearer disclosure procedures are needed before systems are widely deployed.</p>
      <p>Researchers called for companies to test new products carefully and inform affected organisations promptly.</p>
      <p>Get our flagship newsletter with all the headlines you need to start the day. Sign up here.</p>
      <div data-testid="links-grid"><p>Related card must not enter the body.</p></div>
    </div>
    <div data-component="tag-list-block">Artificial intelligence</div>
  </article>
</main>
"""


class BBCTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "candidate_include_host_patterns": [r"^(?:www\.)?bbc\.com$"],
            "candidate_include_url_patterns": [r"^/news/articles/[a-z0-9]+/?$"],
            "candidate_exclude_title_patterns": [r"\b(sport|sports|football|rugby|cricket|tennis|golf|formula 1|f1|olympics)\b"],
        }

    def test_listing_keeps_bbc_news_articles_only(self):
        parser = st.PageParser()
        parser.feed(LISTING_HTML)
        accepted = [
            st.canonicalize(link["href"], "https://www.bbc.com")
            for link in parser.links
            if st.candidate_allowed(
                self.source,
                st.canonicalize(link["href"], "https://www.bbc.com") or "",
                link.get("text", ""),
            )
        ]

        self.assertEqual(accepted, [ARTICLE_URL])

    def test_article_extracts_clean_bbc_metadata_and_body(self):
        result = st.FetchResult(
            url=ARTICLE_URL,
            status=200,
            final_url=ARTICLE_URL,
            content_type="text/html",
            body=ARTICLE_HTML.encode("utf-8"),
        )
        extracted = st.extract_article(
            result,
            "https://www.bbc.com",
            include_body=True,
            source_id="bbc",
        )

        self.assertEqual(extracted["title"], "OpenAI scraps rollout of new model over safety concerns")
        self.assertEqual(extracted["author"], "Osmond Chia")
        self.assertEqual(extracted["published_at"], "2026-09-29T04:30:13.730Z")
        self.assertIn("OpenAI will not release", extracted["description"])
        self.assertIn("Australia hacks", extracted["body"])
        self.assertNotIn("Image caption", extracted["body"])
        self.assertNotIn("flagship newsletter", extracted["body"])
        self.assertNotIn("Related card", extracted["body"])
        self.assertTrue(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
