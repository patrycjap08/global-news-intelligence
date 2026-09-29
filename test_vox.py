import unittest

import source_tester as st


ARTICLE_URL = "https://www.vox.com/politics/504154/flock-cameras-crime-surveillance"

LISTING_HTML = """
<main id="content">
  <a href="/politics/504154/flock-cameras-crime-surveillance">Flock cameras are creepy. They might still be worth it.</a>
  <a href="/podcasts/504011/burnerverse-maddie-kowalski-online-harassment">The online burnerverse</a>
  <a href="/21523212/crossword-puzzles-free-daily-printable">Take a mental break with the newest Vox crossword</a>
  <a href="/politics/504188/college-football-reform">A football story that must not be harvested</a>
</main>
"""

ARTICLE_HTML = """
<article>
  <div class="duet--article--lede">
    <h1>Trump’s taxpayer-funded propaganda blitz</h1>
    <p>Trump is using your money on TV ads to stroke his ego.</p>
    <div class="duet--article--article-byline"><span>by <a href="/authors/cameron-peters">Cameron Peters</a></span></div>
    <time datetime="2026-09-28T22:10:00+00:00">Sep. 28, 2026</time>
  </div>
  <div class="duet--media--caption"><p>Image caption must not enter the body.</p></div>
  <div class="duet--article--article-body-component"><p><em>This story appeared in The Logoff, a daily newsletter. Subscribe here.</em></p></div>
  <div class="duet--article--article-body-component"><p><strong>Welcome to The Logoff:</strong> Donald Trump is spending taxpayer money on propaganda ads.</p></div>
  <div class="duet--article--article-body-component"><p><strong>What’s happening?</strong> The administration aired a spot promising to demolish the deep state and paired it with black-and-white footage of the president walking down a hallway.</p></div>
  <div class="duet--article--article-body-component"><p>For the final seconds of the ad, a line of white text appears on the screen saying it was paid for by the U.S. Government.</p></div>
  <div class="duet--article--article-body-component"><p><strong>What’s the context?</strong> Ethics experts say the campaign-style messages raise serious legal questions about the use of public money.</p></div>
  <section><h2>Most Popular</h2><p>This recommendation must not enter the body.</p></section>
  <form class="duet--cta--newsletter"><p>Newsletter signup must not enter the body.</p></form>
</article>
"""


class VoxTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "candidate_include_host_patterns": [r"^www\.vox\.com$"],
            "candidate_include_url_patterns": [r"^/[^/]+/[0-9]{4,}/[^/?#]+/?$"],
            "candidate_exclude_url_patterns": [r"^/(?:podcasts|video|videos|crossword|games)(?:/|$)"],
            "candidate_exclude_title_patterns": [r"\b(sport|sports|nfl|nba|mlb|nhl|ncaa|football|baseball|basketball|soccer|golf|tennis|olympics)\b"],
        }

    def test_listing_keeps_articles_and_rejects_podcasts_games_and_sports(self):
        parser = st.PageParser()
        parser.feed(LISTING_HTML)
        accepted = [
            st.canonicalize(link["href"], "https://www.vox.com")
            for link in parser.links
            if st.candidate_allowed(
                self.source,
                st.canonicalize(link["href"], "https://www.vox.com") or "",
                link.get("text", ""),
            )
        ]

        self.assertEqual(accepted, [ARTICLE_URL])

    def test_article_extracts_clean_vox_metadata_and_body(self):
        result = st.FetchResult(
            url=ARTICLE_URL,
            status=200,
            final_url=ARTICLE_URL,
            content_type="text/html",
            body=ARTICLE_HTML.encode("utf-8"),
        )
        extracted = st.extract_article(
            result,
            "https://www.vox.com",
            include_body=True,
            source_id="vox",
        )

        self.assertEqual(extracted["title"], "Trump’s taxpayer-funded propaganda blitz")
        self.assertEqual(extracted["author"], "Cameron Peters")
        self.assertEqual(extracted["published_at"], "2026-09-28T22:10:00+00:00")
        self.assertEqual(extracted["description"], "Trump is using your money on TV ads to stroke his ego.")
        self.assertIn("What’s happening?", extracted["body"])
        self.assertNotIn("This story appeared", extracted["body"])
        self.assertNotIn("Image caption", extracted["body"])
        self.assertNotIn("Most Popular", extracted["body"])
        self.assertNotIn("Newsletter signup", extracted["body"])
        self.assertTrue(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
