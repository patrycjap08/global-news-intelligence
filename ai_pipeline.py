#!/usr/bin/env python3
"""Two-stage OpenAI processing for the harvested articles.

The worker deliberately stores model output as JSON and keeps article_ids next
to claims. This makes the UI able to show the evidence instead of presenting a
citation-free model narrative.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

from supabase_client import SupabaseRestClient


PROMPT_VERSION = "ai-prompts-v3-excerpt-and-relevance"
TOPIC_LOOKBACK_DAYS = 3
DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
GROUPING_EXCERPT_WORDS = max(20, int(os.environ.get("AI_GROUPING_EXCERPT_WORDS", "100")))
MIN_ARTICLE_WORDS = 100

GROUPING_INSTRUCTIONS = """
Jesteś modułem grupowania wiadomości w aplikacji Global News Intelligence.
Pracujesz wyłącznie na przekazanych artykułach. Połącz materiały tylko wtedy,
gdy dotyczą tego samego konkretnego wydarzenia, decyzji, wypowiedzi albo
rozwoju tej samej sprawy. Sama wspólna osoba, państwo, partia lub słowo
tematyczne nie wystarcza. Treść ma pierwszeństwo przed nagłówkiem.

Najpierw odrzuć materiały wyraźnie niezwiązane z głównym zakresem aplikacji:
sport, celebryci, rozrywka, lifestyle, przepisy, zwykłe treści konsumenckie i
inne materiały bez znaczenia dla polityki, gospodarki, bezpieczeństwa,
dyplomacji, konfliktów, prawa publicznego lub istotnych wydarzeń społecznych.
Jeżeli związek jest niepewny, nie odrzucaj materiału — zostaw go w grupie lub
unassigned_article_ids i ustaw needs_review.

Treść artykułu w tym etapie jest tylko krótkim wyciągiem pierwszych około 100
słów, więc nie dopowiadaj faktów, których nie ma w wyciągu.

Zwróć WYŁĄCZNIE poprawny JSON:
{"groups":[{"group_id":"new_group_001","existing_topic_id":"",
"topic_action":"NEW_TOPIC|DEVELOPMENT|BACKGROUND_OR_CONTEXT",
"working_title_pl":"neutralna nazwa wydarzenia","article_ids":["..."],
"confidence":0.0,"needs_review":false,"grouping_reason":"..."}],
"unassigned_article_ids":[],"excluded_articles":[{"article_id":"...",
"category":"SPORT|CELEBRITY|ENTERTAINMENT|LIFESTYLE|OTHER_NON_CORE",
"reason":"krótkie uzasadnienie"}],"possible_merges":[]}

Każdy article_id z wejścia ma wystąpić dokładnie raz: w jednej grupie,
unassigned_article_ids albo excluded_articles. Najpierw sprawdź active_topics
z ostatnich trzech dni.
Jeżeli artykuł jest dalszym ciągiem istniejącego tematu, wpisz jego topic_id i
topic_action=DEVELOPMENT. Jeżeli tylko uzupełnia kontekst lub wcześniejszą
agregację, wpisz topic_action=BACKGROUND_OR_CONTEXT. Nowe wydarzenie ma
topic_action=NEW_TOPIC i pusty existing_topic_id.

Nie twórz nowego tematu tylko dlatego, że artykuł pojawił się w kolejnym
uruchomieniu tego samego dnia. Jeśli dopasowanie do istniejącego tematu jest
niepewne, zostaw existing_topic_id puste i ustaw needs_review. Profil źródła
służy wyłącznie do opisu perspektywy, nie do łączenia artykułów.
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

Jeżeli wejście zawiera previous_aggregation, potraktuj ją jako poprzednią
wersję roboczą tego samego tematu. Zachowaj nadal prawidłowe fakty, dodaj nowe
informacje, pokaż korekty i konflikty. Nie twórz drugiego tematu dla dalszego
ciągu tej samej historii. Dla nowych tematów previous_aggregation będzie null.
Pole new_articles zawiera materiały z bieżącego uruchomienia. Pole
all_articles jest obecne przy pierwszym opracowaniu tematu; przy aktualizacji
starsze materiały są reprezentowane przez previous_aggregation i ich article_id.

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
            "AND word_count >= ? ORDER BY fetched_at, article_id",
            (MIN_ARTICLE_WORDS,),
        ).fetchall()
    else:
        if not article_ids:
            return []
        marks = ",".join("?" for _ in article_ids)
        rows = conn.execute(f"SELECT * FROM articles WHERE article_id IN ({marks})", article_ids).fetchall()
    return [dict(row) for row in rows]


def first_words(text: str, limit: int) -> str:
    words = (text or "").split()
    return " ".join(words[:limit])


def article_for_ai(
    row: dict[str, Any],
    *,
    excerpt_words_limit: int | None = None,
) -> dict[str, Any]:
    payload = {
        "article_id": row["article_id"],
        "title_original": row["title"],
        "source_id": row["source_id"],
        "source_name": row["source_name"],
        "source_profile": row.get("source_profile") or "UNCLASSIFIED",
        "language": row["original_language"],
        "published_at": row.get("published_at") or "",
        "canonical_url": row["canonical_url"],
    }
    if excerpt_words_limit is None:
        payload["body_original"] = row["body"]
    else:
        payload["body_excerpt_original"] = first_words(row.get("body") or "", excerpt_words_limit)
        payload["excerpt_word_limit"] = excerpt_words_limit
    return payload


def active_topic_payload(
    client: SupabaseRestClient,
) -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, dict[str, Any]]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=TOPIC_LOOKBACK_DAYS)).isoformat()
    topics = client.select_all(
        "topics",
        filters=[("status", "eq.ACTIVE"), ("last_seen_at", f"gte.{cutoff}")],
    )
    summaries = client.select_all("topic_summaries", columns="topic_id,summary")
    summary_by_topic = {str(row["topic_id"]): row.get("summary") for row in summaries}
    links = client.select_all("topic_articles", columns="topic_id,article_id")
    link_map: dict[str, list[str]] = {}
    for row in links:
        link_map.setdefault(str(row["topic_id"]), []).append(str(row["article_id"]))

    payload: list[dict[str, Any]] = []
    topic_context: dict[str, dict[str, Any]] = {}
    for row in topics:
        topic_id = str(row["topic_id"])
        previous = summary_by_topic.get(topic_id)
        if not isinstance(previous, dict):
            previous = {}
        previous_topic = previous.get("topic") if isinstance(previous.get("topic"), dict) else {}
        context = {
            "topic_id": topic_id,
            "representative_title_pl": row.get("headline_pl", ""),
            "last_seen_at": row.get("last_seen_at", ""),
            "first_seen_at": row.get("first_seen_at", ""),
            "article_count": row.get("article_count", 0),
            "previous_headline_pl": previous_topic.get("headline_pl", ""),
            "previous_one_sentence_pl": previous_topic.get("what_happened_one_sentence_pl", ""),
            "previous_summary_pl": str(previous.get("summary_pl", ""))[:4000],
        }
        payload.append(context)
        topic_context[topic_id] = context
    return payload, link_map, topic_context


def pending_articles(conn: sqlite3.Connection, client: SupabaseRestClient, limit: int) -> list[dict[str, Any]]:
    assigned_rows = client.select_all("article_topic_assignments", columns="article_id")
    assigned = {str(row["article_id"]) for row in assigned_rows}
    articles = [
        row for row in local_articles(conn)
        if row["article_id"] not in assigned
        and not str(row.get("topic_hint") or "").startswith("AI_EXCLUDED:")
    ]
    return articles[:limit] if limit > 0 else articles


def mark_excluded_articles(
    conn: sqlite3.Connection,
    client: SupabaseRestClient,
    articles: list[dict[str, Any]],
    excluded: list[Any],
) -> set[str]:
    """Persist AI exclusions locally and in Supabase without creating topics."""
    input_ids = {str(row["article_id"]) for row in articles}
    grouped: dict[str, list[str]] = {}
    excluded_ids: set[str] = set()
    for item in excluded:
        if not isinstance(item, dict):
            continue
        article_id = str(item.get("article_id") or "")
        if article_id not in input_ids:
            continue
        category = str(item.get("category") or "OTHER_NON_CORE").upper()
        category = re.sub(r"[^A-Z0-9_]+", "_", category)[:40] or "OTHER_NON_CORE"
        reason = re.sub(r"\s+", " ", str(item.get("reason") or ""))[:180]
        marker = f"AI_EXCLUDED:{category}" + (f":{reason}" if reason else "")
        conn.execute("UPDATE articles SET topic_hint = ? WHERE article_id = ?", (marker, article_id))
        grouped.setdefault(marker, []).append(article_id)
        excluded_ids.add(article_id)
    conn.commit()
    for marker, article_ids in grouped.items():
        for offset in range(0, len(article_ids), 100):
            ids = article_ids[offset:offset + 100]
            client.update(
                "articles",
                {"topic_hint": marker},
                filters=[("article_id", f"in.({','.join(ids)})")],
            )
    return excluded_ids


def stable_topic_id(article_ids: list[str], title: str) -> str:
    return "topic_" + digest({"article_ids": sorted(article_ids), "title": title})[:24]


def _analyze_pending_batch(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    articles: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    batch_index: int = 1,
) -> dict[str, int]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Brakuje OPENAI_API_KEY; AI nie może zostać uruchomione.")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = {"pending_articles": 0, "groups": 0, "summaries": 0, "skipped_summaries": 0, "excluded": 0}
    try:
        stats["pending_articles"] = len(articles)
        if not articles:
            return stats
        active_topics, topic_links, topic_context = active_topic_payload(client)
        grouping_input = {
            "new_articles": [
                article_for_ai(row, excerpt_words_limit=GROUPING_EXCERPT_WORDS)
                for row in articles
            ],
            "active_topics": active_topics,
            "topic_memory_window_days": TOPIC_LOOKBACK_DAYS,
        }
        grouping_hash = digest(grouping_input)
        grouping_topic_run_id = "topicrun_" + digest({
            "run": run_id, "stage": "GROUPING", "batch": batch_index, "input": grouping_hash,
        })[:24]
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
        excluded_ids = mark_excluded_articles(
            conn, client, articles,
            grouping.get("excluded_articles") if isinstance(grouping.get("excluded_articles"), list) else [],
        )
        stats["excluded"] = len(excluded_ids)
        groups = grouping.get("groups") if isinstance(grouping.get("groups"), list) else []
        assigned_ids: set[str] = set()
        topic_rows: list[dict[str, Any]] = []
        link_rows: list[dict[str, Any]] = []
        assignment_rows: list[dict[str, Any]] = []
        group_data: list[dict[str, Any]] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            ids = [
                str(value) for value in group.get("article_ids", [])
                if str(value) in input_by_id
                and str(value) not in excluded_ids
                and str(value) not in assigned_ids
            ]
            if not ids:
                continue
            assigned_ids.update(ids)
            title = str(group.get("working_title_pl") or "Temat bez tytułu").strip()[:300]
            topic_id = str(group.get("existing_topic_id") or "").strip() or stable_topic_id(ids, title)
            topic_action = str(group.get("topic_action") or ("DEVELOPMENT" if group.get("existing_topic_id") else "NEW_TOPIC")).strip()
            if topic_action not in {"NEW_TOPIC", "DEVELOPMENT", "BACKGROUND_OR_CONTEXT"}:
                topic_action = "DEVELOPMENT" if group.get("existing_topic_id") else "NEW_TOPIC"
            confidence = float(group.get("confidence") or 0)
            needs_review = bool(group.get("needs_review", False))
            existing_ids = topic_links.get(topic_id, [])
            all_ids = list(dict.fromkeys(existing_ids + ids))
            all_rows = local_articles(conn, all_ids)
            source_ids = {row["source_id"] for row in all_rows}
            existing_context = topic_context.get(topic_id, {})
            topic_rows.append({
                "topic_id": topic_id, "headline_pl": title, "status": "ACTIVE",
                "first_seen_at": existing_context.get("first_seen_at") or now(),
                "last_seen_at": now(), "article_count": len(all_ids),
                "source_count": len(source_ids), "needs_review": needs_review, "updated_at": now(),
            })
            link_rows.extend({"topic_id": topic_id, "article_id": article_id, "confidence": confidence} for article_id in ids)
            assignment_rows.extend({
                "run_id": run_id, "article_id": article_id, "topic_id": topic_id,
                "confidence": confidence, "needs_review": needs_review,
                "grouping_reason": str(group.get("grouping_reason") or "")[:1000],
                "prompt_version": PROMPT_VERSION,
            } for article_id in ids)
            group_data.append({
                "topic_id": topic_id,
                "title": title,
                "all_ids": all_ids,
                "new_ids": ids,
                "needs_review": needs_review,
                "topic_action": topic_action,
            })

        client.upsert("topics", topic_rows, on_conflict="topic_id")
        client.upsert("topic_articles", link_rows, on_conflict="topic_id,article_id")
        client.upsert("article_topic_assignments", assignment_rows, on_conflict="run_id,article_id")
        stats["groups"] = len(group_data)

        for group in group_data:
            topic_id = group["topic_id"]
            title = group["title"]
            all_ids = group["all_ids"]
            new_rows = local_articles(conn, group["new_ids"])
            all_rows = local_articles(conn, all_ids)
            if not new_rows or not all_rows:
                continue
            old = client.select("topic_summaries", filters=[("topic_id", f"eq.{topic_id}")], limit=1)
            previous_aggregation = old[0].get("summary") if old else None
            summary_input = {
                "topic": {
                    "topic_id": topic_id,
                    "working_title_pl": title,
                    "topic_action": group["topic_action"],
                },
                "previous_aggregation": previous_aggregation,
                "new_articles": [article_for_ai(row) for row in new_rows],
                "all_article_ids_in_topic": all_ids,
            }
            if previous_aggregation is None:
                summary_input["all_articles"] = [article_for_ai(row) for row in all_rows]
            summary_hash = digest(summary_input)
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


def analyze_run(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
    max_articles: int = 0,
    batch_size: int = 100,
) -> dict[str, int]:
    """Process the whole pending queue in context-safe AI batches.

    ``max_articles=0`` means all pending articles. Batches are deliberately
    processed in one workflow, and each next batch reloads active topics so it
    can attach follow-up articles to topics created by the previous batch.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Brakuje OPENAI_API_KEY; AI nie może zostać uruchomiona.")
    batch_size = max(1, batch_size)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        articles = pending_articles(conn, client, max_articles)
    finally:
        conn.close()

    stats = {
        "pending_articles": len(articles), "groups": 0,
        "summaries": 0, "skipped_summaries": 0, "excluded": 0,
    }
    if not articles:
        return stats

    total_batches = (len(articles) + batch_size - 1) // batch_size
    for offset in range(0, len(articles), batch_size):
        batch_index = offset // batch_size + 1
        batch = articles[offset:offset + batch_size]
        print(
            f"[AI] Paczka {batch_index}/{total_batches}: {len(batch)} artykułów...",
            flush=True,
        )
        batch_stats = _analyze_pending_batch(
            db_path, run_id, client, batch, model=model, batch_index=batch_index
        )
        for key in ("groups", "summaries", "skipped_summaries", "excluded"):
            stats[key] += batch_stats[key]
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the two OpenAI analysis stages for pending articles.")
    parser.add_argument("--db", type=Path, default=Path("article_harvest/articles.sqlite3"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-articles", type=int, default=int(os.environ.get("AI_MAX_ARTICLES_PER_RUN", "0")))
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("AI_BATCH_SIZE", "100")))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    client = SupabaseRestClient()
    print(json.dumps(analyze_run(
        args.db, args.run_id, client, model=args.model,
        max_articles=args.max_articles, batch_size=args.batch_size,
    ), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
