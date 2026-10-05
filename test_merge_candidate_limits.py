import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import ai_pipeline as ai
from test_topic_titles import FakeMergeClient


class MergeCandidateLimitTests(unittest.TestCase):
    def test_two_scattered_words_are_rejected_but_shared_phrase_is_kept(self):
        topics = [
            {"topic_id": "a", "headline_pl": "Falcon bada Artemis"},
            {"topic_id": "b", "headline_pl": "Artemis odwiedza Falcon"},
        ]
        self.assertEqual(ai.build_topic_merge_candidate_groups(topics), [])
        topics[1]["headline_pl"] = "Falcon bada Artemis podczas lotu"
        self.assertEqual(ai.build_topic_merge_candidate_groups(topics), [["a", "b"]])

    def test_three_scattered_anchors_still_create_a_candidate(self):
        topics = [
            {"topic_id": "a", "headline_pl": "Falcon bada Artemis nad Orion"},
            {"topic_id": "b", "headline_pl": "Orion obserwuje Artemis razem Falcon"},
        ]
        self.assertEqual(ai.build_topic_merge_candidate_groups(topics), [["a", "b"]])

    def test_moderate_semantic_similarity_does_not_reach_ai(self):
        self.assertEqual(
            ai.build_embedding_candidate_edges(["a", "b"], [[1.0, 0.0], [0.86, 0.51]]),
            {},
        )
        self.assertEqual(
            set(ai.build_embedding_candidate_edges(["a", "b"], [[1.0, 0.0], [0.96, 0.28]])),
            {("a", "b")},
        )

    def test_disjoint_groups_share_a_request_with_separate_scopes(self):
        topics = [{"topic_id": str(index), "headline_pl": str(index)} for index in range(80)]
        groups = [[str(index), str(index + 1)] for index in range(0, 80, 2)]
        requests = ai.build_topic_merge_requests(
            topics, max_topics_per_request=100,
            candidate_groups=groups, preserve_candidate_group_overlap=True,
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(requests[0]), 80)
        scopes = {}
        for record in requests[0]:
            scopes.setdefault(record["candidate_group_id"], set()).add(record["topic_id"])
        self.assertEqual({frozenset(group) for group in scopes.values()}, {frozenset(group) for group in groups})

    def test_overlapping_groups_stay_separate_and_request_size_is_bounded(self):
        topics = [{"topic_id": topic_id, "headline_pl": topic_id} for topic_id in "abcdef"]
        requests = ai.build_topic_merge_requests(
            topics, max_topics_per_request=3,
            candidate_groups=[["a", "b"], ["b", "c"], ["d", "e"], ["e", "f"]],
            preserve_candidate_group_overlap=True,
        )
        self.assertTrue(all(len(request) <= 3 for request in requests))
        for group in [("a", "b"), ("b", "c"), ("d", "e"), ("e", "f")]:
            self.assertTrue(any(set(group).issubset({r["topic_id"] for r in request}) for request in requests))
        self.assertTrue(all(len({r["topic_id"] for r in request}) == len(request) for request in requests))

    def test_old_repository_variables_cannot_loosen_candidate_selection(self):
        env = {
            **os.environ,
            "AI_TOPIC_MERGE_MAX_REQUESTS": "80",
            "AI_TOPIC_MERGE_EMBEDDING_TOP_K": "5",
            "AI_TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY": "0.84",
            "AI_TOPIC_MERGE_MAX_TOPICS_PER_REQUEST": "100",
        }
        result = subprocess.run(
            [sys.executable, "-c", "import json, ai_pipeline as a; print(json.dumps([a.TOPIC_MERGE_EMBEDDING_TOP_K, a.TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY, a.TOPIC_MERGE_MAX_TOPICS_PER_REQUEST]))"],
            cwd=Path(__file__).parent, env=env, check=True, capture_output=True, text=True,
        )
        self.assertEqual(json.loads(result.stdout), [3, 0.88, 80])

    def test_lower_threshold_accepts_new_candidates_but_still_rejects_weaker_pairs(self):
        self.assertEqual(
            set(ai.build_embedding_candidate_edges(["a", "b"], [[1.0, 0.0], [0.89, (1 - 0.89**2)**0.5]])),
            {("a", "b")},
        )
        self.assertEqual(
            ai.build_embedding_candidate_edges(["a", "b"], [[1.0, 0.0], [0.87, (1 - 0.87**2)**0.5]]),
            {},
        )

    def test_semantic_only_chain_preserves_every_pair_in_groups_and_requests_of_eighty(self):
        topics = [{"topic_id": str(index), "headline_pl": str(index)} for index in range(200)]
        edges = {(str(index), str(index + 1)): 0.95 for index in range(199)}
        with patch.object(ai, "_topic_merge_candidate_edges", side_effect=AssertionError("Lexical filter called")):
            groups = ai.build_topic_merge_candidate_groups(
                topics, semantic_edges=edges, preserve_candidate_edges=True,
                include_lexical_candidates=False,
            )
        requests = ai.build_topic_merge_requests(
            topics, candidate_groups=groups, preserve_candidate_group_overlap=True,
        )
        self.assertTrue(groups)
        self.assertTrue(all(2 <= len(group) <= 80 for group in groups))
        self.assertTrue(all(len(request) <= 80 for request in requests))
        for pair in edges:
            self.assertTrue(any(set(pair).issubset(group) for group in groups))
            self.assertTrue(any(set(pair).issubset({row["topic_id"] for row in request}) for request in requests))

    def test_normal_selection_uses_words_only_when_embeddings_unavailable(self):
        topics = [
            {"topic_id": "a", "headline_pl": "Falcon bada Artemis nad Orion"},
            {"topic_id": "b", "headline_pl": "Orion obserwuje Artemis razem Falcon"},
        ]
        for embedding_result, enabled, expected_calls in (
            ({}, True, 0),  # A successful zero-match result must remain empty.
            ({("a", "b"): 0.95}, True, 1),
            (RuntimeError("Embedding outage"), True, 1),
            ({}, False, 1),
        ):
            with self.subTest(result=embedding_result, enabled=enabled):
                client = FakeMergeClient(topics, [], [])
                with TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch.object(
                    ai, "TOPIC_MERGE_EMBEDDINGS_ENABLED", enabled,
                ), patch.object(
                    ai, "build_topic_embedding_candidate_edges",
                    **({"side_effect": embedding_result} if isinstance(embedding_result, Exception)
                       else {"return_value": embedding_result}),
                ), patch.object(ai, "call_openai", return_value={"merge_groups": []}) as model, patch.object(ai, "log"):
                    ai.merge_active_topics(Path(temp_dir) / "articles.sqlite3", "run", client, prefer_embeddings=True)
                self.assertEqual(model.call_count, expected_calls)

    def test_default_pipeline_enables_embedding_primary_selection(self):
        stats = {key: 0 for key in (
            "merge_candidates", "topics_merged", "merge_failed", "local_candidate_groups",
            "local_candidate_topics", "largest_candidate_group", "merge_requests",
        )}
        with TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch.object(
            ai, "pending_articles", return_value=[],
        ), patch.object(ai, "merge_active_topics", return_value=stats) as merge, patch.object(
            ai, "normalize_topic_titles", return_value=0,
        ), patch.object(ai, "classify_topic_categories", return_value=0), patch.object(
            ai, "retry_incomplete_summaries", return_value={"summaries": 0, "failed_summaries": 0},
        ), patch.object(ai, "log"):
            ai.analyze_run(Path(temp_dir) / "articles.sqlite3", "run", object())
        self.assertTrue(merge.call_args.kwargs["prefer_embeddings"])

    def run_merge(self, topics, requests, response):
        client = FakeMergeClient(topics, [], [])
        with TemporaryDirectory() as temp_dir, patch.object(
            ai, "build_topic_embedding_candidate_edges", return_value={},
        ), patch.object(ai, "build_topic_merge_requests", return_value=requests), patch.object(
            ai, "call_openai", return_value=response,
        ) as call, patch.object(ai, "log"):
            ai.merge_active_topics(Path(temp_dir) / "articles.sqlite3", "run", client)
            return client, call.call_count

    def test_merge_stage_processes_all_batches_even_with_old_limit_variable(self):
        for batch_count in (34, 81):
            with self.subTest(batches=batch_count), patch.dict(os.environ, {"AI_TOPIC_MERGE_MAX_REQUESTS": "20"}):
                topics = [{"topic_id": f"t{index}", "headline_pl": f"Topic {index}"} for index in range(batch_count * 2)]
                requests = [
                    [{"topic_id": f"t{index}", "candidate_group_id": str(index)},
                     {"topic_id": f"t{index + 1}", "candidate_group_id": str(index)}]
                    for index in range(0, batch_count * 2, 2)
                ]
                _, count = self.run_merge(topics, requests, {"merge_groups": []})
                self.assertEqual(count, batch_count)

    def test_ai_cannot_merge_across_packed_groups_or_use_foreign_ids(self):
        topics = [{"topic_id": topic_id, "headline_pl": topic_id} for topic_id in "abcde"]
        requests = [[
            {"topic_id": "a", "candidate_group_id": "first"},
            {"topic_id": "b", "candidate_group_id": "first"},
            {"topic_id": "c", "candidate_group_id": "second"},
            {"topic_id": "d", "candidate_group_id": "second"},
        ]]
        response = {"merge_groups": [
            {"topic_ids": ["a", "c"], "confidence": 0.99},
            {"topic_ids": ["b", "e"], "confidence": 0.99},
        ]}
        client, count = self.run_merge(topics, requests, response)
        self.assertEqual(count, 1)
        self.assertFalse(any(table == "topics" for table, _, _ in client.upserts))
        self.assertEqual(client.updates, [])


if __name__ == "__main__":
    unittest.main()
