#!/usr/bin/env python3
"""Move the harvester's durable state between SQLite and Supabase.

GitHub-hosted runners are ephemeral. The worker pulls the de-duplication state
before visiting any source and pushes only the current run's new state after it
finishes. Full article bodies therefore live in Supabase, not in git history.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Iterable

from article_harvester import open_db
from supabase_client import SupabaseRestClient


ARTICLE_COLUMNS = (
    "article_id,source_id,source_name,source_profile,source_type,original_language,"
    "title,body,description,author,original_url,canonical_url,published_at,updated_at,"
    "section,item_kind,content_status,word_count,content_hash,title_key,opening_text,"
    "opening_fingerprint,sentiment,tone_hint,topic_hint,fetch_method,http_status,error,"
    "first_seen_at,fetched_at,last_seen_on_homepage_at"
)


def chunks(rows: list[dict[str, Any]], size: int = 25) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(rows), size):
        yield rows[index:index + size]


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def _bool(value: Any) -> bool:
    return bool(int(value or 0))


def pull_state(db_path: Path, client: SupabaseRestClient) -> dict[str, int]:
    """Pull remote rows needed for local URL/title/opening de-duplication."""
    conn = open_db(db_path)
    counts = {
        "sources": 0, "harvest_runs": 0, "source_run_results": 0,
        "articles": 0, "aliases": 0, "rejected": 0,
    }
    try:
        source_rows = client.select_all("sources")
        for row in source_rows:
            conn.execute(
                "INSERT OR REPLACE INTO sources "
                "(source_id,name,homepage,region,editorial_profile,source_type,enabled,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    row.get("source_id", ""), row.get("name", ""), row.get("homepage", ""),
                    row.get("region", ""), row.get("editorial_profile", "UNCLASSIFIED"),
                    row.get("source_type", "UNCLASSIFIED"), int(bool(row.get("enabled", True))),
                    row.get("updated_at", ""),
                ),
            )
        counts["sources"] = len(source_rows)

        harvest_rows = client.select_all(
            "harvest_runs",
            columns="run_id,started_at,finished_at,status,source_count,discovered_count,fetched_count,skipped_existing_count,valid_article_count,failed_count",
        )
        for row in harvest_rows:
            conn.execute(
                "INSERT OR REPLACE INTO harvest_runs "
                "(run_id,started_at,finished_at,status,source_count,discovered_count,fetched_count,"
                "skipped_existing_count,valid_article_count,failed_count) VALUES (?,?,?,?,?,?,?,?,?,?)",
                tuple(row.get(column) for column in (
                    "run_id", "started_at", "finished_at", "status", "source_count",
                    "discovered_count", "fetched_count", "skipped_existing_count",
                    "valid_article_count", "failed_count",
                )),
            )
        counts["harvest_runs"] = len(harvest_rows)

        result_rows = client.select_all("source_run_results")
        for row in result_rows:
            conn.execute(
                "INSERT OR REPLACE INTO source_run_results "
                "(run_id,source_id,homepage_status,discovered_count,fetched_count,"
                "skipped_existing_count,valid_article_count,failed_count,duplicate_count,"
                "rejected_short_count,discovery_duration_ms,fetch_duration_ms,"
                "total_duration_ms,average_article_fetch_ms,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(row.get(column) for column in (
                    "run_id", "source_id", "homepage_status", "discovered_count",
                    "fetched_count", "skipped_existing_count", "valid_article_count",
                    "failed_count", "duplicate_count", "rejected_short_count",
                    "discovery_duration_ms", "fetch_duration_ms", "total_duration_ms",
                    "average_article_fetch_ms", "notes",
                )),
            )
        counts["source_run_results"] = len(result_rows)

        article_rows = client.select_all("articles", columns=ARTICLE_COLUMNS)
        placeholders = ",".join("?" for _ in ARTICLE_COLUMNS.split(","))
        article_sql = f"INSERT OR REPLACE INTO articles ({ARTICLE_COLUMNS}) VALUES ({placeholders})"
        for row in article_rows:
            conn.execute(article_sql, tuple(row.get(column) for column in ARTICLE_COLUMNS.split(",")))
        counts["articles"] = len(article_rows)

        alias_rows = client.select_all("article_url_aliases")
        for row in alias_rows:
            conn.execute(
                "INSERT OR REPLACE INTO article_url_aliases "
                "(source_id,candidate_url,duplicate_of_article_id,first_seen_at,last_seen_at,reason) "
                "VALUES (?,?,?,?,?,?)",
                tuple(row.get(column, "") for column in (
                    "source_id", "candidate_url", "duplicate_of_article_id",
                    "first_seen_at", "last_seen_at", "reason",
                )),
            )
        counts["aliases"] = len(alias_rows)

        rejected_rows = client.select_all("rejected_candidates")
        for row in rejected_rows:
            conn.execute(
                "INSERT OR REPLACE INTO rejected_candidates "
                "(source_id,canonical_url,title,word_count,opening_fingerprint,reason,first_seen_at,last_seen_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                tuple(row.get(column, "") for column in (
                    "source_id", "canonical_url", "title", "word_count",
                    "opening_fingerprint", "reason", "first_seen_at", "last_seen_at",
                )),
            )
        counts["rejected"] = len(rejected_rows)
        conn.commit()
        return counts
    finally:
        conn.close()


def _push_table(
    client: SupabaseRestClient,
    table: str,
    rows: list[dict[str, Any]],
    conflict: str,
    *,
    batch_size: int = 25,
) -> int:
    for batch in chunks(rows, size=batch_size):
        client.upsert(table, batch, on_conflict=conflict)
    return len(rows)


def push_run(db_path: Path, run_id: str, client: SupabaseRestClient) -> dict[str, int]:
    """Push sources, the current run, and rows created during that run."""
    conn = open_db(db_path)
    counts: dict[str, int] = {}
    try:
        sources = [_row_dict(row) for row in conn.execute("SELECT * FROM sources").fetchall()]
        for row in sources:
            row["enabled"] = _bool(row.get("enabled"))
        counts["sources"] = _push_table(client, "sources", sources, "source_id")

        harvest = conn.execute("SELECT * FROM harvest_runs WHERE run_id = ?", (run_id,)).fetchone()
        counts["harvest_runs"] = _push_table(
            client, "harvest_runs", [_row_dict(harvest)] if harvest else [], "run_id"
        )

        articles = [
            _row_dict(row)
            for row in conn.execute(
                "SELECT a.* FROM articles a JOIN run_articles r ON r.article_id = a.article_id "
                "WHERE r.run_id = ? AND r.fetched_now = 1",
                (run_id,),
            ).fetchall()
        ]
        # Article bodies are the largest payload. Small, idempotent batches keep
        # PostgREST requests below the network timeout and are safe to retry.
        article_batch_size = max(1, int(os.environ.get("SUPABASE_ARTICLE_BATCH_SIZE", "10")))
        counts["articles"] = _push_table(
            client, "articles", articles, "article_id", batch_size=article_batch_size
        )

        run_articles = [_row_dict(row) for row in conn.execute(
            "SELECT * FROM run_articles WHERE run_id = ?", (run_id,)
        ).fetchall()]
        for row in run_articles:
            row["discovered_on_homepage"] = _bool(row.get("discovered_on_homepage"))
            row["fetched_now"] = _bool(row.get("fetched_now"))
        counts["run_articles"] = _push_table(client, "run_articles", run_articles, "run_id,article_id")

        results = [_row_dict(row) for row in conn.execute(
            "SELECT * FROM source_run_results WHERE run_id = ?", (run_id,)
        ).fetchall()]
        counts["source_run_results"] = _push_table(client, "source_run_results", results, "run_id,source_id")

        aliases = [_row_dict(row) for row in conn.execute("SELECT * FROM article_url_aliases").fetchall()]
        counts["aliases"] = _push_table(client, "article_url_aliases", aliases, "source_id,candidate_url")

        rejected = [_row_dict(row) for row in conn.execute("SELECT * FROM rejected_candidates").fetchall()]
        counts["rejected"] = _push_table(client, "rejected_candidates", rejected, "source_id,canonical_url")
        return counts
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize the local harvester state with Supabase.")
    parser.add_argument("direction", choices=("pull", "push"))
    parser.add_argument("--db", type=Path, default=Path("article_harvest/articles.sqlite3"))
    parser.add_argument("--run-id")
    args = parser.parse_args()
    client = SupabaseRestClient()
    if args.direction == "pull":
        print(pull_state(args.db, client))
    else:
        if not args.run_id:
            raise SystemExit("push wymaga --run-id")
        print(push_run(args.db, args.run_id, client))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
