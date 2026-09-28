#!/usr/bin/env python3
"""Fetch selected X accounts and attach relevant posts to active news topics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ai_pipeline import (
    DEFAULT_MODEL,
    PROMPT_VERSION,
    TOPIC_LOOKBACK_HOURS,
    call_openai,
    digest,
    empty_update,
    now,
    stored_base_summary,
)
from supabase_client import SupabaseRestClient


ACCOUNTS = [
    ("donaldtusk", "Donald Tusk", "POLSKA_POLITYKA", "CENTER_LEFT"),
    ("trzaskowski_", "Rafał Trzaskowski", "POLSKA_POLITYKA", "CENTER_LEFT"),
    ("ZandbergRAZEM", "Adrian Zandberg", "POLSKA_POLITYKA", "LEFT"),
    ("MagdaBiejat", "Magdalena Biejat", "POLSKA_POLITYKA", "LEFT"),
    ("NawrockiKn", "Karol Nawrocki", "POLSKA_POLITYKA", "RIGHT"),
    ("MorawieckiM", "Mateusz Morawiecki", "POLSKA_POLITYKA", "RIGHT"),
    ("SlawomirMentzen", "Sławomir Mentzen", "POLSKA_POLITYKA", "RIGHT"),
    ("krzysztofbosak", "Krzysztof Bosak", "POLSKA_POLITYKA", "RIGHT"),
    ("szymon_holownia", "Szymon Hołownia", "POLSKA_POLITYKA", "CENTER"),
    ("realDonaldTrump", "Donald Trump", "USA_POLITYKA", "RIGHT"),
    ("JDVance", "J.D. Vance", "USA_POLITYKA", "RIGHT"),
    ("AOC", "Alexandria Ocasio-Cortez", "USA_POLITYKA", "LEFT"),
    ("michaeljburry", "Michael Burry", "FINANSE", "UNCLASSIFIED"),
    ("RayDalio", "Ray Dalio", "FINANSE", "UNCLASSIFIED"),
    ("elerianm", "Mohamed El-Erian", "FINANSE", "UNCLASSIFIED"),
    ("LynAldenContact", "Lyn Alden", "FINANSE", "UNCLASSIFIED"),
    ("AswathDamodaran", "Aswath Damodaran", "FINANSE", "UNCLASSIFIED"),
    ("general_ben", "Ben Hodges", "BEZPIECZENSTWO", "UNCLASSIFIED"),
    ("MarkHertling", "Mark Hertling", "BEZPIECZENSTWO", "UNCLASSIFIED"),
    ("WarintheFuture", "Mick Ryan", "BEZPIECZENSTWO", "UNCLASSIFIED"),
    ("SKoziej", "Stanisław Koziej", "BEZPIECZENSTWO", "UNCLASSIFIED"),
    ("PMBreedlove", "Philip Breedlove", "BEZPIECZENSTWO", "UNCLASSIFIED"),
    ("KofmanMichael", "Michael Kofman", "ANALITYKA", "UNCLASSIFIED"),
    ("RALee85", "Rob Lee", "ANALITYKA", "UNCLASSIFIED"),
    ("adam_tooze", "Adam Tooze", "ANALITYKA", "UNCLASSIFIED"),
]

MATCH_INSTRUCTIONS = """
Jesteś modułem przypisującym publiczne wpisy z X do aktywnych historii
prasowych. Wpis można przypisać wyłącznie wtedy, gdy dotyczy tego samego
konkretnego wydarzenia, decyzji lub bezpośredniego rozwoju sprawy. Wspólna
osoba, kraj albo ogólna tematyka nie wystarcza. Nie twórz nowych tematów.
Wpis na X jest wypowiedzią autora, a nie niezależnym potwierdzeniem faktów.

Zwróć WYŁĄCZNIE poprawny JSON:
{"assignments":[{"post_id":"","topic_id":"","confidence":0.0,
"is_material":true,"update_pl":"konkretna informacja po polsku z jasnym wskazaniem autora"}],
"unassigned_post_ids":[]}

Każdy post_id ma wystąpić dokładnie raz. confidence musi wynosić co najmniej
0.85, aby przypisać wpis. update_pl wyjaśnia, co autor napisał i co to wnosi
do historii; nie przedstawia jego twierdzeń jako potwierdzonych faktów.
""".strip()


def _x_get(path: str, token: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    url = "https://api.x.com/2/" + path.lstrip("/")
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"X API HTTP {exc.code}: {detail}") from exc


def fetch_x_posts(run_id: str, client: SupabaseRestClient) -> dict[str, int]:
    token = (os.environ.get("X_BEARER_TOKEN") or "").strip()
    stats = {"accounts": len(ACCOUNTS), "checked": 0, "posts": 0, "failed": 0}
    if not token:
        print("[X] Brakuje X_BEARER_TOKEN — pomijam X.", flush=True)
        return stats
    existing = {str(row["username"]).lower(): row for row in client.select_all("x_accounts")}
    existing_post_ids = {
        str(row["post_id"]) for row in client.select_all("x_posts", columns="post_id")
    }
    start_time = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for username, display_name, category, profile in ACCOUNTS:
        try:
            account = existing.get(username.lower(), {})
            user_id = str(account.get("x_user_id") or "")
            if not user_id:
                data = _x_get(f"users/by/username/{urllib.parse.quote(username)}", token).get("data") or {}
                user_id = str(data.get("id") or "")
                display_name = str(data.get("name") or display_name)
            if not user_id:
                raise RuntimeError("konto nie zostało odnalezione")
            timestamp = now()
            client.upsert("x_accounts", [{
                "username": username, "display_name": display_name, "category": category,
                "editorial_profile": profile, "x_user_id": user_id, "enabled": True,
                "last_checked_at": timestamp, "updated_at": timestamp,
            }], on_conflict="username")
            payload = _x_get(f"users/{user_id}/tweets", token, {
                "start_time": start_time,
                "max_results": "5",
                "exclude": "replies,retweets",
                "tweet.fields": "created_at,lang,note_tweet",
            })
            rows = []
            for post in payload.get("data") or []:
                post_id = str(post.get("id") or "")
                note = post.get("note_tweet") if isinstance(post.get("note_tweet"), dict) else {}
                text = str(note.get("text") or post.get("text") or "").strip()
                if not post_id or not text or post_id in existing_post_ids:
                    continue
                rows.append({
                    "post_id": post_id, "username": username, "display_name": display_name,
                    "category": category, "editorial_profile": profile, "text": text,
                    "lang": post.get("lang"), "posted_at": post.get("created_at"),
                    "url": f"https://x.com/{username}/status/{post_id}", "fetched_at": timestamp,
                    "harvest_run_id": run_id, "ai_status": "PENDING", "raw_json": post,
                })
            client.upsert("x_posts", rows, on_conflict="post_id")
            existing_post_ids.update(str(row["post_id"]) for row in rows)
            stats["checked"] += 1
            stats["posts"] += len(rows)
        except Exception as exc:
            stats["failed"] += 1
            print(f"[X] @{username}: {exc}", flush=True)
    return stats


def analyze_x_posts(run_id: str, client: SupabaseRestClient, model: str = DEFAULT_MODEL) -> dict[str, int]:
    posts = client.select_all("x_posts", filters=[("harvest_run_id", f"eq.{run_id}"), ("ai_status", "eq.PENDING")])
    stats = {"pending": len(posts), "matched": 0, "unassigned": 0, "updated_topics": 0}
    if not posts:
        return stats
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=TOPIC_LOOKBACK_HOURS)).isoformat()
    topics = client.select_all("topics", columns="topic_id,headline_pl,last_seen_at", filters=[("status", "eq.ACTIVE"), ("last_seen_at", f"gte.{cutoff}")])
    summaries = {str(row["topic_id"]): row for row in client.select_all("topic_summaries")}
    payload = {
        "posts": [{"post_id": p["post_id"], "author": p["display_name"], "username": p["username"], "text": p["text"], "posted_at": p.get("posted_at")} for p in posts],
        "active_topics": [{"topic_id": t["topic_id"], "headline_pl": t["headline_pl"], "summary_pl": str(stored_base_summary(summaries.get(str(t["topic_id"]), {}).get("summary")).get("summary_pl") or "")[:2000]} for t in topics],
    }
    result = call_openai(MATCH_INSTRUCTIONS, payload, model)
    valid_posts = {str(p["post_id"]): p for p in posts}
    valid_topics = {str(t["topic_id"]) for t in topics}
    updates_by_topic: dict[str, list[dict[str, Any]]] = {}
    assigned: set[str] = set()
    for item in result.get("assignments") or []:
        if not isinstance(item, dict):
            continue
        post_id, topic_id = str(item.get("post_id") or ""), str(item.get("topic_id") or "")
        try: confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError): confidence = 0
        if post_id not in valid_posts or topic_id not in valid_topics or confidence < 0.85 or post_id in assigned:
            continue
        assigned.add(post_id)
        client.upsert("topic_x_posts", [{"topic_id": topic_id, "post_id": post_id, "confidence": confidence}], on_conflict="topic_id,post_id")
        updates_by_topic.setdefault(topic_id, []).append({**item, "post": valid_posts[post_id]})
        client.update("x_posts", {"ai_status": "MATCHED", "exclusion_reason": None}, filters=[("post_id", f"eq.{post_id}")])
    for post_id in valid_posts.keys() - assigned:
        client.update("x_posts", {"ai_status": "UNASSIGNED", "exclusion_reason": "Brak pewnego dopasowania do aktywnej historii."}, filters=[("post_id", f"eq.{post_id}")])
    for topic_id, items in updates_by_topic.items():
        old = summaries.get(topic_id)
        if not old:
            continue
        old_stored = old.get("summary") or {}
        base = stored_base_summary(old_stored)
        material = [i for i in items if bool(i.get("is_material")) and str(i.get("update_pl") or "").strip()]
        if material:
            update_text = "\n\n".join(str(i["update_pl"]).strip() for i in material)
        else:
            names = ", ".join(dict.fromkeys(str(i["post"]["display_name"]) for i in items))
            update_text = f"Dodano nowe wpisy na X ({names}), ale nie wnoszą one istotnych nowych informacji do wcześniejszej syntezy."
        post_ids = [str(i["post_id"]) for i in items]
        latest_update = {**empty_update(), "is_update": True, "new_information_pl": update_text, "new_x_post_ids": post_ids}
        stored = {"base_summary": base, "latest_update": latest_update}
        version = int(old.get("version") or 0) + 1
        timestamp = now()
        input_hash = digest({"topic_id": topic_id, "post_ids": post_ids})
        client.upsert("topic_summaries", [{"topic_id": topic_id, "version": version, "input_hash": input_hash, "model": model, "summary": stored, "generated_at": timestamp, "updated_at": timestamp}], on_conflict="topic_id")
        client.upsert("topic_summary_versions", [{"topic_id": topic_id, "version": version, "run_id": run_id, "model": model, "prompt_version": PROMPT_VERSION + "+x", "summary": stored, "new_article_ids": [], "generated_at": timestamp}], on_conflict="topic_id,version")
        stats["updated_topics"] += 1
    stats["matched"] = len(assigned)
    stats["unassigned"] = len(posts) - len(assigned)
    return stats
