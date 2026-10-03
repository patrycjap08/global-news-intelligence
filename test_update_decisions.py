from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import ai_pipeline as ai
from test_topic_titles import FakeMergeClient


def previous_row():
    base = {"summary_pl": "Pierwotna synteza.", "facts": [{"text_pl": "Znany fakt.", "article_ids": ["old"]}]}
    updates = [{"is_update": True, "new_information_pl": f"Wcześniejsze ustalenie {i}.",
                "new_article_ids": [f"old{i}"], "run_id": f"run{i}", "generated_at": f"2026-10-01T0{i}:00:00+00:00"}
               for i in (1, 2)]
    return {"topic_id": "topic", "version": 3, "updated_at": "2026-10-01T12:00:00+00:00", "input_hash": "old",
            "summary": {"base_summary": base, "updates": updates, "latest_update": deepcopy(updates[-1])}}


class UpdateDecisionTests(unittest.TestCase):
    def test_confirmation_only_is_rejected_even_when_model_claims_new_information(self):
        for text in (
            "Kolejne artykuły potwierdzają wcześniejsze dane.",
            "Nowe źródła potwierdzają wcześniejsze ustalenia o proteście.",
            "Artykuły potwierdzają znane fakty. Nowe materiały potwierdzają dotychczasowe informacje.",
        ):
            with self.subTest(text=text):
                response = {"update": {"status": "NEW_INFORMATION", "new_information_pl": text}}
                self.assertTrue(ai.update_needs_repair(response))
                with self.assertRaisesRegex(ValueError, "samo potwierdzenie"):
                    self.persist(response, previous_row())

    def test_confirmed_new_event_is_not_mistaken_for_confirmation_only(self):
        for text in (
            "Minister potwierdził podpisanie porozumienia kończącego protest.",
            "Nowe artykuły potwierdzają podpisanie porozumienia.",
            "Kolejne artykuły potwierdzają wcześniejsze dane. Liczba rannych wzrosła do 18.",
        ):
            with self.subTest(text=text):
                self.assertFalse(ai.update_needs_repair({"update": {"status": "NEW_INFORMATION", "new_information_pl": text}}))

    def persist(self, response, previous=None, run_id="run3", input_hash="new"):
        client = FakeMergeClient([], [], [])
        with patch.object(ai, "now", return_value="2026-10-02T08:34:00+00:00"):
            ai.persist_summary(client, topic_id="topic", run_id=run_id, model="test", summary=response,
                               summary_hash=input_hash, previous_row=previous, new_article_ids=["new"])
        return {table: rows[0] for table, rows, _ in client.upserts}

    def test_explicit_no_information_is_valid_and_never_returns_reader_text(self):
        result = ai.normalize_summary_response({"update": {
            "status": "NO_NEW_INFORMATION", "is_update": True,
            "new_information_pl": "Artykuły potwierdzają znane ustalenia.", "what_changed_pl": "Potwierdzenie",
            "new_article_ids": ["new"],
        }})
        self.assertFalse(ai.update_needs_repair(result))
        self.assertFalse(result["update"]["is_update"])
        self.assertEqual(result["update"]["new_information_pl"], "")
        self.assertEqual(result["update"]["what_changed_pl"], "")
        self.assertEqual(result["update"]["new_article_ids"], ["new"])

    def test_empty_new_information_still_requires_repair(self):
        self.assertTrue(ai.update_needs_repair(ai.normalize_summary_response({"update": {
            "status": "NEW_INFORMATION", "is_update": True, "new_information_pl": "", "what_changed_pl": "",
        }})))

    def test_no_information_preserves_base_updates_and_records_processed_articles(self):
        old = previous_row()
        original = deepcopy(old)
        rows = self.persist({"update": {"status": "NO_NEW_INFORMATION"}}, old)
        current = rows["topic_summaries"]
        self.assertEqual(old, original)
        self.assertEqual(current["summary"]["base_summary"], old["summary"]["base_summary"])
        self.assertEqual(current["summary"]["updates"], old["summary"]["updates"])
        self.assertEqual(current["summary"]["latest_update"], old["summary"]["latest_update"])
        self.assertEqual(current["summary"]["last_analysis"]["status"], "NO_NEW_INFORMATION")
        self.assertEqual(current["summary"]["processed_article_ids"], ["new"])
        self.assertEqual(rows["topic_summary_versions"]["new_article_ids"], ["new"])
        self.assertEqual(current["updated_at"], "2026-10-02T08:34:00+00:00")

    def test_first_no_information_result_does_not_create_an_update(self):
        old = previous_row()
        old["summary"]["updates"] = []
        old["summary"]["latest_update"] = ai.empty_update()
        result = self.persist({"update": {"status": "NO_NEW_INFORMATION"}}, old)["topic_summaries"]
        self.assertEqual(result["summary"]["updates"], [])
        self.assertEqual(ai.stored_updates(result["summary"]), [])

    def test_new_information_keeps_all_updates_even_when_run_id_is_reused(self):
        old = previous_row()
        response = {"update": {"status": "NEW_INFORMATION", "new_information_pl": "Nowa decyzja."}}
        result = self.persist(response, old, run_id="run2")["topic_summaries"]
        updates = result["summary"]["updates"]
        self.assertEqual(len(updates), 3)
        self.assertEqual(updates[:2], old["summary"]["updates"])
        self.assertEqual(updates[-1]["generated_at"], "2026-10-02T08:34:00+00:00")
        self.assertTrue(updates[-1]["update_id"])
        retried = self.persist(response, result, run_id="run2")["topic_summaries"]
        self.assertEqual(len(retried["summary"]["updates"]), 3)

    def test_context_includes_base_and_all_meaningful_updates(self):
        stored = previous_row()["summary"]
        stored["updates"].append({"status": "NO_NEW_INFORMATION", "new_information_pl": ""})
        context = ai.previous_aggregation_context(stored)
        self.assertEqual(context["base_summary"], stored["base_summary"])
        self.assertEqual(context["prior_updates"], stored["updates"][:2])

    def test_normal_run_accepts_no_information_without_retry_or_reprocessing(self):
        self.check_normal_run([{"update": {"status": "NO_NEW_INFORMATION"}}])

    def test_normal_run_retries_confirmation_then_accepts_no_information(self):
        self.check_normal_run([
            {"update": {"status": "NEW_INFORMATION", "new_information_pl": "Kolejne artykuły potwierdzają wcześniejsze dane."}},
            {"update": {"status": "NO_NEW_INFORMATION"}},
        ])

    def check_normal_run(self, responses):
        class Client(FakeMergeClient):
            def upsert(self, table, rows, *, on_conflict):
                super().upsert(table, deepcopy(rows), on_conflict=on_conflict)
                if table == "topic_summaries":
                    self.rows[table] = deepcopy(rows)

        old = previous_row()
        client = Client([{"topic_id": "topic", "headline_pl": "[Polska] Wątek", "status": "ACTIVE"}],
                       [{"topic_id": "topic", "article_id": value} for value in ("old", "new")], [old])
        client.rows["article_topic_assignments"] = [
            {"topic_id": "topic", "article_id": "old", "created_at": "2026-10-01T00:00:00+00:00"},
            {"topic_id": "topic", "article_id": "new", "created_at": "2026-10-02T08:00:00+00:00"},
        ]
        articles = {value: {"article_id": value, "source_id": value, "source_name": value, "title": value,
                            "original_language": "pl", "canonical_url": "https://example.com/" + value, "body": value}
                    for value in ("old", "new")}
        def local(conn, ids):
            return [articles[value] for value in ids]
        with TemporaryDirectory() as directory, patch.object(ai, "local_articles", side_effect=local), patch.object(
            ai, "call_openai", side_effect=responses,
        ) as call, patch.object(ai, "now", return_value="2026-10-02T08:34:00+00:00"), patch.object(ai, "log"):
            first = ai.retry_incomplete_summaries(Path(directory) / "articles.db", "run3", client)
            second = ai.retry_incomplete_summaries(Path(directory) / "articles.db", "run4", client)
        self.assertEqual(first["failed_summaries"], 0)
        self.assertEqual(second["summaries"], 0)
        self.assertEqual(call.call_count, len(responses))
        context = call.call_args.args[1]["previous_aggregation"]
        self.assertEqual(len(context["prior_updates"]), 2)
        self.assertEqual(context["base_summary"], old["summary"]["base_summary"])
        self.assertEqual(client.rows["topic_articles"], [{"topic_id": "topic", "article_id": value} for value in ("old", "new")])


if __name__ == "__main__":
    unittest.main()
