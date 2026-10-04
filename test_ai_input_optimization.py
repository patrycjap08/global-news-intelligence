from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import ai_pipeline as ai


def article(article_id):
    return {
        "article_id": article_id, "title": f"Tytuł {article_id}",
        "body": f"Pełna treść {article_id}. " * 400,
        "source_id": article_id, "source_name": f"Źródło {article_id}",
        "original_language": "pl", "canonical_url": f"https://example.test/{article_id}",
    }


class AIInputOptimizationTests(unittest.TestCase):
    def test_first_summary_sends_each_full_body_once_and_keeps_subset_ids(self):
        old, new, missing = [article(value) for value in ("old", "new", "missing")]
        outdated = {**new, "body": "Nieaktualna kopia."}
        rows = [old, outdated, old]
        batch = [new, missing, new]
        original = deepcopy((rows, batch))
        payload, size, mode = ai.build_bounded_summary_input(
            {"previous_aggregation": None}, batch, rows,
        )
        self.assertNotIn("new_articles", payload)
        self.assertEqual(payload["new_article_ids"], ["new", "missing"])
        self.assertEqual([row["article_id"] for row in payload["all_articles"]],
                         ["old", "new", "missing"])
        self.assertEqual([row["body_original"] for row in payload["all_articles"]],
                         [old["body"], new["body"], missing["body"]])
        self.assertEqual(mode, "pełne treści")
        self.assertEqual(size, len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
        self.assertEqual((rows, batch), original)

    def test_deduplication_avoids_unnecessary_excerpt_fallback(self):
        rows = [article("one"), article("two")]
        rendered = [ai.article_for_ai(row) for row in rows]
        single_size = len(json.dumps({"all_articles": rendered, "new_article_ids": ["one", "two"]},
                                     ensure_ascii=False, separators=(",", ":")))
        with patch.object(ai, "SUMMARY_MAX_PAYLOAD_CHARS", single_size + 10):
            payload, size, mode = ai.build_bounded_summary_input({}, rows, rows)
        self.assertEqual(mode, "pełne treści")
        self.assertEqual(size, single_size)
        self.assertEqual(payload["all_articles"][1]["body_original"], rows[1]["body"])

    def test_updates_keep_new_articles_payload(self):
        rows = [article("new")]
        context = {"base_summary": {"summary_pl": "Synteza."}, "prior_updates": []}
        payload, _, mode = ai.build_bounded_summary_input({"previous_aggregation": context}, rows)
        self.assertEqual(payload["new_articles"], [ai.article_for_ai(rows[0])])
        self.assertNotIn("all_articles", payload)
        self.assertNotIn("new_article_ids", payload)
        self.assertEqual(mode, "pełne treści")

    def test_both_update_calls_receive_complete_history_without_old_audits(self):
        stored = {
            "base_summary": {"summary_pl": "Cała synteza.",
                             "facts": [{"text_pl": "Znany fakt.", "article_ids": ["old"]}]},
            "updates": [
                {"status": "NEW_INFORMATION", "new_information_pl": "Pierwsza aktualizacja.",
                 "new_article_ids": ["old1"], "generated_at": "2026-10-01T12:00:00Z",
                 "novelty_audit": {"candidate_facts": [{"text_pl": "Odrzucona propozycja."}]}},
                {"status": "NEW_INFORMATION", "new_information_pl": "Druga aktualizacja.",
                 "what_changed_pl": "Korekta liczby.", "novelty_audit": {"verdicts": []}},
            ],
        }
        original = deepcopy(stored)
        context = ai.previous_aggregation_context(stored)
        expected = deepcopy(stored)
        for update in expected["updates"]:
            update.pop("novelty_audit")
        self.assertEqual(context, {"base_summary": expected["base_summary"],
                                   "prior_updates": expected["updates"]})
        payload, _, _ = ai.build_bounded_summary_input({"previous_aggregation": context}, [article("new")])
        with patch.object(ai, "call_openai", side_effect=[
            {"facts": [{"text_pl": "Nowy fakt.", "article_ids": ["new"], "why_new_pl": "Nowe ustalenie."}]},
            {"verdicts": {"0": {"keep": True, "reason_pl": "Nie występuje w historii."}}},
        ]) as model:
            result = ai.generate_summary_response(payload, "test-model")
        self.assertEqual(model.call_count, 2)
        for call in model.call_args_list:
            self.assertEqual(call.args[1]["previous_aggregation"], context)
        self.assertEqual(stored, original)

        class Client:
            def __init__(self):
                self.saved = {}

            def upsert(self, table, rows, **kwargs):
                self.saved[table] = deepcopy(rows)

        client = Client()
        ai.persist_summary(client, topic_id="topic", run_id="run", model="test-model",
                           summary=result, summary_hash="hash",
                           previous_row={"summary": stored, "version": 2}, new_article_ids=["new"])
        saved = client.saved["topic_summaries"][0]["summary"]
        self.assertEqual(saved["updates"][:2], original["updates"])
        self.assertIn("novelty_audit", saved["updates"][-1])
        self.assertEqual(client.saved["topic_summary_versions"][0]["summary"], saved)
        self.assertEqual(stored, original)

    def test_legacy_update_context_also_preserves_text_without_audit(self):
        stored = {"base_summary": {"summary_pl": "Baza."},
                  "latest_update": {"new_information_pl": "Starsza aktualizacja.",
                                    "novelty_audit": {"verdicts": []}}}
        context = ai.previous_aggregation_context(stored)
        self.assertEqual(context["prior_updates"], [{"new_information_pl": "Starsza aktualizacja."}])
        self.assertIn("novelty_audit", stored["latest_update"])


if __name__ == "__main__":
    unittest.main()
