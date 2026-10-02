#!/usr/bin/env python3
"""Rebuild saved updates chronologically, keeping bases and article batches.

Default: snapshot and report only. --apply generates replacements and saves
each complete topic atomically through the companion Supabase RPC migration.
The state file is both a backup and a resumable checkpoint. No article links,
topic categories, original dates or summary version numbers are changed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any

import ai_pipeline as ai
from supabase_client import SupabaseRestClient


RPC = "rpc/rebuild_topic_updates_atomic"
HISTORY_FIELDS = ("version", "run_id", "model", "prompt_version", "summary", "new_article_ids")
HISTORY_COLUMNS = ",".join(HISTORY_FIELDS) + ",generated_at"
CURRENT_FIELDS = ("version", "input_hash", "model", "summary")
REBUILD_SELECTION = {"status": "ACTIVE", "lookback_hours": 55, "min_updates": 2}


def text_of(update: dict[str, Any]) -> str:
    if update.get("status") == "NO_NEW_INFORMATION":
        return ""
    return ai.update_text_value({"update": update})


def identity(update: dict[str, Any]) -> str:
    if update.get("update_id"):
        return "update:" + str(update["update_id"])
    if update.get("run_id"):
        return "run:" + str(update["run_id"])
    return "legacy:" + ai.digest({
        "text": text_of(update), "articles": update.get("new_article_ids") or [],
    })


def dated_updates(stored: Any, fallback: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for raw in ai.stored_updates(stored):
        if not text_of(raw):
            continue
        update = deepcopy(raw)
        for field in ("run_id", "generated_at", "version", "new_article_ids"):
            if (field not in update or (field != "new_article_ids" and not update.get(field))) and fallback.get(field):
                update[field] = deepcopy(fallback[field])
        result.append(update)
    return result


def time_key(value: Any) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def collect_updates(current: dict[str, Any], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror UI deduplication, including updates retained only in snapshots."""
    selected: dict[str, dict[str, Any]] = {}
    rows = [current, *sorted(history, key=lambda row: int(row["version"]))]
    for row in rows:
        for update in dated_updates(row.get("summary"), row):
            key = identity(update)
            previous = selected.get(key)
            if previous and previous.get("new_article_ids") != update.get("new_article_ids"):
                # Reused run IDs may describe different batches. Never silently
                # invent a correspondence between a text and its articles.
                raise ValueError("Ten sam identyfikator aktualizacji ma różne zestawy artykułów w historii.")
            if previous is None or time_key(update.get("generated_at")) > time_key(previous.get("generated_at")):
                selected[key] = update
    updates = sorted(selected.values(), key=lambda item: (
        time_key(item.get("generated_at")), int(item.get("version") or 0),
    ))
    for update in updates:
        ids = update.get("new_article_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(value, str) and value for value in ids):
            raise ValueError("Aktualizacja nie ma zapisanej listy artykułów; wymagane ręczne sprawdzenie.")
    return updates


def rewrite_stored(stored: dict[str, Any], fallback: dict[str, Any], replacements: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(stored)

    def replace(raw: dict[str, Any]) -> dict[str, Any]:
        dated = dated_updates({"updates": [raw]}, fallback)
        if not dated:
            return deepcopy(raw)
        replacement = replacements[identity(dated[0])]
        # Preserve snapshot-specific metadata; copy only the new text.
        return {**deepcopy(raw), "status": replacement["status"], "is_update": replacement["is_update"],
                "new_information_pl": replacement["new_information_pl"],
                "what_changed_pl": replacement["what_changed_pl"]}

    if isinstance(result.get("updates"), list):
        result["updates"] = [replace(value) for value in result["updates"]]
    for field in ("latest_update", "update"):
        if isinstance(result.get(field), dict):
            result[field] = replace(result[field])
    return result


def article_rows(client: SupabaseRestClient, ids: list[str]) -> list[dict[str, Any]]:
    unique = list(dict.fromkeys(ids))
    rows = []
    for start in range(0, len(unique), 100):
        batch = unique[start:start + 100]
        # Quote PostgREST values rather than interpolating bare identifiers.
        values = ",".join(json.dumps(value) for value in batch)
        rows.extend(client.select_all("articles", filters=[("article_id", f"in.({values})")]))
    by_id = {str(row["article_id"]): row for row in rows}
    missing = [value for value in unique if value not in by_id or not str(by_id[value].get("body") or "").strip()]
    if missing:
        raise ValueError(f"Brakuje artykułów lub ich treści: {', '.join(missing[:10])}")
    return [by_id[value] for value in unique]


def rebuild_job(job: dict[str, Any], client: SupabaseRestClient, model: str) -> dict[str, Any]:
    current, history = job["current"], job["history"]
    originals = collect_updates(current, history)
    base = deepcopy(ai.stored_base_summary(current["summary"]))
    # Legacy direct summaries may contain the last update in their base.
    # The prose and all factual fields of the base remain untouched.
    if "base_summary" not in current["summary"]:
        base["update"] = ai.empty_update()
    all_ids = list(dict.fromkeys(value for update in originals for value in update["new_article_ids"]))
    by_id = {str(row["article_id"]): row for row in article_rows(client, all_ids)}
    rebuilt = []
    for index, original in enumerate(originals, 1):
        print(f"{job['topic_id']}: aktualizacja {index}/{len(originals)}", flush=True)
        rows = [by_id[value] for value in dict.fromkeys(original["new_article_ids"])]
        payload, _, _ = ai.build_bounded_summary_input({
            "topic": {"topic_id": job["topic_id"], "working_title_pl": job["title"], "topic_action": "DEVELOPMENT"},
            "previous_aggregation": {"base_summary": base, "prior_updates": deepcopy([
                update for update in rebuilt if update.get("status") != "NO_NEW_INFORMATION"
            ])},
            "all_article_ids_in_topic": list(dict.fromkeys([*job["article_ids"], *all_ids])),
        }, rows)
        response = None
        for instructions in (ai.SUMMARY_INSTRUCTIONS, ai.SUMMARY_UPDATE_REPAIR_INSTRUCTIONS):
            response = ai.normalize_summary_response(ai.call_openai(
                instructions, payload, model,
                timeout_seconds=ai.SUMMARY_REQUEST_TIMEOUT_SECONDS,
                response_schema=ai.SUMMARY_RESPONSE_SCHEMA,
                response_schema_name="rebuild_topic_update",
            ))
            if not ai.update_needs_repair(response):
                break
        if response is None or ai.update_needs_repair(response):
            raise ValueError("Model nie wygenerował poprawnej aktualizacji po ponowieniu.")
        generated = response["update"]
        update = {**deepcopy(original), "status": generated["status"], "is_update": generated["is_update"],
                  "new_information_pl": generated["new_information_pl"],
                  "what_changed_pl": generated.get("what_changed_pl") or ""}
        rebuilt.append(update)
    replacements = {identity(old): new for old, new in zip(originals, rebuilt)}
    new_history = []
    for row in history:
        revised = deepcopy(row)
        revised["summary"] = rewrite_stored(row["summary"], row, replacements)
        if revised["summary"] != row["summary"]:
            revised["model"] = model
            revised["prompt_version"] = ai.PROMPT_VERSION
        new_history.append(revised)
    new_current = {field: deepcopy(current[field]) for field in CURRENT_FIELDS}
    new_current["summary"] = {**deepcopy(current["summary"]), "base_summary": base,
                              "updates": rebuilt, "latest_update": deepcopy(rebuilt[-1]),
                              "last_analysis": deepcopy(rebuilt[-1])}
    # A legacy top-level update would otherwise retain its old text.
    if isinstance(new_current["summary"].get("update"), dict):
        new_current["summary"]["update"] = deepcopy(rebuilt[-1])
    new_current["model"] = model
    new_current["input_hash"] = ai.digest({"rebuild": new_current["summary"], "prompt": ai.PROMPT_VERSION, "model": model})
    return {"current": new_current, "history": new_history}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        json.dump(state, handle, ensure_ascii=False, indent=2)
    temporary.replace(path)


def snapshot(client: SupabaseRestClient, topic_ids: list[str]) -> dict[str, Any]:
    captured_at = ai.now()
    cutoff = time_key(captured_at) - timedelta(hours=REBUILD_SELECTION["lookback_hours"])
    filters = [("topic_id", "in.(" + ",".join(json.dumps(value) for value in topic_ids) + ")")] if topic_ids else []
    topics = {row["topic_id"]: row for row in client.select_all("topics", filters=[
        *filters, ("status", "eq.ACTIVE"), ("last_seen_at", f"gt.{cutoff.isoformat()}"),
    ]) if row.get("status") == "ACTIVE" and time_key(row.get("last_seen_at")) > cutoff}
    state = {"format": 1, "project_url": client.project_url, "created_at": captured_at,
             "prompt_version": ai.PROMPT_VERSION, "selection": deepcopy(REBUILD_SELECTION), "jobs": []}
    if not topics:
        return state
    current = client.select_all("topic_summaries", filters=filters)
    history_rows = client.select_all("topic_summary_versions", columns="topic_id," + HISTORY_COLUMNS, filters=filters)
    links = client.select_all("topic_articles", columns="topic_id,article_id", filters=filters)
    history_by_topic: dict[str, list[Any]] = {}
    for row in history_rows:
        history_by_topic.setdefault(row["topic_id"], []).append({field: row[field] for field in HISTORY_COLUMNS.split(",")})
    jobs = []
    for row in current:
        topic_id = row["topic_id"]
        if topic_id not in topics:
            continue
        history = sorted(history_by_topic.get(topic_id, []), key=lambda item: int(item["version"]))
        job = {"topic_id": topic_id, "title": topics.get(topic_id, {}).get("headline_pl") or topic_id,
               "article_ids": [link["article_id"] for link in links if link["topic_id"] == topic_id],
               "current": deepcopy(row), "history": history, "status": "pending"}
        try:
            updates = collect_updates(row, history)
            if len(updates) < REBUILD_SELECTION["min_updates"]:
                continue
            job["update_count"] = len(updates)
        except ValueError as exc:
            job["error"] = str(exc)
            job["status"] = "invalid"
        jobs.append(job)
    state["jobs"] = jobs
    return state


def validate_selection(state: dict[str, Any]) -> None:
    if state.get("selection") != REBUILD_SELECTION:
        raise ValueError("Checkpoint ma starszy lub inny zakres naprawy. Rozpocznij nowe uruchomienie bez resume_run_id (lokalnie użyj nowego pliku --state).")


def rpc_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {"p_topic_id": job["topic_id"],
            "p_expected_current": {field: job["current"][field] for field in CURRENT_FIELDS},
            "p_expected_history": [{field: row[field] for field in HISTORY_FIELDS} for row in job["history"]],
            "p_new_current": job["replacement"]["current"],
            "p_new_history": [{field: row[field] for field in HISTORY_FIELDS} for row in job["replacement"]["history"]]}


def execute(state: dict[str, Any], path: Path, client: SupabaseRestClient, model: str) -> int:
    failed = 0
    for job in state["jobs"]:
        if job["status"] == "completed":
            continue
        if job["status"] == "invalid":
            print(f"Pominięto {job['topic_id']}: {job['error']}", flush=True)
            failed += 1
            continue
        try:
            if "replacement" not in job:
                job["replacement"] = rebuild_job(job, client, model)
                save_state(path, state)
            result = client.request("POST", RPC, payload=rpc_payload(job))
            if result not in ("applied", "already_applied"):
                raise ValueError(f"Nieoczekiwany wynik zapisu: {result}")
            job["status"] = "completed"
            job.pop("error", None)
            save_state(path, state)
            visible = sum(bool(text_of(update)) for update in job["replacement"]["current"]["summary"]["updates"])
            print(f"Zapisano {job['topic_id']}: oceniono {job['update_count']} aktualizacji; widocznych po naprawie: {visible}.", flush=True)
        except Exception as exc:
            job["error"] = ai.short_text(exc, 400)
            save_state(path, state)
            failed += 1
            print(f"Nie zapisano {job['topic_id']}: {job['error']}", flush=True)
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Wygeneruj i atomowo podmień aktualizacje.")
    parser.add_argument("--state", type=Path, default=Path("topic-update-rebuild.json"), help="Kopia i checkpoint; istniejący plik wznawia tę samą naprawę.")
    parser.add_argument("--topic-id", action="append", default=[], help="Opcjonalnie ogranicz do wskazanych wątków.")
    parser.add_argument("--model", default=ai.DEFAULT_MODEL)
    args = parser.parse_args()
    client = SupabaseRestClient()
    if args.state.exists():
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if state.get("format") != 1 or state.get("project_url") != client.project_url:
            raise ValueError("Plik stanu ma inny format lub pochodzi z innej bazy.")
        validate_selection(state)
        if state.get("prompt_version") != ai.PROMPT_VERSION or state.get("model", args.model) != args.model:
            raise ValueError("Checkpoint powstał z innym promptem lub modelem; nie mieszaj wersji naprawy.")
        if args.topic_id and set(args.topic_id) != set(state.get("requested_topic_ids", [])):
            raise ValueError("Nie zmieniaj zakresu naprawy przy użyciu istniejącego checkpointu.")
    else:
        state = snapshot(client, args.topic_id)
        state["model"] = args.model
        state["requested_topic_ids"] = args.topic_id
        save_state(args.state, state)
    print(f"Zakres: ACTIVE, mniej niż 55 godzin od ostatniego artykułu, co najmniej 2 widoczne aktualizacje (stan z {state['created_at']}).", flush=True)
    print(f"Plan: {len(state['jobs'])} wątków, {sum(job.get('update_count', 0) for job in state['jobs'])} aktualizacji. Kopia: {args.state}", flush=True)
    if not args.apply:
        print("Podgląd: nie wywołano AI i nie zmieniono bazy. Dodaj --apply, aby wykonać naprawę.")
        return 0
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Brakuje OPENAI_API_KEY.")
    client.request("POST", RPC, payload={"p_check_only": True, "p_topic_id": "",
        "p_expected_current": {}, "p_expected_history": [], "p_new_current": {}, "p_new_history": []})
    failed = execute(state, args.state, client, args.model)
    print(f"Zakończono: {sum(job['status'] == 'completed' for job in state['jobs'])} zapisanych wątków; {failed} błędów.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
