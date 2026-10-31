"""Regression: title preparation timed out on the entire synthesis archive."""
import copy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import ai_pipeline as ai
from supabase_client import SupabaseError
from test_topic_titles import FakeMergeClient


class ScopedClient(FakeMergeClient):
    """Model server-side filters/projections and reject archive-sized JSON reads."""
    def __init__(self, topics=(), links=(), summaries=(), articles=(), *, allow_full=False):
        super().__init__(list(topics), list(links), list(summaries), list(articles))
        self.calls = []
        self.allow_full = allow_full

    def select_all(self, table, *, columns="*", filters=()):
        self.calls.append((table, columns, list(filters)))
        rows = list(self.rows.get(table, []))
        if table == "topic_summaries" and "summary" in columns.split(","):
            if not self.allow_full or "topic_id" not in dict(filters):
                raise SupabaseError("Full synthesis archive timed out after three attempts")
        for column, expression in filters:
            if column == "order":
                continue
            if expression.startswith("in.("):
                allowed = set(expression[4:-1].split(","))
                rows = [r for r in rows if str(r.get(column) or "") in allowed]
            elif expression.startswith("eq."):
                rows = [r for r in rows if str(r.get(column) or "") == expression[3:]]
            elif expression.startswith("neq."):
                rows = [r for r in rows if str(r.get(column) or "") != expression[4:]]
            elif expression.startswith("gte."):
                rows = [r for r in rows if str(r.get(column) or "") >= expression[4:]]
        if table == "topic_summaries" and ":summary->" in columns:
            projected = []
            for row in rows:
                stored = row.get("summary") or {}
                item = {"topic_id": row["topic_id"]}
                for label, key in (("current_sentence", "current_summary"), ("base_sentence", "base_summary"), ("legacy_sentence", None)):
                    obj = (stored.get(key) or {}) if key else stored
                    item[label] = (obj.get("topic") or {}).get("what_happened_one_sentence_pl")
                if "processed_article_ids:summary->processed_article_ids" in columns:
                    item["processed_article_ids"] = stored.get("processed_article_ids")
                projected.append(item)
            return projected
        return rows


class TitleDatabaseReadTests(unittest.TestCase):
    def setUp(self):
        self.stamp = datetime.now(timezone.utc).isoformat()
        self.old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

    def topic(self, key, title="[Polska] Finansowanie szkół", *, old=False):
        return {"topic_id": key, "headline_pl": title, "status": "ACTIVE",
                "source_count": 2, "last_seen_at": self.old if old else self.stamp}

    def calls(self, client, table):
        return [call for call in client.calls if call[0] == table]

    def test_valid_titles_never_fetch_summaries_or_call_ai(self):
        client = ScopedClient([self.topic("new"), self.topic("old", "Zły", old=True)])
        with patch.object(ai, "call_openai") as call:
            self.assertEqual(ai.normalize_topic_titles(client), 0)
        call.assert_not_called()
        self.assertEqual(self.calls(client, "topic_summaries"), [])
        self.assertEqual(self.calls(client, "articles"), [])
        self.assertIn("last_seen_at", dict(client.calls[0][2]))

    def test_no_active_topics_skips_all_followup_reads(self):
        client = ScopedClient([self.topic("old", "Zły", old=True)])
        self.assertEqual(ai.normalize_topic_titles(client), 0)
        self.assertEqual([c[0] for c in client.calls], ["topics"])

    def test_projected_current_description_repairs_a_copied_title_without_reading_archive(self):
        article_title = "Rząd zmieni sposób finansowania szkół od przyszłego roku"
        rows = [self.topic("new", "[Polska] " + article_title), self.topic("old", "Zły", old=True)]
        summaries = [{"topic_id": "new", "summary": {
            "base_summary": {"topic": {"what_happened_one_sentence_pl": "Stary opis."}},
            "current_summary": {"topic": {"what_happened_one_sentence_pl": "Bieżąca reforma finansowania szkół."}},
            "updates": [{"private_ledger": "DO_NOT_TRANSFER"}],
        }}, {"topic_id": "old", "summary": {"huge_history": "DO_NOT_TRANSFER"}}]
        client = ScopedClient(rows, [{"topic_id": "new", "article_id": "a"}], summaries,
                              [{"article_id": "a", "title": article_title, "opening_text": "Nowe finansowanie."}])
        original = copy.deepcopy(summaries)
        with patch.object(ai, "call_openai", return_value={"titles": [
                {"topic_id": "new", "title_pl": "[Polska] Reforma finansowania oświaty"}]}) as call:
            self.assertEqual(ai.normalize_topic_titles(client), 1)
        payload = call.call_args.args[1]["topics"]
        self.assertEqual([row["topic_id"] for row in payload], ["new"])
        self.assertEqual(payload[0]["one_sentence_pl"], "Bieżąca reforma finansowania szkół.")
        self.assertEqual(payload[0]["article_titles"], [article_title])
        self.assertEqual(client.rows["topic_summaries"], original)
        self.assertEqual(client.rows["topics"][1]["headline_pl"], "Zły")
        for table, columns, filters in client.calls[1:]:
            self.assertIn("in.(", str(filters))
            self.assertIn("order", dict(filters))
            if table == "topic_summaries":
                self.assertNotIn("summary", columns.split(","))
                self.assertEqual(dict(filters)["topic_id"], "in.(new)")

    def test_forced_topic_outside_window_is_still_checked_without_reopening_other_history(self):
        client = ScopedClient([self.topic("forced", old=True), self.topic("old", "Zły", old=True)])
        with patch.object(ai, "call_openai", return_value={"titles": [
                {"topic_id": "forced", "title_pl": "[Polska] Zmiany w finansowaniu oświaty"}]}) as call:
            self.assertEqual(ai.normalize_topic_titles(client, forced_topic_ids={"forced"}), 1)
        self.assertEqual([r["topic_id"] for r in call.call_args.args[1]["topics"]], ["forced"])
        self.assertEqual(client.rows["topics"][1]["headline_pl"], "Zły")

    def test_description_projection_preserves_base_and_legacy_formats(self):
        client = ScopedClient(summaries=[
            {"topic_id": "base", "summary": {"base_summary": {"topic": {"what_happened_one_sentence_pl": "Opis bazowy."}}}},
            {"topic_id": "legacy", "summary": {"topic": {"what_happened_one_sentence_pl": "Opis dawny."}}},
        ])
        result = ai._topic_description_metadata(client, ["base", "legacy"])
        self.assertEqual(result["base"]["topic"]["what_happened_one_sentence_pl"], "Opis bazowy.")
        self.assertEqual(result["legacy"]["topic"]["what_happened_one_sentence_pl"], "Opis dawny.")

    def test_id_batches_are_bounded_deduplicated_and_do_not_include_foreign_rows(self):
        rows = [{"topic_id": str(i)} for i in range(123)] + [{"topic_id": "foreign"}]
        client = FakeMergeClient([], [], rows)
        with patch.object(client, "select_all", wraps=client.select_all) as select:
            actual = ai._select_rows_by_ids(client, "topic_summaries", "topic_id", [str(i) for i in range(123)] * 2)
        self.assertEqual(len(actual), 123)
        self.assertEqual({r["topic_id"] for r in actual}, {str(i) for i in range(123)})
        self.assertEqual(select.call_count, 3)
        for call in select.call_args_list:
            expression = dict(call.kwargs["filters"])["topic_id"]
            self.assertLessEqual(len(expression[4:-1].split(",")), 50)

    def test_categories_fetch_only_descriptions_for_missing_categories(self):
        client = ScopedClient([self.topic("new"), self.topic("reviewed")],
            [{"topic_id": tid, "article_id": tid + str(i)} for tid in ("new", "reviewed") for i in range(2)],
            [{"topic_id": tid, "summary": {"topic": {"what_happened_one_sentence_pl": "Nowe finansowanie szkół."}}} for tid in ("new", "reviewed")],
            [{"article_id": tid + str(i), "source_profile": "CENTER", "source_id": str(i), "title": "Decyzja rządu"} for tid in ("new", "reviewed") for i in range(2)])
        client.rows["topic_categories"] = [{"topic_id": "reviewed", "category": "POLSKA"}]
        with patch.object(ai, "call_openai", return_value={"categories": [{"topic_id": "new", "categories": ["POLSKA"]}]}):
            self.assertEqual(ai.classify_topic_categories(client), 1)
        self.assertEqual(dict(self.calls(client, "topic_summaries")[0][2])["topic_id"], "in.(new)")

    def test_summary_queue_never_reads_archived_ledgers_or_singletons(self):
        topics = [self.topic("topic_perspectives_new"), self.topic("singleton"), self.topic("old", old=True)]
        links = [{"topic_id": t["topic_id"], "article_id": t["topic_id"] + str(i)}
                 for t in topics for i in range(1 if t["topic_id"] == "singleton" else 2)]
        stored = {"processed_article_ids": ["topic_perspectives_new0", "topic_perspectives_new1"], "summary_pl": "Istniejący tekst."}
        client = ScopedClient(topics, links, [{"topic_id": "topic_perspectives_new", "updated_at": self.stamp, "summary": stored}], allow_full=True)
        with TemporaryDirectory() as folder:
            db = Path(folder) / "db"
            sqlite3.connect(db).close()
            with patch.object(ai, "generate_summary_response") as generate:
                stats = ai.retry_incomplete_summaries(db, "r", client)
        generate.assert_not_called()
        self.assertEqual(stats, {"summaries": 0, "failed_summaries": 0})
        reads = self.calls(client, "topic_summaries")
        self.assertEqual(len(reads), 1)
        self.assertEqual(dict(reads[0][2])["topic_id"], "in.(topic_perspectives_new)")

    def test_resume_focus_reads_only_processed_ids_instead_of_fact_ledgers(self):
        client = ScopedClient(summaries=[{"topic_id": "new", "summary": {"processed_article_ids": ["old"]}}])
        client.rows["article_topic_assignments"] = [{"run_id": "r", "topic_id": "new", "article_id": "a"}]
        self.assertEqual(ai.pending_run_merge_focus(client, "r"), {"new"})
        self.assertEqual(self.calls(client, "topic_summaries")[0][1], "topic_id,processed_article_ids:summary->processed_article_ids")

    def test_merge_reads_at_most_twenty_current_ledgers_at_once_and_preserves_them(self):
        topics = [self.topic("new-" + str(i)) for i in range(41)] + [self.topic("archive", old=True)]
        summaries = [{"topic_id": t["topic_id"], "summary": {"summary_pl": "Oryginalna publikacja.",
                      "updates": [{"text": "Zapisana aktualizacja."}]}} for t in topics]
        client = ScopedClient(topics, summaries=summaries, allow_full=True)
        original = copy.deepcopy(summaries)
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
             patch.object(ai, "build_topic_embedding_candidate_edges", return_value={}), \
             patch.object(ai, "call_openai") as call:
            ai.merge_active_topics(Path(folder) / "db", "r", client, prefer_embeddings=True)
        call.assert_not_called()
        self.assertEqual(client.rows["topic_summaries"], original)
        reads = self.calls(client, "topic_summaries")
        self.assertEqual(len(reads), 3)
        for _, _, filters in reads:
            requested = dict(filters)["topic_id"][4:-1].split(",")
            self.assertLessEqual(len(requested), 20)
            self.assertNotIn("archive", requested)

    def test_merge_without_new_topics_skips_all_fact_ledger_reads(self):
        client = ScopedClient([self.topic("one"), self.topic("two")])
        with TemporaryDirectory() as folder, patch.object(ai, "call_openai") as call:
            stats = ai.merge_active_topics(Path(folder) / "db", "r", client,
                                            prefer_embeddings=True, focus_topic_ids=set())
        call.assert_not_called()
        self.assertEqual(stats["topics_merged"], 0)
        self.assertEqual([c[0] for c in client.calls], ["topics"])


if __name__ == "__main__":
    unittest.main()
