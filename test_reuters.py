import unittest

import source_tester as st


ARTICLE_URL = (
    "https://www.reuters.com/business/finance/"
    "anthropic-warns-ai-may-pose-existential-risks-humanity-ipo-filing-2026-09-29/"
)

LISTING_HTML = """
<section data-testid="story-cluster">
  <a data-testid="TitleLink" href="/business/finance/anthropic-warns-ai-may-pose-existential-risks-humanity-ipo-filing-2026-09-29/">
    <span data-testid="TitleHeading">Anthropic warns AI may pose existential risks to humanity</span>
  </a>
  <a data-testid="TitleLink" href="/legal/transactional/anthropic-leaders-control-ai-lab-2026-09-29/">
    <span data-testid="TitleHeading">Anthropic leaders control AI lab</span>
  </a>
  <a data-testid="TitleLink" href="/podcasts/the-big-view/future-workers-ai-2026-09-29/">
    <span data-testid="TitleHeading">The right way to prepare future workers for AI</span>
  </a>
</section>
"""

ARTICLE_HTML = """
<article data-testid="Article">
  <header data-testid="DefaultArticleHeader">
    <h1 data-testid="Heading">Anthropic warns AI may pose existential risks to humanity</h1>
    <div data-testid="AuthorName"><a data-testid="AuthorNameLink">Echo Wang</a> and <a data-testid="AuthorNameLink">Aditya Soni</a></div>
    <time data-testid="DateLine" datetime="2026-09-29T02:34:52.563Z">September 29, 2026</time>
  </header>
  <div data-testid="ArticleBody">
    <div class="article-body-module__container__oOFyv">
      <div data-testid="ContextWidget"><ul><li>Summary should not enter the body</li></ul></div>
      <div data-testid="paragraph-0" class="article-body-module__paragraph__Ts-yF">Anthropic warned potential investors that advanced AI could pose severe risks if systems are deployed without adequate safeguards.</div>
      <div data-testid="paragraph-1" class="article-body-module__paragraph__Ts-yF">The filing describes how the company evaluates its models, manages safety concerns and plans to communicate those risks to investors.</div>
      <p data-testid="promo-box" class="article-body-module__promo-box__hVl8h">Subscribe to a newsletter.</p>
      <div data-testid="paragraph-2" class="article-body-module__paragraph__Ts-yF">Executives said the company will continue to invest in research, testing and measures that make model behavior more reliable.</div>
      <h2 class="article-body-module__heading__KTJKz">RISK-HEAVY DISCLOSURES</h2>
      <div data-testid="paragraph-3" class="article-body-module__paragraph__Ts-yF">The prospectus includes detailed discussion of risks, expected costs and uncertainty surrounding the commercial adoption of new technology.</div>
      <div data-testid="paragraph-4" class="article-body-module__paragraph__Ts-yF"><a href="/legal/transactional/related-2026-09-29/"><i>Exclusive: related article</i></a></div>
      <div data-testid="AuthorBio"><p>Reporter biography should not enter the body.</p></div>
    </div>
  </div>
</article>
"""


class ReutersTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "candidate_include_host_patterns": [r"^www\.reuters\.com$"],
            "candidate_include_url_patterns": [r"^/(?:[^/]+/)+[^/?#]+-20[0-9]{2}-[0-9]{2}-[0-9]{2}/?$"],
            "candidate_exclude_url_patterns": [r"^/(?:podcasts|video|videos|graphics|sports)(?:/|$)"],
        }

    def test_listing_keeps_news_titles_and_rejects_podcast(self):
        parser = st.PageParser()
        parser.feed(LISTING_HTML)
        accepted = [
            st.canonicalize(link["href"], "https://www.reuters.com")
            for link in parser.links
            if st.candidate_allowed(
                self.source,
                st.canonicalize(link["href"], "https://www.reuters.com") or "",
                link.get("text", ""),
            )
        ]

        self.assertEqual(len(accepted), 2)
        self.assertIn(ARTICLE_URL, accepted)
        self.assertNotIn(
            "https://www.reuters.com/podcasts/the-big-view/future-workers-ai-2026-09-29/",
            accepted,
        )

    def test_article_extracts_full_clean_reuters_body(self):
        result = st.FetchResult(
            url=ARTICLE_URL,
            status=200,
            final_url=ARTICLE_URL,
            content_type="text/html",
            body=ARTICLE_HTML.encode("utf-8"),
        )
        extracted = st.extract_article(
            result,
            "https://www.reuters.com",
            include_body=True,
            source_id="reuters",
        )

        self.assertEqual(extracted["title"], "Anthropic warns AI may pose existential risks to humanity")
        self.assertEqual(extracted["author"], "Echo Wang, Aditya Soni")
        self.assertEqual(extracted["published_at"], "2026-09-29T02:34:52.563Z")
        self.assertIn("Anthropic warned potential investors", extracted["description"])
        self.assertIn("RISK-HEAVY DISCLOSURES", extracted["body"])
        self.assertNotIn("Summary should not enter", extracted["body"])
        self.assertNotIn("Subscribe to a newsletter", extracted["body"])
        self.assertNotIn("Exclusive: related article", extracted["body"])
        self.assertNotIn("Reporter biography", extracted["body"])
        self.assertTrue(extracted["body_success"])


if __name__ == "__main__":
    unittest.main()
