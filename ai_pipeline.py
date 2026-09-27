#!/usr/bin/env python3
"""Two-stage OpenAI processing for the harvested articles.

The worker deliberately stores model output as JSON and keeps article_ids next
to claims. This makes the UI able to show the evidence instead of presenting a
citation-free model narrative.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

from supabase_client import SupabaseRestClient


PROMPT_VERSION = "ai-prompts-v1"
DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

GROUPING_INSTRUCTIONS = """
Jesteś modułem grupowania wiadomości w aplikacji Global News Intelligence.
Pracujesz wyłącznie na przekazanych artykułach. Połącz materiały tylko wtedy,
gdy dotyczą tego samego konkretnego wydarzenia, decyzji, wypowiedzi albo
rozwoju tej samej sprawy. Sama wspólna osoba, państwo, partia lub słowo
tematyczne nie wystarcza. Treść ma pierwszeństwo przed nagłówkiem.

Zwróć WYŁĄCZNIE poprawny JSON:
{"groups":[{"group_id":"new_group_001","existing_topic_id":"",
"working_title_pl":"neutralna nazwa wydarzenia","article_ids":["..."],
"confidence":0.0,"needs_review":false,"grouping_reason":"..."}],
"unassigned_article_ids":[],"possible_merges":[]}

Każdy article_id z wejścia ma wystąpić dokładnie raz: w jednej grupie albo w
unassigned_article_ids. Nie wymyślaj faktów. Jeśli dopasowanie do istniejącego
tematu jest niepewne, zostaw existing_topic_id puste i ustaw needs_review.
Profil źródła służy wyłącznie do opisu perspektywy, nie do łączenia artykułów.
""".strip()

SUMMARY_INSTRUCTIONS = """
Jesteś redaktorem analitycznym aplikacji Global News Intelligence. Przygotuj
neutralne polskie opracowanie jednego tematu wyłącznie na podstawie
dostarczonych artykułów. Każde istotne twierdzenie musi mieć article_ids.
Pokaż osobno fakty zgodne, informacje jednostkowe, różnice i sprzeczności.
Nie rozstrzygaj, które źródło ma rację. Profil lewicowe/prawicowe/centralne
służy wyłącznie do pokazania sposobu przedstawienia tematu.

Nie nazywaj artykułu kłamliwym. Możesz wskazać konkretny sygnał wymagający
sprawdzenia: wartościujący język, brak kontekstu, nagłówek mocniejszy niż
treść, niezweryfikowane twierdzenie albo konflikt z innym materiałem. Nie
wymyślaj cytatów ani informacji spoza artykułów. Kontekst ogólny wpisz tylko
do background_context i oznacz needs_verification=true.

Zwróć WYŁĄCZNIE poprawny JSON o następującej strukturze:
{"topic":{"headline_pl":"","what_happened_one_sentence_pl":"",
"status":"ONGOING","time_scope":""},"summary_pl":"","timeline":[],
"facts":[],"agreement":[],"differences":[],"framing_and_tone":[],
"potential_manipulation_signals":[],"contradictions":[],
"background_context":[],"unknowns":[],"sources":[],
"quality":{"article_count":0,"source_count":0,
"has_multiple_perspectives":false,"overall_confidence":"MEDIUM",
"limitations_pl":""}}
""".strip()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract_json(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"AI nie zwróciło JSON: {cleaned[:400]}") from exc
        value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("AI zwróciło JSON inny niż obiekt.")
    return value


def call_openai(instructions: str, payload: dict[str, Any], model: str) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=json.dumps(payload, ensure_ascii=False),
    )
    return extract_json(response.output_text)


def local_articles(conn: sqlite3.Connection, article_ids: list[str] | None = None) -> list[dict[str, Any]]:
    if article_ids is None:
        rows = conn.execute(
            "SELECT * FROM articles WHERE content_status IN ('COMPLETE','EXCERPT') "
            "AND word_count >= 200 ORDER BY fetched_at, article_id"
        ).fetchall()
    else:
        if not article_ids:
            return []
        marks = ",".join("?" for _ in article_ids)
        rows = conn.execute(f"SELECT * FROM articles WHERE article_id IN ({marks})", article_ids).fetchall()
    return [dict(row) for row in rows]


def article_for_ai(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": row["article_id"],
        "title_original": row["title"],
        "body_original": row["body"],
        "source_id": row["source_id"],
        "source_name": row["source_name"],
        "source_profile": row.get("source_profile") or "UNCLASSIFIED",
        "language": row["original_language"],
        "published_at": row.get("published_at") or "",
        "canonical_url": row["canonical_url"],
    }


def active_topic_payload(client: SupabaseRestClient) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    topics = client.select_all("topics", filters=[("status", "eq.ACTIVE")])
    links = client.select_all("topic_articles", columns="topic_id,article_id")
    link_map: dict[str, list[str]] = {}
    for row in links:
        link_map.setdefault(str(row["topic_id"]), []).append(str(row["article_id"]))
    payload = [
        {
            "topic_id": row["topic_id"],
            "representative_title_pl": row.get("headline_pl", ""),
            "last_seen_at": row.get("last_seen_at", ""),
            "article_count": row.get("article_count", 0),
        }
        for row in topics
    ]
    return payload, link_map


def pending_articles(conn: sqlite3.Connection, client: SupabaseRestClient, limit: int) -> list[dict[str, Any]]:
    assigned_rows = client.select_all("article_topic_assignments", columns="article_id")
    assigned = {str(row["article_id"]) for row in assigned_rows}
    articles = [row for row in local_articles(conn) if row["article_id"] not in assigned]
    return articles[:limit] if limit > 0 else articles


def stable_topic_id(article_ids: list[str], title: str) -> str:
    return "topic_" + digest({"article_ids": sorted(article_ids), "title": title})[:24]


def analyze_run(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
    max_articles: int = 100,
) -> dict[str, int]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Brakuje OPENAI_API_KEY; AI nie może zostać uruchomione.")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = {"pending_articles": 0, "groups": 0, "summaries": 0, "skipped_summaries": 0}
    try:
        articles = pending_articles(conn, client, max_articles)
        stats["pending_articles"] = len(articles)
        if not articles:
            return stats
        active_topics, topic_links = active_topic_payload(client)
        grouping_input = {
            "new_articles": [article_for_ai(row) for row in articles],
            "active_topics": active_topics,
        }
        grouping_hash = digest(grouping_input)
        grouping_topic_run_id = "topicrun_" + digest({"run": run_id, "stage": "GROUPING", "input": grouping_hash})[:24]
        try:
            grouping = call_openai(GROUPING_INSTRUCTIONS, grouping_input, model)
            client.upsert("topic_runs", [{
                "topic_run_id": grouping_topic_run_id, "run_id": run_id,
                "stage": "GROUPING", "prompt_version": PROMPT_VERSION,
                "model": model, "input_hash": grouping_hash, "status": "COMPLETED",
                "raw_output": grouping, "error": None,
            }], on_conflict="topic_run_id")
        except Exception as exc:
            client.upsert("topic_runs", [{
                "topic_run_id": grouping_topic_run_id, "run_id": run_id,
                "stage": "GROUPING", "prompt_version": PROMPT_VERSION,
                "model": model, "input_hash": grouping_hash, "status": "FAILED",
                "raw_output": None, "error": str(exc)[:2000],
            }], on_conflict="topic_run_id")
            raise

        input_by_id = {row["article_id"]: row for row in articles}
        groups = grouping.get("groups") if isinstance(grouping.get("groups"), list) else []
        assigned_ids: set[str] = set()
        topic_rows: list[dict[str, Any]] = []
        link_rows: list[dict[str, Any]] = []
        assignment_rows: list[dict[str, Any]] = []
        group_data: list[tuple[str, str, list[str], bool]] = []
        for index, group in enumerate(groups, 1):
            if not isinstance(group, dict):
                continue
            ids = [str(value) for value in group.get("article_ids", []) if str(value) in input_by_id and str(value) not in assigned_ids]
            if not ids:
                continue
            assigned_ids.update(ids)
            title = str(group.get("working_title_pl") or "Temat bez tytułu").strip()[:300]
            topic_id = str(group.get("existing_topic_id") or "").strip() or stable_topic_id(ids, title)
            confidence = float(group.get("confidence") or 0)
            needs_review = bool(group.get("needs_review", False))
            existing_ids = topic_links.get(topic_id, [])
            all_ids = list(dict.fromkeys(existing_ids + ids))
            source_ids = {input_by_id[article_id]["source_id"] for article_id in ids}
            topic_rows.append({
                "topic_id": topic_id, "headline_pl": title, "status": "ACTIVE",
                "first_seen_at": now(), "last_seen_at": now(), "article_count": len(all_ids),
                "source_count": len(source_ids), "needs_review": needs_review, "updated_at": now(),
            })
            link_rows.extend({"topic_id": topic_id, "article_id": article_id, "confidence": confidence} for article_id in ids)
            assignment_rows.extend({
                "run_id": run_id, "article_id": article_id, "topic_id": topic_id,
                "confidence": confidence, "needs_review": needs_review,
                "grouping_reason": str(group.get("grouping_reason") or "")[:1000],
                "prompt_version": PROMPT_VERSION,
            } for article_id in ids)
            group_data.append((topic_id, title, all_ids, needs_review))

        client.upsert("topics", topic_rows, on_conflict="topic_id")
        client.upsert("topic_articles", link_rows, on_conflict="topic_id,article_id")
        client.upsert("article_topic_assignments", assignment_rows, on_conflict="run_id,article_id")
        stats["groups"] = len(group_data)

        for topic_id, title, all_ids, needs_review in group_data:
            rows = local_articles(conn, all_ids)
            if not rows:
                continue
            summary_input = {
                "topic": {"topic_id": topic_id, "working_title_pl": title},
                "articles": [article_for_ai(row) for row in rows],
            }
            summary_hash = digest(summary_input)
            old = client.select("topic_summaries", filters=[("topic_id", f"eq.{topic_id}")], limit=1)
            if old and old[0].get("input_hash") == summary_hash:
                stats["skipped_summaries"] += 1
                continue
            summary_topic_run_id = "topicrun_" + digest({"topic": topic_id, "stage": "SUMMARY", "input": summary_hash})[:24]
            try:
                summary = call_openai(SUMMARY_INSTRUCTIONS, summary_input, model)
                client.upsert("topic_summaries", [{
                    "topic_id": topic_id, "version": int(old[0].get("version", 0)) + 1 if old else 1,
                    "input_hash": summary_hash, "model": model, "summary": summary,
                    "generated_at": now(), "updated_at": now(),
                }], on_conflict="topic_id")
                client.upsert("topic_runs", [{
                    "topic_run_id": summary_topic_run_id, "run_id": run_id,
                    "stage": "SUMMARY", "prompt_version": PROMPT_VERSION,
                    "model": model, "input_hash": summary_hash, "status": "COMPLETED",
                    "raw_output": summary, "error": None,
                }], on_conflict="topic_run_id")
                stats["summaries"] += 1
            except Exception as exc:
                client.upsert("topic_runs", [{
                    "topic_run_id": summary_topic_run_id, "run_id": run_id,
                    "stage": "SUMMARY", "prompt_version": PROMPT_VERSION,
                    "model": model, "input_hash": summary_hash, "status": "FAILED",
                    "raw_output": None, "error": str(exc)[:2000],
                }], on_conflict="topic_run_id")
                raise
        return stats
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the two OpenAI analysis stages for pending articles.")
    parser.add_argument("--db", type=Path, default=Path("article_harvest/articles.sqlite3"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-articles", type=int, default=int(os.environ.get("AI_MAX_ARTICLES_PER_RUN", "100")))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    client = SupabaseRestClient()
    print(json.dumps(analyze_run(args.db, args.run_id, client, model=args.model, max_articles=args.max_articles), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
