#!/usr/bin/env python3
"""One scheduled production run: pull state -> harvest -> push -> analyze."""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import sqlite3
import subprocess
import sys

from ai_pipeline import analyze_run, normalize_topic_titles
from pipeline_logging import log
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


def count_summary(values: dict[str, int], labels: tuple[tuple[str, str], ...]) -> str:
    """Render selected counters without dumping an opaque JSON object."""
    return ", ".join(
        f"{label}: {values[key]}"
        for key, label in labels
        if key in values
    )


def ai_summary(values: dict[str, int]) -> str:
    labels = (
        ("pending_articles", "oczekujące artykuły"),
        ("labeled_articles", "nazwane artykuły"),
        ("candidate_topics", "kandydackie tematy"),
        ("local_candidate_groups", "grupy kandydackie"),
        ("largest_candidate_group", "największa grupa kandydacka"),
        ("merge_requests", "zapytania o scalanie"),
        ("merge_split_retries", "podziały paczek po ucięciu odpowiedzi"),
        ("merge_failed", "nieudane paczki scalania"),
        ("summaries", "gotowe syntezy"),
        ("topics_rebuilt", "przebudowane syntezy"),
        ("failed_summaries", "nieudane syntezy"),
        ("topics_merged", "scalone tematy"),
        ("categories_classified", "uzupełnione kategorie"),
        ("excluded", "wykluczone artykuły"),
        ("repair_candidates", "artykuły do naprawy"),
        ("singleton_topics_merged", "naprawione osobne tematy"),
    )
    return count_summary(values, labels)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Global News Intelligence ingestion pipeline.")
    parser.add_argument("--config", type=Path, default=Path("sources.yaml"))
    parser.add_argument("--db", type=Path, default=Path("article_harvest/articles.sqlite3"))
    parser.add_argument("--output-dir", type=Path, default=Path("article_harvest"))
    parser.add_argument(
        "--daily-max-articles-per-source",
        type=int,
        default=0,
        help="Deprecated compatibility option. Zero disables the former daily limit.",
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
        "--titles-only", action="store_true",
        help="Pomiń harvesting i ujednolić wyłącznie prefiksy geograficzne tytułów.",
    )
    parser.add_argument(
        "--merge-existing-summaries", action="store_true",
        help=(
            "Sprawdź wyłącznie aktywne wątki z syntezami, scal podobne wątki "
            "i zaktualizuj zachowaną najstarszą syntezę."
        ),
    )
    parser.add_argument("--ai-max-articles", type=int, default=int(os.environ.get("AI_MAX_ARTICLES_PER_RUN", "0")))
    parser.add_argument("--ai-batch-size", type=int, default=int(os.environ.get("AI_BATCH_SIZE", "100")))
    parser.add_argument(
        "--merge-existing-max-topics",
        type=int,
        default=int(os.environ.get("AI_EXISTING_TOPIC_MERGE_MAX_TOPICS", "0")),
        help="Opcjonalne ograniczenie liczby aktywnych tematów z syntezami; 0 oznacza wszystkie.",
    )
    args = parser.parse_args()

    if args.ai_only and args.skip_ai:
        parser.error("--ai-only nie może być użyte razem z --skip-ai.")
    if args.titles_only and (args.ai_only or args.merge_existing_summaries or args.skip_ai):
        parser.error("--titles-only jest osobnym trybem.")
    if args.merge_existing_summaries and not args.ai_only:
        parser.error("--merge-existing-summaries wymaga także --ai-only, aby nie uruchomić harvestera.")

    client = SupabaseRestClient()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    log("RUN", "Etap 1/4 — pobieram stan deduplikacji z Supabase.")
    pull_counts = pull_state(args.db, client)
    log(
        "RUN",
        "Etap 1/4 zakończony: " + count_summary(
            pull_counts,
            (("articles", "artykułów"), ("aliases", "aliasów URL"), ("rejected", "odrzuconych adresów")),
        ) + ".",
    )

    if args.titles_only:
        log("RUN", "Etap 2/4 pominięty — tryb tylko tytułów.")
        log("RUN", "Etap 3/4 pominięty — tryb tylko tytułów.")
        log("RUN", "Etap 4/4 — ujednolicam prefiksy geograficzne tytułów.")
        changed = normalize_topic_titles(client)
        log("RUN", f"Etap 4/4 zakończony: poprawiono {changed} tytułów.")
        log("RUN", "Cały przebieg zakończony pomyślnie.")
        return 0
    if args.ai_only:
        run_id = latest_run_id(args.db)
        log("RUN", f"Etap 2/4 pominięty — używam run {run_id}; artykuły są już pobrane.")
        log("RUN", "Etap 3/4 pominięty — synchronizacja harvestera nie jest potrzebna w trybie AI-only.")
    else:
        command = [
            sys.executable, "article_harvester.py", "--config", str(args.config),
            "--db", str(args.db), "--output-dir", str(args.output_dir),
            "--runtime-config", "source_runtime.yaml",
            "--daily-max-articles-per-source", "0",
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
        log("RUN", "Etap 2/4 — pobieram strony główne i nowe artykuły.")
        subprocess.run(command, check=True)
        run_id = latest_run_id(args.db)
        log("RUN", f"Etap 2/4 zakończony: run {run_id} zapisany lokalnie.")

        log("RUN", f"Etap 3/4 — zapisuję run {run_id} w Supabase.")
        push_counts = push_run(args.db, run_id, client)
        log(
            "RUN",
            "Etap 3/4 zakończony: " + count_summary(
                push_counts,
                (("articles", "artykułów"), ("run_articles", "powiązań z runem"), ("source_run_results", "wyników źródeł")),
            ) + ".",
        )

    if args.skip_ai:
        log("RUN", "Etap 4/4 pominięty — użyto --skip-ai.")
    else:
        if args.merge_existing_summaries:
            log("RUN", "Etap 4/4 — sprawdzam i aktualizuję istniejące syntezy aktywnych wątków.")
        else:
            log("RUN", "Etap 4/4 — grupuję tematy i tworzę opracowania AI.")
        result = analyze_run(
            args.db, run_id, client,
            max_articles=args.ai_max_articles,
            batch_size=args.ai_batch_size,
            merge_existing_summaries_mode=args.merge_existing_summaries,
            merge_existing_max_topics=args.merge_existing_max_topics,
        )
        log("RUN", "Etap 4/4 zakończony: " + ai_summary(result) + ".")
        if result.get("merge_failed", 0) or result.get("failed_summaries", 0):
            log(
                "RUN",
                "Przebieg niekompletny: pozostały błędy scalania lub syntez. "
                "Poprawnie zapisane wyniki pozostają w bazie; ponów tryb ai-only.",
                level="ERROR",
            )
            return 1
    log("RUN", "Cały przebieg zakończony pomyślnie.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
