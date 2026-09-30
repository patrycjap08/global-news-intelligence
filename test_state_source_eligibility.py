import unittest

from ai_pipeline import has_independent_source, is_state_source


class StateSourceEligibilityTests(unittest.TestCase):
    def test_state_aligned_sources_are_not_independent(self):
        self.assertTrue(is_state_source({"source_profile": "STATE_ALIGNED"}))
        self.assertTrue(is_state_source({"source_type": "STATE_MEDIA"}))
        self.assertFalse(is_state_source({"source_profile": "CENTER"}))
        self.assertFalse(has_independent_source([
            {"source_profile": "STATE_ALIGNED"},
            {"source_profile": "STATE_ALIGNED"},
        ]))

    def test_one_non_state_source_is_enough_for_coverage(self):
        self.assertTrue(has_independent_source([
            {"source_profile": "STATE_ALIGNED"},
            {"source_profile": "CENTER"},
        ]))


if __name__ == "__main__":
    unittest.main()
