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
            topics, candidate_groups=groups, preserve_candidate_group_overlap=True,
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

    def test_old_repository_variables_cannot_restore_liberal_limits(self):
        env = {
            **os.environ,
            "AI_TOPIC_MERGE_MAX_REQUESTS": "80",
            "AI_TOPIC_MERGE_EMBEDDING_TOP_K": "5",
            "AI_TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY": "0.84",
        }
        result = subprocess.run(
            [sys.executable, "-c", "import json, ai_pipeline as a; print(json.dumps([a.TOPIC_MERGE_MAX_REQUESTS, a.TOPIC_MERGE_EMBEDDING_TOP_K, a.TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY]))"],
            cwd=Path(__file__).parent, env=env, check=True, capture_output=True, text=True,
        )
        self.assertEqual(json.loads(result.stdout), [20, 3, 0.90])

    def run_merge(self, topics, requests, response):
        client = FakeMergeClient(topics, [], [])
        with TemporaryDirectory() as temp_dir, patch.object(
            ai, "build_topic_embedding_candidate_edges", return_value={},
        ), patch.object(ai, "build_topic_merge_requests", return_value=requests), patch.object(
            ai, "call_openai", return_value=response,
        ) as call, patch.object(ai, "log"):
            ai.merge_active_topics(Path(temp_dir) / "articles.sqlite3", "run", client)
            return client, call.call_count

    def test_merge_stage_never_sends_more_than_twenty_batches(self):
        topics = [{"topic_id": f"t{index}", "headline_pl": f"Topic {index}"} for index in range(50)]
        requests = [
            [{"topic_id": f"t{index}", "candidate_group_id": str(index)},
             {"topic_id": f"t{index + 1}", "candidate_group_id": str(index)}]
            for index in range(0, 50, 2)
        ]
        _, count = self.run_merge(topics, requests, {"merge_groups": []})
        self.assertEqual(count, 20)

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
