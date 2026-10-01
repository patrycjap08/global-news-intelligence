from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import rebuild_topic_updates as rebuild


def fixtures():
    base = {"summary_pl": "Szpital rozpoczął protest.", "facts": [{"text_pl": "Protest trwa.", "article_ids": ["base"]}], "update": {"is_update": False}}
    first = {"is_update": True, "new_information_pl": "Stara pierwsza: protest trwa.", "what_changed_pl": "Stare zmiany 1",
             "new_article_ids": ["a1"], "run_id": "run1", "generated_at": "2026-09-01T12:00:00Z"}
    second = {"is_update": True, "new_information_pl": "Stara druga: protest trwa.", "what_changed_pl": "Stare zmiany 2",
              "new_article_ids": ["a2", "a3"], "run_id": "run2", "generated_at": "2026-09-02T12:00:00Z"}
    def stored(updates):
        return {"base_summary": deepcopy(base), "updates": deepcopy(updates), "latest_update": deepcopy(updates[-1])}
    current = {"topic_id": "topic", "version": 3, "model": "old", "input_hash": "oldhash", "summary": stored([first, second]),
               "generated_at": "2026-09-02T12:00:00Z", "updated_at": "2026-09-02T12:00:00Z"}
    history = [{"version": i + 2, "run_id": update["run_id"], "model": "old", "prompt_version": "old",
                "summary": stored([first] if i == 0 else [first, second]), "new_article_ids": update["new_article_ids"],
                "generated_at": update["generated_at"]} for i, update in enumerate([first, second])]
    job = {"topic_id": "topic", "title": "[Polska] Protest szpitala", "article_ids": ["base", "a1", "a2", "a3"],
           "current": current, "history": history, "status": "pending", "update_count": 2}
    return job


class Client:
    project_url = "https://example.supabase.co"

    def __init__(self):
        self.calls = []
        self.result = "applied"

    def select_all(self, table, **kwargs):
        assert table == "articles"
        return [{"article_id": value, "source_id": value, "source_name": value, "title": value,
                 "original_language": "pl", "canonical_url": "https://example.com/" + value, "body": "Tekst " + value}
                for value in ("a1", "a2", "a3")]

    def request(self, method, path, *, payload):
        self.calls.append(deepcopy(payload))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class RebuildUpdatesTests(unittest.TestCase):
    def generate(self, job=None, client=None):
        job, client = job or fixtures(), client or Client()
        inputs = []

        def model(instructions, payload, *args, **kwargs):
            inputs.append(deepcopy(payload))
            return {"update": {"is_update": True, "new_information_pl": "Nowe ustalenie 1." if len(inputs) == 1
                               else "Kolejne artykuły potwierdzają wcześniejsze ustalenia o proteście.",
                               "what_changed_pl": "Zmiana" if len(inputs) == 1 else "Potwierdzenie", "new_article_ids": ["invented"]}}

        with patch.object(rebuild.ai, "call_openai", side_effect=model):
            replacement = rebuild.rebuild_job(job, client, "test-model")
        return replacement, inputs

    def test_second_update_sees_only_rebuilt_first_update_and_original_base(self):
        job = fixtures()
        original = deepcopy(job)
        replacement, inputs = self.generate(job)
        self.assertEqual(job, original)
        self.assertEqual(inputs[0]["previous_aggregation"]["prior_updates"], [])
        self.assertEqual(inputs[1]["previous_aggregation"]["prior_updates"][0]["new_information_pl"], "Nowe ustalenie 1.")
        self.assertNotIn("Stara pierwsza", json.dumps(inputs, ensure_ascii=False))
        self.assertNotIn("Stara druga", json.dumps(inputs, ensure_ascii=False))
        self.assertEqual(inputs[1]["previous_aggregation"]["base_summary"], job["current"]["summary"]["base_summary"])
        updates = replacement["current"]["summary"]["updates"]
        self.assertEqual(len(updates), 2)
        self.assertEqual([row["new_article_ids"] for row in updates], [["a1"], ["a2", "a3"]])
        self.assertEqual([[row["article_id"] for row in item["new_articles"]] for item in inputs], [["a1"], ["a2", "a3"]])
        self.assertEqual([row["generated_at"] for row in updates], [row["generated_at"] for row in job["current"]["summary"]["updates"]])
        self.assertEqual([row["run_id"] for row in updates], ["run1", "run2"])
        self.assertEqual(replacement["current"]["summary"]["base_summary"], job["current"]["summary"]["base_summary"])

    def test_all_cumulative_snapshots_are_rewritten_without_old_text(self):
        job = fixtures()
        replacement, _ = self.generate(job)
        self.assertNotIn("Stara", json.dumps(replacement, ensure_ascii=False))
        self.assertNotIn("Stare", json.dumps(replacement, ensure_ascii=False))
        for old, new in zip(job["history"], replacement["history"]):
            for field in ("version", "run_id", "new_article_ids", "generated_at"):
                self.assertEqual(new[field], old[field])
            self.assertEqual(new["summary"]["base_summary"], old["summary"]["base_summary"])
            self.assertEqual(len(new["summary"]["updates"]), len(old["summary"]["updates"]))

    def test_history_only_update_is_recovered_and_sorted_before_newer_update(self):
        job = fixtures()
        second = job["current"]["summary"]["updates"][1]
        job["current"]["summary"]["updates"] = [second]
        updates = rebuild.collect_updates(job["current"], list(reversed(job["history"])))
        self.assertEqual([row["run_id"] for row in updates], ["run1", "run2"])

    def test_ambiguous_reused_run_ids_are_rejected(self):
        job = fixtures()
        job["history"][0]["summary"]["updates"][0]["new_article_ids"] = ["other"]
        with self.assertRaisesRegex(ValueError, "różne zestawy"):
            rebuild.collect_updates(job["current"], job["history"])

    def test_missing_ids_or_article_bodies_do_not_trigger_ai(self):
        job = fixtures()
        job["current"]["summary"]["updates"][0]["new_article_ids"] = []
        with patch.object(rebuild.ai, "call_openai") as model:
            with self.assertRaises(ValueError):
                rebuild.rebuild_job(job, Client(), "model")
            model.assert_not_called()
        with patch.object(Client, "select_all", return_value=[]), patch.object(rebuild.ai, "call_openai") as model:
            with self.assertRaisesRegex(ValueError, "Brakuje artykułów"):
                rebuild.rebuild_job(fixtures(), Client(), "model")
            model.assert_not_called()

    def test_second_generation_failure_leaves_database_and_backup_unchanged(self):
        job = fixtures()
        original = deepcopy(job["current"])
        client = Client()
        state = {"jobs": [job]}
        with TemporaryDirectory() as directory, patch.object(rebuild.ai, "call_openai", side_effect=[
            {"update": {"new_information_pl": "Nowe ustalenie.", "what_changed_pl": "", "new_article_ids": []}},
            RuntimeError("API failed"),
        ]):
            self.assertEqual(rebuild.execute(state, Path(directory) / "state.json", client, "model"), 1)
        self.assertEqual(client.calls, [])
        self.assertEqual(job["current"], original)
        self.assertNotIn("replacement", job)

    def test_checkpoint_reuses_generated_text_and_rpc_supports_lost_response_retry(self):
        job = fixtures()
        job["replacement"], _ = self.generate(job)
        state = {"jobs": [job]}
        client = Client()
        client.result = RuntimeError("network response lost")
        with TemporaryDirectory() as directory, patch.object(rebuild.ai, "call_openai") as model:
            path = Path(directory) / "state.json"
            self.assertEqual(rebuild.execute(state, path, client, "model"), 1)
            saved = json.loads(path.read_text())
            client.result = "already_applied"
            self.assertEqual(rebuild.execute(saved, path, client, "model"), 0)
            self.assertEqual(rebuild.execute(saved, path, client, "model"), 0)
            model.assert_not_called()
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0], client.calls[1])
        self.assertEqual(client.calls[0]["p_expected_current"]["summary"], job["current"]["summary"])
        self.assertNotIn("updated_at", client.calls[0]["p_new_current"])

    def test_legacy_summary_update_preserves_base_prose_and_rewrites_legacy_history(self):
        job = fixtures()
        first = job["current"]["summary"]["updates"][0]
        direct = {**job["current"]["summary"]["base_summary"], "update": first}
        job["current"]["summary"] = deepcopy(direct)
        job["history"] = [{**job["history"][0], "summary": deepcopy(direct)}]
        replacement, _ = self.generate(job)
        self.assertEqual(replacement["current"]["summary"]["base_summary"]["summary_pl"], direct["summary_pl"])
        self.assertEqual(replacement["history"][0]["summary"]["summary_pl"], direct["summary_pl"])
        self.assertEqual(replacement["history"][0]["summary"]["update"]["new_information_pl"], "Nowe ustalenie 1.")


if __name__ == "__main__":
    unittest.main()
