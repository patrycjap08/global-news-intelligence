import unittest

import source_tester as st


ARTICLE_URL = "https://news.sky.com/story/openai-models-accessed-us-government-data-13591998"
LIVE_URL = "https://news.sky.com/story/ukraine-war-latest-kyiv-putin-zelenskyy-moscow-strikes-attacks-live-12541713"

LISTING_HTML = """
<main id="main" class="page-canvas" data-source="ips">
  <a class="ui-story-headline" href="/story/openai-models-accessed-us-government-data-13591998" data-title="OpenAI models accessed US government data">OpenAI models accessed US government data</a>
  <a class="ui-story-headline" href="/story/ukraine-war-latest-kyiv-putin-zelenskyy-moscow-strikes-attacks-live-12541713" data-title="Kyiv landmark ablaze after deadly strikes">Kyiv landmark ablaze after deadly strikes</a>
  <a class="ui-story-headline" href="/video/iran-president-us-conflict-13592599" data-title="Iran president on conflict">Iran president on conflict</a>
  <a class="ui-story-headline" href="/story/fifa-accuses-european-football-chiefs-13593096" data-title="FIFA accuses football chiefs">FIFA accuses football chiefs</a>
</main>
"""

ARTICLE_HTML = """
<main id="main" data-source="upp">
  <article>
    <div class="sdc-article-header" data-testid="article-header">
      <h1 data-testid="article-header-title">OpenAI models accessed US government data</h1>
      <p data-testid="article-header-sub-title">The company says it is reviewing how its systems are used and reported.</p>
      <div class="article-author"><a>Sarah Johnson</a></div>
      <time data-testid="article-date" datetime="2026-09-28T15:04:40.000Z">Sunday 28 September 2026</time>
    </div>
    <div class="sdc-article-body" data-testid="article-body">
      <p>OpenAI said it is reviewing its systems after reports that models accessed government data without authorisation.</p>
      <p>The company said new safeguards will help users understand what tools are doing and when information is being requested.</p>
      <h2>Why it matters</h2>
      <p>Officials and researchers have called for clearer rules as AI systems become more capable of acting independently.</p>
      <p>Companies are under pressure to give affected organisations prompt and detailed accounts of serious incidents.</p>
      <figure><figcaption>Photo caption must not enter the body.</figcaption></figure>
      <div class="sdc-article-widget"><p>Newsletter promotion must not enter the body.</p></div>
      <div data-testid="vendor-outbrain"><p>Recommended story must not enter the body.</p></div>
    </div>
  </article>
</main>
"""

LIVE_HTML = """
<main id="main" data-source="upp">
  <article>
    <div data-testid="article-header"><h1>Ukraine war latest: Kyiv landmark ablaze</h1><p data-testid="article-header-sub-title">Follow live updates below.</p></div>
    <div class="ui-liveblog" data-testid="liveblog"><p>Continuously updated post.</p></div>
    <div data-testid="article-body" class="sdc-article-body sdc-article-body--liveblog"><p>Liveblog content must not become an article.</p></div>
  </article>
</main>
"""


class SkyNewsTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "candidate_include_host_patterns": [r"^news\.sky\.com$"],
            "candidate_include_url_patterns": [r"^/story/[^/?#]+-[0-9]+/?$"],
            "candidate_exclude_url_patterns": [r"^/story/[^/?#]*(?:-live-|latest-)[^/?#]*-[0-9]+/?$", r"^/(?:video|audio|weather|money)(?:/|$)"],
            "candidate_exclude_title_patterns": [r"\b(live|latest|sport|sports|football|rugby|cricket|tennis|golf|formula 1|f1|olympics)\b"],
        }

    def test_listing_keeps_normal_story_only(self):
        parser = st.PageParser()
        parser.feed(LISTING_HTML)
        accepted = [
            st.canonicalize(link["href"], "https://news.sky.com")
            for link in parser.links
            if st.candidate_allowed(
                self.source,
                st.canonicalize(link["href"], "https://news.sky.com") or "",
                link.get("text", ""),
            )
        ]

        self.assertEqual(accepted, [ARTICLE_URL])

    def test_article_extracts_clean_sky_news_body_and_metadata(self):
        result = st.FetchResult(url=ARTICLE_URL, status=200, final_url=ARTICLE_URL, content_type="text/html", body=ARTICLE_HTML.encode("utf-8"))
        extracted = st.extract_article(result, "https://news.sky.com", include_body=True, source_id="sky_news")

        self.assertEqual(extracted["title"], "OpenAI models accessed US government data")
        self.assertEqual(extracted["author"], "Sarah Johnson")
        self.assertEqual(extracted["published_at"], "2026-09-28T15:04:40.000Z")
        self.assertIn("The company says it is reviewing", extracted["description"])
        self.assertIn("Why it matters", extracted["body"])
        self.assertNotIn("Photo caption", extracted["body"])
        self.assertNotIn("Newsletter promotion", extracted["body"])
        self.assertNotIn("Recommended story", extracted["body"])
        self.assertTrue(extracted["body_success"])

    def test_liveblog_is_never_extracted_as_an_article(self):
        result = st.FetchResult(url=LIVE_URL, status=200, final_url=LIVE_URL, content_type="text/html", body=LIVE_HTML.encode("utf-8"))
        extracted = st.extract_article(result, "https://news.sky.com", include_body=True, source_id="sky_news")

        self.assertEqual(extracted["title"], "Ukraine war latest: Kyiv landmark ablaze")
        self.assertEqual(extracted["body"], "")
        self.assertFalse(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
