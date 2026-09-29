import unittest

from ai_pipeline import (
    GROUPING_INSTRUCTIONS,
    build_topic_merge_candidate_groups,
    build_topic_merge_requests,
    is_article_title_copy,
)


class TopicTitleTests(unittest.TestCase):
    def test_detects_verbatim_article_title_even_with_geo_prefix(self):
        article_title = "Nie uwierzycie, co Trump powiedział w swoim dzisiejszym wystąpieniu"
        self.assertTrue(is_article_title_copy(f"[USA] {article_title}", [article_title]))

    def test_accepts_editorial_topic_label_instead_of_article_title(self):
        article_title = "Nie uwierzycie, co Trump powiedział w swoim dzisiejszym wystąpieniu"
        self.assertFalse(is_article_title_copy("[USA] Dzisiejsze wystąpienie Trumpa", [article_title]))

    def test_grouping_prompt_requires_abstraction_for_singletons(self):
        self.assertIn("dotyczy to także grup jednoartykułowych", GROUPING_INSTRUCTIONS)
        self.assertIn("Dzisiejsze wystąpienie Trumpa", GROUPING_INSTRUCTIONS)

    def test_local_merge_filter_keeps_only_plausible_candidates(self):
        topics = [
            {
                "topic_id": "topic_a",
                "headline_pl": "[USA] Wystąpienie Trumpa",
                "what_happened_one_sentence_pl": "Trump mówił o nowych sankcjach wobec Iranu.",
                "recent_article_titles": ["Trump zapowiedział sankcje wobec Iranu"],
            },
            {
                "topic_id": "topic_b",
                "headline_pl": "[USA i Iran] Trump zapowiada sankcje wobec Iranu",
                "what_happened_one_sentence_pl": "Prezydent USA zapowiedział nowe sankcje.",
                "recent_article_titles": ["Nowe sankcje USA wobec Iranu po wystąpieniu Trumpa"],
            },
            {
                "topic_id": "topic_c",
                "headline_pl": "[Polska] Ceny paliw spadają",
                "what_happened_one_sentence_pl": "Stacje obniżają ceny benzyny.",
                "recent_article_titles": ["Benzyna tańsza na stacjach"],
            },
        ]
        self.assertEqual(
            build_topic_merge_candidate_groups(topics),
            [["topic_a", "topic_b"]],
        )
        request_topics = build_topic_merge_requests(topics)
        self.assertEqual(
            [topic["topic_id"] for topic in request_topics[0]],
            ["topic_a", "topic_b"],
        )
        self.assertEqual(
            {topic["candidate_group_id"] for topic in request_topics[0]},
            {"local_1"},
        )


if __name__ == "__main__":
    unittest.main()
