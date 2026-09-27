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
    parser.add_argument("--max-articles-per-source", type=int, default=50)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--retry-rejected", action="store_true")
    parser.add_argument("--skip-ai", action="store_true")
    parser.add_argument("--ai-max-articles", type=int, default=int(os.environ.get("AI_MAX_ARTICLES_PER_RUN", "100")))
    args = parser.parse_args()

    client = SupabaseRestClient()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    print("[1/4] Pobieram stan deduplikacji z Supabase...", flush=True)
    print(json.dumps(pull_state(args.db, client), ensure_ascii=False), flush=True)

    command = [
        sys.executable, "article_harvester.py", "--config", str(args.config),
        "--db", str(args.db), "--output-dir", str(args.output_dir),
        "--max-articles-per-source", str(args.max_articles_per_source),
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
        print("[4/4] Grupuję tematy i tworzę opracowania AI...", flush=True)
        result = analyze_run(args.db, run_id, client, max_articles=args.ai_max_articles)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
