#!/usr/bin/env python3
"""Read-only smoke test for one X account; writes nothing to Supabase."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
import re
import urllib.parse

from x_pipeline import _x_get


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    args = parser.parse_args()
    username = args.username.strip().lstrip("@")
    token = (os.environ.get("X_BEARER_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Brakuje X_BEARER_TOKEN.")

    user = (_x_get(f"users/by/username/{urllib.parse.quote(username)}", token).get("data") or {})
    user_id = str(user.get("id") or "")
    if not user_id:
        raise RuntimeError(f"Nie znaleziono konta @{username}.")
    print(f"Konto: {user.get('name') or username} (@{username}), id={user_id}")

    start_time = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    payload = _x_get(f"users/{user_id}/tweets", token, {
        "start_time": start_time,
        "max_results": "8",
        "exclude": "retweets",
        "tweet.fields": "attachments,author_id,created_at,lang,note_tweet,in_reply_to_user_id,referenced_tweets",
        "expansions": "attachments.media_keys,referenced_tweets.id",
        "media.fields": "media_key,type",
    })
    media_by_key = {
        str(item.get("media_key")): item
        for item in ((payload.get("includes") or {}).get("media") or [])
        if item.get("media_key")
    }
    posts = payload.get("data") or []
    print(f"X zwrócił: {len(posts)} wpisów z ostatnich 24 h\n")
    accepted = 0
    for index, post in enumerate(posts, start=1):
        note = post.get("note_tweet") if isinstance(post.get("note_tweet"), dict) else {}
        text = str(note.get("text") or post.get("text") or "").strip()
        reply_to = str(post.get("in_reply_to_user_id") or "")
        media_keys = (post.get("attachments") or {}).get("media_keys") or []
        media_types = [
            str(media_by_key.get(str(key), {}).get("type") or "unknown")
            for key in media_keys
        ]
        meaningful = re.sub(r"https?://\S+", "", text).strip()
        reasons = []
        if reply_to and reply_to != user_id:
            reasons.append("odpowiedź do innej osoby")
        if any(kind in {"video", "animated_gif"} for kind in media_types):
            reasons.append("film/GIF")
        if len(meaningful.split()) <= 10:
            reasons.append(f"tylko {len(meaningful.split())} słów")
        status = "POMINIĘTY: " + ", ".join(reasons) if reasons else "PRZYJĘTY"
        accepted += not reasons
        print(f"[{index}] {status}")
        print(f"Data: {post.get('created_at') or 'brak'} | media: {', '.join(media_types) or 'brak'}")
        print(f"https://x.com/{username}/status/{post.get('id')}")
        print(text[:1200] + ("…" if len(text) > 1200 else ""))
        print()
    print(f"Podsumowanie: przyjęte={accepted}, pominięte={len(posts) - accepted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
