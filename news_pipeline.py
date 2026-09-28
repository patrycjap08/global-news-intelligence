#!/usr/bin/env python3
"""One scheduled production run: pull state -> harvest -> push -> analyze."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import sqlite3
import subprocess
import sys

from ai_pipeline import analyze_run
from article_harvester import open_db
from supabase_client import SupabaseRestClient
from supabase_sync import pull_state, push_run


def latest_run_id(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT run_id FROM harvest_runs ORDER BY started_at DESC LIMIT 1").fetchone()
        if not row:
            raise RuntimeError("Harvester nie utworzył harvest_run.")
        return str(row[0])
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Global News Intelligence ingestion pipeline.")
    parser.add_argument("--config", type=Path, default=Path("sources.yaml"))
    parser.add_argument("--db", type=Path, default=Path("article_harvest/articles.sqlite3"))
    parser.add_argument("--output-dir", type=Path, default=Path("article_harvest"))
    parser.add_argument(
        "--daily-max-articles-per-source",
        type=int,
        default=int(os.environ.get("HARVEST_DAILY_MAX_ARTICLES_PER_SOURCE", "30")),
        help="Maximum number of new fetch attempts per source during one UTC day.",
    )
    parser.add_argument(
        "--top-articles-per-source",
        type=int,
        default=int(os.environ.get("HARVEST_TOP_ARTICLES_PER_SOURCE_PER_RUN", "10")),
        help="Only inspect the first N discovered articles per source in this run.",
    )
    parser.add_argument("--discovery-limit-per-source", type=int, default=500)
    parser.add_argument("--max-sitemap-probes", type=int, default=6)
    parser.add_argument("--max-sitemap-children", type=int, default=3)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--retry-rejected", action="store_true")
    parser.add_argument("--skip-ai", action="store_true")
    parser.add_argument(
        "--ai-only", action="store_true",
        help="Pomiń pobieranie źródeł i uruchom AI na artykułach już zapisanych w Supabase.",
    )
    parser.add_argument(
        "--rebuild-summaries", action="store_true",
        help="Pomiń harvesting i grupowanie; wygeneruj od nowa syntezy istniejących tematów wieloartykułowych.",
    )
    parser.add_argument("--ai-max-articles", type=int, default=int(os.environ.get("AI_MAX_ARTICLES_PER_RUN", "0")))
    parser.add_argument("--ai-batch-size", type=int, default=int(os.environ.get("AI_BATCH_SIZE", "100")))
    parser.add_argument(
        "--rebuild-max-topics",
        type=int,
        default=int(os.environ.get("AI_REBUILD_MAX_TOPICS", "0")),
    )
    args = parser.parse_args()

    if args.ai_only and args.skip_ai:
        parser.error("--ai-only nie może być użyte razem z --skip-ai.")
    if args.rebuild_summaries and not args.ai_only:
        parser.error("--rebuild-summaries wymaga także --ai-only, aby nie uruchomić harvestera.")

    client = SupabaseRestClient()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    print("[1/4] Pobieram stan deduplikacji z Supabase...", flush=True)
    print(json.dumps(pull_state(args.db, client), ensure_ascii=False), flush=True)

    if args.ai_only:
        run_id = latest_run_id(args.db)
        print(f"[2/4] Pobieranie źródeł pominięte; używam run {run_id}...", flush=True)
        print("[3/4] Synchronizacja harvestera pominięta; artykuły są już w Supabase.", flush=True)
    else:
        command = [
            sys.executable, "article_harvester.py", "--config", str(args.config),
            "--db", str(args.db), "--output-dir", str(args.output_dir),
            "--runtime-config", "source_runtime.yaml",
            "--daily-max-articles-per-source", str(args.daily_max_articles_per_source),
            "--top-articles-per-source", str(args.top_articles_per_source),
            "--discovery-limit-per-source", str(args.discovery_limit_per_source),
            "--max-sitemap-probes", str(args.max_sitemap_probes),
            "--max-sitemap-children", str(args.max_sitemap_children),
        ]
        if args.browser:
            command.append("--browser")
        if args.retry_failed:
            command.append("--retry-failed")
        if args.retry_rejected:
            command.append("--retry-rejected")
        print("[2/4] Pobieram strony główne i nowe artykuły...", flush=True)
        subprocess.run(command, check=True)
        run_id = latest_run_id(args.db)

        print(f"[3/4] Zapisuję run {run_id} w Supabase...", flush=True)
        print(json.dumps(push_run(args.db, run_id, client), ensure_ascii=False), flush=True)

    if args.skip_ai:
        print("[4/4] AI pominięte przez --skip-ai.", flush=True)
    else:
        if args.rebuild_summaries:
            print("[4/4] Przepisuję syntezy istniejących tematów AI...", flush=True)
        else:
            print("[4/4] Grupuję tematy i tworzę opracowania AI...", flush=True)
        result = analyze_run(
            args.db, run_id, client,
            max_articles=args.ai_max_articles,
            batch_size=args.ai_batch_size,
            rebuild_summaries_mode=args.rebuild_summaries,
            rebuild_max_topics=args.rebuild_max_topics,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
