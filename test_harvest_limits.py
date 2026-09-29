import unittest

from article_harvester import effective_top_articles_limit


class HarvestLimitTests(unittest.TestCase):
    def test_polish_region_raises_standard_window_to_fifteen(self):
        self.assertEqual(
            effective_top_articles_limit({"region": "Poland"}, 10),
            15,
        )

    def test_polish_language_raises_standard_window_to_fifteen(self):
        self.assertEqual(
            effective_top_articles_limit({"region": "France", "language": "pl"}, 10),
            15,
        )

    def test_non_polish_source_keeps_window_at_ten(self):
        self.assertEqual(
            effective_top_articles_limit({"region": "USA"}, 10),
            10,
        )

    def test_explicit_nonstandard_window_is_preserved(self):
        self.assertEqual(
            effective_top_articles_limit({"region": "Poland"}, 8),
            8,
        )


if __name__ == "__main__":
    unittest.main()
