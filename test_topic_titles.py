import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import ai_pipeline
from ai_pipeline import (
    GROUPING_INSTRUCTIONS,
    TOPIC_LABELING_INSTRUCTIONS,
    build_topic_merge_candidate_groups,
    build_topic_merge_requests,
    build_bounded_summary_input,
    choose_merge_canonical_topic_id,
    classify_topic_categories,
    has_composite_geo_prefix,
    is_article_title_copy,
    merge_active_topics,
    merge_overlapping_candidate_groups,
    normalize_topic_titles,
)


class FakeMergeClient:
    def __init__(self, topics, links, summaries, articles=None):
        self.rows = {
            "topics": topics,
            "topic_articles": links,
            "topic_summaries": summaries,
            "topic_categories": [],
            "articles": articles or [],
        }
        self.upserts = []
        self.updates = []
        self.deletes = []

    def select_all(self, table, *, columns="*", filters=()):
        return list(self.rows.get(table, []))

    def upsert(self, table, rows, *, on_conflict):
        self.upserts.append((table, rows, on_conflict))

    def update(self, table, values, *, filters):
        self.updates.append((table, values, list(filters)))
        for row in self.rows.get(table, []):
            matches = True
            for column, expression in filters:
                operator, expected = expression.split(".", 1)
                actual = str(row.get(column) or "")
                if operator == "eq" and actual != expected:
                    matches = False
                if operator == "neq" and actual == expected:
                    matches = False
            if matches:
                row.update(values)

    def delete(self, table, *, filters):
        self.deletes.append((table, list(filters)))


class TopicTitleTests(unittest.TestCase):
    def test_detects_verbatim_article_title_even_with_geo_prefix(self):
        article_title = "Nie uwierzycie, co Trump powiedział w swoim dzisiejszym wystąpieniu"
        self.assertTrue(is_article_title_copy(f"[USA] {article_title}", [article_title]))

    def test_accepts_editorial_topic_label_instead_of_article_title(self):
        article_title = "Nie uwierzycie, co Trump powiedział w swoim dzisiejszym wystąpieniu"
        self.assertFalse(is_article_title_copy("[USA] Dzisiejsze wystąpienie Trumpa", [article_title]))

    def test_normalization_repairs_topic_that_copies_article_title(self):
        article_title = "XTB – tu pracują twoje pieniądze. Dobrze, tylko na kogo?"
        client = FakeMergeClient(
            topics=[{
                "topic_id": "topic_one",
                "headline_pl": f"[Świat] {article_title}",
                "status": "ACTIVE",
            }],
            links=[{"topic_id": "topic_one", "article_id": "article_one"}],
            summaries=[{
                "topic_id": "topic_one",
                "summary": {
                    "topic": {
                        "what_happened_one_sentence_pl": "Opis działalności platformy XTB i ryzyk dla inwestorów."
                    },
                    "summary_pl": "Opis działalności platformy XTB.",
                },
            }],
            articles=[{
                "article_id": "article_one",
                "title": article_title,
                "opening_text": "Materiał analizuje model działalności platformy XTB i pytania dotyczące bezpieczeństwa inwestowania.",
            }],
        )

        with patch.object(
            ai_pipeline,
            "call_openai",
            return_value={
                "titles": [{
                    "topic_id": "topic_one",
                    "title_pl": "[Polska] Model działalności platformy XTB",
                }],
            },
        ):
            changed = normalize_topic_titles(client)

        self.assertEqual(changed, 1)
        self.assertEqual(
            client.rows["topics"][0]["headline_pl"],
            "[Polska] Model działalności platformy XTB",
        )

    def test_detects_multi_country_geo_prefix_but_not_single_country_name(self):
        self.assertTrue(has_composite_geo_prefix("[USA i Iran] Sprawa sankcji"))
        self.assertTrue(has_composite_geo_prefix("[Niemcy, Francja] Wspólna decyzja"))
        self.assertFalse(has_composite_geo_prefix("[Bośnia i Hercegowina] Wybory"))
        self.assertFalse(has_composite_geo_prefix("[USA] Śledztwo na Cornell"))

    def test_grouping_prompt_requires_abstraction_for_singletons(self):
        self.assertIn("dotyczy to także grup jednoartykułowych", GROUPING_INSTRUCTIONS)
        self.assertIn("Dzisiejsze wystąpienie Trumpa", GROUPING_INSTRUCTIONS)

    def test_grouping_prompt_excludes_weather_sport_and_celebrities(self):
        self.assertIn("sport, pogodę i prognozy pogody, celebrytów", GROUPING_INSTRUCTIONS)
        self.assertIn("zwykła prognoza pogody", GROUPING_INSTRUCTIONS)
        self.assertIn("Nie wykluczaj natomiast klęsk żywiołowych", GROUPING_INSTRUCTIONS)
        self.assertIn("SPORT|WEATHER|CELEBRITY", GROUPING_INSTRUCTIONS)

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
            {"local_1_1"},
        )

    def test_labeling_prompt_separates_naming_from_grouping(self):
        self.assertIn("nie grupuj artykułów", TOPIC_LABELING_INSTRUCTIONS)
        self.assertIn("title_original", TOPIC_LABELING_INSTRUCTIONS)
        self.assertIn("body_excerpt_original", TOPIC_LABELING_INSTRUCTIONS)
        self.assertIn("zawsze po polsku", TOPIC_LABELING_INSTRUCTIONS)
        self.assertNotIn("topic_anchor_pl", TOPIC_LABELING_INSTRUCTIONS)

    def test_large_component_uses_bounded_edge_cover_instead_of_one_group_per_topic(self):
        actor_names = [f"Actor{index}" for index in range(120)]
        topics = [
            {
                "topic_id": "hub",
                "headline_pl": "[Świat] " + " ".join(actor_names),
                "what_happened_one_sentence_pl": "Wspólna sprawa.",
                "recent_article_titles": [],
            }
        ] + [
            {
                "topic_id": f"topic_{index}",
                "headline_pl": f"[Świat] {actor_name} wydarzenie",
                "what_happened_one_sentence_pl": "Wspólna sprawa.",
                "recent_article_titles": [],
            }
            for index, actor_name in enumerate(actor_names)
        ]
        groups = build_topic_merge_candidate_groups(topics, max_topics_per_group=20)
        self.assertGreater(len(groups), 1)
        self.assertLessEqual(max(len(group) for group in groups), 20)
        self.assertEqual(
            {topic_id for group in groups for topic_id in group},
            {topic["topic_id"] for topic in topics},
        )
        requests = build_topic_merge_requests(
            topics,
            max_topics_per_request=20,
            candidate_groups=groups,
        )
        self.assertGreater(len(requests), 1)
        self.assertLessEqual(max(len(request) for request in requests), 20)
        self.assertEqual(
            {item["topic_id"] for request in requests for item in request},
            {topic["topic_id"] for topic in topics},
        )

    def test_overlapping_candidate_groups_are_collapsed(self):
        topics = [
            {"topic_id": topic_id, "headline_pl": topic_id}
            for topic_id in ("a", "b", "c")
        ]
        requests = build_topic_merge_requests(
            topics,
            max_topics_per_request=3,
            candidate_groups=[["a", "b"], ["a", "c"]],
        )
        self.assertEqual(
            merge_overlapping_candidate_groups([["a", "b"], ["a", "c"]]),
            [["a", "b", "c"]],
        )
        self.assertEqual(
            [[item["topic_id"] for item in request] for request in requests],
            [["a", "b", "c"]],
        )

    def test_merge_preserves_topic_with_existing_synthesis(self):
        topics = {
            "older_without_summary": {
                "topic_id": "older_without_summary",
                "first_seen_at": "2026-09-01T00:00:00+00:00",
                "article_count": 4,
            },
            "established_topic": {
                "topic_id": "established_topic",
                "first_seen_at": "2026-09-10T00:00:00+00:00",
                "article_count": 2,
            },
            "new_topic": {
                "topic_id": "new_topic",
                "first_seen_at": "2026-09-28T00:00:00+00:00",
                "article_count": 1,
            },
        }
        self.assertEqual(
            choose_merge_canonical_topic_id(
                ["older_without_summary", "established_topic", "new_topic"],
                topics,
                {"established_topic": {"topic": {"what_happened_one_sentence_pl": "stara synteza"}}},
            ),
            "established_topic",
        )

    def test_existing_summary_repair_preserves_oldest_synthesis(self):
        topics = {
            "older_synthesis": {
                "topic_id": "older_synthesis",
                "first_seen_at": "2026-09-20T00:00:00+00:00",
                "article_count": 2,
            },
            "newer_synthesis": {
                "topic_id": "newer_synthesis",
                "first_seen_at": "2026-09-10T00:00:00+00:00",
                "article_count": 5,
            },
        }
        summaries = {
            "older_synthesis": {"topic": {"what_happened_one_sentence_pl": "Starsza synteza"}},
            "newer_synthesis": {"topic": {"what_happened_one_sentence_pl": "Nowsza synteza"}},
        }
        summary_rows = {
            "older_synthesis": {"generated_at": "2026-09-20T08:00:00+00:00"},
            "newer_synthesis": {"generated_at": "2026-09-28T08:00:00+00:00"},
        }

        self.assertEqual(
            choose_merge_canonical_topic_id(
                ["older_synthesis", "newer_synthesis"],
                topics,
                summaries,
                summary_metadata_by_topic=summary_rows,
                prefer_oldest_synthesis=True,
            ),
            "older_synthesis",
        )

    def test_existing_summary_flow_refreshes_only_retained_merged_topics(self):
        captured = {}

        def fake_merge(*args, **kwargs):
            captured["merge"] = kwargs
            kwargs["merged_article_ids_by_topic"]["retained_topic"] = ["new_article"]
            return {"topics_merged": 2, "merge_failed": 0}

        def fake_retry(*args, **kwargs):
            captured["retry"] = kwargs
            return {"summaries": 1, "failed_summaries": 0}

        with patch.object(ai_pipeline, "merge_active_topics", side_effect=fake_merge), \
                patch.object(ai_pipeline, "retry_incomplete_summaries", side_effect=fake_retry):
            stats = ai_pipeline.merge_existing_summaries(
                Path("articles.sqlite3"),
                "run_existing_merge",
                object(),
                max_topics=25,
            )

        self.assertEqual(stats["summaries"], 1)
        self.assertTrue(captured["merge"]["existing_summaries_only"])
        self.assertEqual(captured["merge"]["max_topics"], 25)
        self.assertEqual(captured["retry"]["only_topic_ids"], {"retained_topic"})
        self.assertEqual(
            captured["retry"]["forced_new_article_ids_by_topic"],
            {"retained_topic": ["new_article"]},
        )

    def test_merge_without_synthesis_preserves_oldest_topic(self):
        topics = {
            "old_topic": {
                "topic_id": "old_topic",
                "first_seen_at": "2026-09-01T00:00:00+00:00",
                "article_count": 2,
            },
            "new_topic": {
                "topic_id": "new_topic",
                "first_seen_at": "2026-09-28T00:00:00+00:00",
                "article_count": 5,
            },
        }
        self.assertEqual(
            choose_merge_canonical_topic_id(["old_topic", "new_topic"], topics),
            "old_topic",
        )

    def test_merge_moves_new_topic_into_existing_synthesis_topic(self):
        topics = [
            {
                "topic_id": "old_topic",
                "headline_pl": "Stary tytuł",
                "status": "ACTIVE",
                "first_seen_at": "2026-09-01T00:00:00+00:00",
                "last_seen_at": "2026-09-28T00:00:00+00:00",
                "article_count": 2,
                "source_count": 2,
                "coverage_status": "MULTI_SOURCE",
                "needs_review": False,
            },
            {
                "topic_id": "new_topic",
                "headline_pl": "Nowy tytuł",
                "status": "ACTIVE",
                "first_seen_at": "2026-09-29T00:00:00+00:00",
                "last_seen_at": "2026-09-29T00:00:00+00:00",
                "article_count": 1,
                "source_count": 1,
                "coverage_status": "SINGLE_SOURCE",
                "needs_review": False,
            },
        ]
        links = [
            {"topic_id": "old_topic", "article_id": "old_article_1"},
            {"topic_id": "old_topic", "article_id": "old_article_2"},
            {"topic_id": "new_topic", "article_id": "new_article"},
        ]
        summaries = [{
            "topic_id": "old_topic",
            "summary": {
                "base_summary": {"topic": {"what_happened_one_sentence_pl": "Stara synteza"}},
                "updates": [],
            },
        }]
        client = FakeMergeClient(topics, links, summaries)

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "articles.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE articles (article_id TEXT, title TEXT, source_id TEXT, "
                "published_at TEXT, fetched_at TEXT)"
            )
            conn.executemany(
                "INSERT INTO articles VALUES (?, ?, ?, ?, ?)",
                [
                    ("old_article_1", "Stary artykuł 1", "source_a", "2026-09-01", "2026-09-01"),
                    ("old_article_2", "Stary artykuł 2", "source_b", "2026-09-02", "2026-09-02"),
                    ("new_article", "Nowy artykuł", "source_c", "2026-09-29", "2026-09-29"),
                ],
            )
            conn.commit()
            conn.close()

            with patch.object(
                ai_pipeline,
                "call_openai",
                return_value={
                    "merge_groups": [{
                        "topic_ids": ["old_topic", "new_topic"],
                        "merged_title_pl": "[Polska] Zaktualizowany tytuł",
                        "confidence": 0.95,
                        "categories": ["POLITYKA"],
                    }],
                },
            ):
                stats = merge_active_topics(db_path, "run_merge", client)

        topic_upsert = next(rows for table, rows, _ in client.upserts if table == "topics")
        self.assertEqual(topic_upsert[0]["topic_id"], "old_topic")
        self.assertEqual(topic_upsert[0]["headline_pl"], "[Polska] Zaktualizowany tytuł")
        self.assertEqual(stats["topics_merged"], 2)
        assignment_update = next(
            values for table, values, _ in client.updates
            if table == "article_topic_assignments"
        )
        self.assertEqual(assignment_update["topic_id"], "old_topic")
        self.assertIn("created_at", assignment_update)
        redirect_update = next(
            values for table, values, filters in client.updates
            if table == "topics" and any("new_topic" in value for _, value in filters)
        )
        self.assertEqual(redirect_update["merged_into_topic_id"], "old_topic")
        links_upsert = [
            row
            for table, rows, _ in client.upserts
            if table == "topic_articles"
            for row in rows
        ]
        new_link = next(row for row in links_upsert if row["article_id"] == "new_article")
        self.assertEqual(new_link["topic_id"], "old_topic")
        self.assertIn("assigned_at", new_link)

    def test_categories_only_classify_multi_source_topics(self):
        topics = [
            {"topic_id": "singleton", "headline_pl": "Jeden artykuł", "status": "ACTIVE", "source_count": 1},
            {"topic_id": "multi", "headline_pl": "Wiele źródeł", "status": "ACTIVE", "source_count": 2},
        ]
        client = FakeMergeClient(
            topics,
            [
                {"topic_id": "singleton", "article_id": "article_one"},
                {"topic_id": "multi", "article_id": "article_two"},
                {"topic_id": "multi", "article_id": "article_three"},
            ],
            [],
            [
                {"article_id": "article_two", "title": "Decyzja parlamentu", "source_id": "source_a"},
                {"article_id": "article_three", "title": "Reakcje na decyzję", "source_id": "source_b"},
            ],
        )
        client.rows["topic_categories"] = [
            {"topic_id": "singleton", "category": "POLITYKA"},
        ]
        captured_payload = {}

        def fake_call(instructions, payload, model, **kwargs):
            captured_payload.update(payload)
            self.assertIs(kwargs["response_schema"], ai_pipeline.CATEGORY_RESPONSE_SCHEMA)
            return {"categories": [{"topic_id": "multi", "categories": ["POLITYKA"]}]}

        with patch.object(ai_pipeline, "call_openai", side_effect=fake_call):
            classified = classify_topic_categories(client)

        self.assertEqual(classified, 1)
        self.assertEqual(
            [row["topic_id"] for row in captured_payload["topics"]],
            ["multi"],
        )
        self.assertIn(
            ("topic_categories", [("topic_id", "eq.singleton")]),
            client.deletes,
        )

    def test_large_summary_payload_falls_back_to_metadata(self):
        rows = [
            {
                "article_id": "article_one",
                "title": "Bardzo długi artykuł",
                "body": "ważne słowo " * 1200,
                "source_id": "source_a",
                "source_name": "Źródło A",
                "source_profile": "CENTRAL",
                "original_language": "pl",
                "published_at": "2026-09-29",
                "canonical_url": "https://example.test/article-one",
            },
            {
                "article_id": "article_two",
                "title": "Drugi długi artykuł",
                "body": "inne słowo " * 1200,
                "source_id": "source_b",
                "source_name": "Źródło B",
                "source_profile": "CENTRAL",
                "original_language": "pl",
                "published_at": "2026-09-29",
                "canonical_url": "https://example.test/article-two",
            },
        ]
        original_limit = ai_pipeline.SUMMARY_MAX_PAYLOAD_CHARS
        ai_pipeline.SUMMARY_MAX_PAYLOAD_CHARS = 500
        try:
            payload, payload_chars, payload_mode = build_bounded_summary_input(
                {
                    "topic": {"topic_id": "topic_large"},
                    "previous_aggregation": None,
                    "all_article_ids_in_topic": ["article_one", "article_two"],
                },
                rows,
                rows,
            )
        finally:
            ai_pipeline.SUMMARY_MAX_PAYLOAD_CHARS = original_limit

        self.assertEqual(payload_mode, "same metadane")
        self.assertGreater(payload_chars, 0)
        self.assertEqual(
            [row["article_id"] for row in payload["all_articles"]],
            ["article_one", "article_two"],
        )
        self.assertNotIn("body_original", payload["all_articles"][0])


if __name__ == "__main__":
    unittest.main()
