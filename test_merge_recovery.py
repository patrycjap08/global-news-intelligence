import copy
import itertools
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ai_pipeline as ai
import news_pipeline
from test_topic_titles import FakeMergeClient


class MergeRecoveryTests(unittest.TestCase):
    def test_split_keeps_whole_independent_groups(self):
        topics = [
            {"topic_id": str(index), "candidate_group_id": str(index // 2)}
            for index in range(10)
        ]
        children = ai.split_topic_merge_request(topics, set())
        self.assertEqual(len(children), 2)
        self.assertEqual(sorted(row["topic_id"] for child in children for row in child),
                         sorted(row["topic_id"] for row in topics))
        for group in range(5):
            self.assertTrue(any({str(group * 2), str(group * 2 + 1)}.issubset(
                {row["topic_id"] for row in child}) for child in children))
        self.assertTrue(all(len(child) < len(topics) for child in children))

    def test_recursive_split_preserves_chain_star_and_dense_edges(self):
        ids = [str(index) for index in range(12)]
        for edges in (
            set(zip(ids, ids[1:])),
            {(ids[0], other) for other in ids[1:]},
            set(itertools.combinations(ids, 2)),
        ):
            with self.subTest(edges=len(edges)):
                topics = [{"topic_id": key, "candidate_group_id": "original"} for key in ids]
                queue = [topics]
                leaves = []
                while queue:
                    parent = queue.pop()
                    children = ai.split_topic_merge_request(parent, edges)
                    if children:
                        self.assertTrue(all(2 <= len(child) < len(parent) for child in children))
                        queue.extend(children)
                    else:
                        leaves.append(parent)
                for edge in edges:
                    self.assertTrue(any(set(edge).issubset(
                        {row["topic_id"] for row in leaf}) for leaf in leaves))

    def test_schema_limits_ids_and_output_without_mutating_global_schema(self):
        original = copy.deepcopy(ai.TOPIC_MERGE_RESPONSE_SCHEMA)
        schema = ai.merge_response_schema([{"topic_id": key} for key in "abcd"])
        groups = schema["properties"]["merge_groups"]
        self.assertEqual(groups["maxItems"], 2)
        self.assertEqual(groups["items"]["properties"]["topic_ids"]["items"]["enum"], list("abcd"))
        self.assertEqual(ai.TOPIC_MERGE_RESPONSE_SCHEMA, original)

    def run_merge(self, topic_ids, edges, responses):
        client = FakeMergeClient(
            [{"topic_id": key, "headline_pl": key} for key in topic_ids], [], [],
        )
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch.object(
            ai, "TOPIC_MERGE_EMBEDDINGS_ENABLED", True,
        ), patch.object(ai, "build_topic_embedding_candidate_edges", return_value=edges), patch.object(
            ai, "call_openai", side_effect=responses,
        ) as model, patch.object(ai, "log"):
            stats = ai.merge_active_topics(
                Path(folder) / "articles.sqlite3", "run", client,
                model="gpt-5-nano", prefer_embeddings=True,
            )
        return stats, client, model

    def test_truncated_batch_recovers_and_records_each_attempt(self):
        truncated = ai.AIResponseParseError("incomplete (reason=max_output_tokens)", '{"merge_groups":[')
        stats, client, model = self.run_merge(
            "abcd", {("a", "b"): .95, ("c", "d"): .95},
            [truncated, {"merge_groups": []}, {"merge_groups": []}],
        )
        self.assertEqual((stats["merge_requests"], stats["merge_split_retries"], stats["merge_failed"]), (3, 1, 0))
        history = [row for table, rows, _ in client.upserts if table == "topic_runs" for row in rows]
        self.assertEqual([row["status"] for row in history], ["FAILED", "COMPLETED", "COMPLETED"])
        self.assertEqual(len({row["topic_run_id"] for row in history}), 3)
        self.assertTrue(all(call.kwargs["reasoning_effort"] == "minimal" for call in model.call_args_list))

    def test_failed_pair_does_not_discard_successful_sibling(self):
        truncated = ai.AIResponseParseError("incomplete (reason=max_output_tokens)", "partial")
        stats, client, model = self.run_merge(
            "abcd", {("a", "b"): .95, ("c", "d"): .95},
            [truncated, truncated, {"merge_groups": []}],
        )
        self.assertEqual((model.call_count, stats["merge_failed"]), (3, 1))
        self.assertTrue(any(row["status"] == "COMPLETED"
                            for table, rows, _ in client.upserts if table == "topic_runs" for row in rows))

    def test_non_truncation_error_is_not_repeated_by_splitting(self):
        stats, _, model = self.run_merge(
            "abcd", {("a", "b"): .95, ("c", "d"): .95},
            [RuntimeError("no credits remaining")],
        )
        self.assertEqual((model.call_count, stats["merge_split_retries"], stats["merge_failed"]), (1, 0, 1))

    def test_api_receives_reasoning_setting_and_logs_truncated_token_usage(self):
        response = SimpleNamespace(
            status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            output_text="partial", usage=SimpleNamespace(
                input_tokens=100, output_tokens=12000,
                input_tokens_details=SimpleNamespace(cached_tokens=50),
                output_tokens_details=SimpleNamespace(reasoning_tokens=11900),
            ),
        )
        with patch("openai.OpenAI") as sdk, patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch.object(ai, "log") as logger:
            sdk.return_value.responses.create.return_value = response
            with self.assertRaisesRegex(ai.AIResponseParseError, "reason=max_output_tokens"):
                ai.call_openai("instructions", {}, "gpt-5-nano", retry_limit=1, reasoning_effort="minimal")
        self.assertEqual(sdk.return_value.responses.create.call_args.kwargs["reasoning"], {"effort": "minimal"})
        self.assertTrue(any("rozumowanie: 11900" in str(call) for call in logger.call_args_list))

    def test_ai_only_fails_only_when_errors_remain_and_does_not_harvest(self):
        for result, expected in (
            ({"merge_failed": 1}, 1),
            ({"failed_summaries": 1}, 1),
            ({"merge_split_retries": 1, "merge_failed": 0, "summaries": 3}, 0),
        ):
            with self.subTest(result=result), TemporaryDirectory() as folder, patch(
                "sys.argv", ["news_pipeline.py", "--ai-only", "--db", str(Path(folder) / "articles.sqlite3")],
            ), patch.object(news_pipeline, "SupabaseRestClient"), patch.object(
                news_pipeline, "pull_state", return_value={},
            ), patch.object(news_pipeline, "latest_run_id", return_value="saved_run"), patch.object(
                news_pipeline, "analyze_run", return_value=result,
            ) as analyze, patch.object(news_pipeline, "log"), patch.object(
                news_pipeline.subprocess, "run",
            ) as harvest, patch.object(news_pipeline, "push_run") as push:
                self.assertEqual(news_pipeline.main(), expected)
                self.assertEqual(analyze.call_args.args[1], "saved_run")
                harvest.assert_not_called()
                push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
