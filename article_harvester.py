#!/usr/bin/env python3
"""Persistent first-pass article harvester.

Homepage -> article links -> article title/body -> SQLite + JSONL/HTML export.

Existing canonical URLs are never fetched again by default. Use
--retry-failed only when a previous attempt did not obtain an article.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
import unicodedata
import urllib.parse

import source_tester as st

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Brak PyYAML.") from exc


IGNORED_PATH_PARTS = (
    "/tag/", "/tags/", "/author/", "/authors/", "/category/",
    "/categories/", "/search", "/newsletter", "/podcast", "/video/",
)
HTML_ASSET_SUFFIXES = st.NON_ARTICLE_EXTENSIONS | {".xml", ".json", ".txt"}
MIN_ARTICLE_WORDS = 200


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(*parts: str) -> str:
    value = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]


def normalized_title(title: str) -> str:
    value = unicodedata.normalize("NFKC", st.clean_text(title)).casefold()
    return re.sub(r"\s+", " ", value).strip()


def first_two_sentences(body: str) -> str:
    text = st.clean_text(body)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?…])\s+", text)
    if len(parts) >= 2:
        return " ".join(parts[:2]).strip()[:1600]
    return text[:1600]


def opening_fingerprint(body: str) -> str:
    opening = first_two_sentences(body)
    if not opening:
        return ""
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", opening).casefold()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS harvest_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            source_count INTEGER NOT NULL DEFAULT 0,
            discovered_count INTEGER NOT NULL DEFAULT 0,
            fetched_count INTEGER NOT NULL DEFAULT 0,
            skipped_existing_count INTEGER NOT NULL DEFAULT 0,
            valid_article_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            homepage TEXT NOT NULL,
            region TEXT,
            editorial_profile TEXT,
            source_type TEXT,
            enabled INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS articles (
            article_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_profile TEXT,
            source_type TEXT,
            original_language TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            original_url TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            published_at TEXT,
            updated_at TEXT,
            section TEXT,
            item_kind TEXT NOT NULL,
            content_status TEXT NOT NULL,
            word_count INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT '',
            title_key TEXT NOT NULL DEFAULT '',
            opening_text TEXT NOT NULL DEFAULT '',
            opening_fingerprint TEXT NOT NULL DEFAULT '',
            sentiment TEXT,
            tone_hint TEXT NOT NULL DEFAULT 'NOT_ANALYZED',
            topic_hint TEXT,
            fetch_method TEXT NOT NULL,
            http_status INTEGER,
            error TEXT,
            first_seen_at TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            last_seen_on_homepage_at TEXT NOT NULL,
            UNIQUE(source_id, canonical_url)
        );
        CREATE TABLE IF NOT EXISTS run_articles (
            run_id TEXT NOT NULL,
            article_id TEXT NOT NULL,
            discovered_on_homepage INTEGER NOT NULL DEFAULT 1,
            fetched_now INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(run_id, article_id)
        );
        CREATE TABLE IF NOT EXISTS source_run_results (
            run_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            homepage_status INTEGER,
            discovered_count INTEGER NOT NULL DEFAULT 0,
            fetched_count INTEGER NOT NULL DEFAULT 0,
            skipped_existing_count INTEGER NOT NULL DEFAULT 0,
            valid_article_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            rejected_short_count INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(run_id, source_id)
        );
        CREATE TABLE IF NOT EXISTS article_url_aliases (
            source_id TEXT NOT NULL,
            candidate_url TEXT NOT NULL,
            duplicate_of_article_id TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY(source_id, candidate_url)
        );
        CREATE TABLE IF NOT EXISTS rejected_candidates (
            source_id TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            word_count INTEGER NOT NULL DEFAULT 0,
            opening_fingerprint TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY(source_id, canonical_url)
        );
        """
    )
    ensure_column(conn, "articles", "title_key", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "articles", "opening_text", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "articles", "opening_fingerprint", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "source_run_results", "duplicate_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "source_run_results", "rejected_short_count", "INTEGER NOT NULL DEFAULT 0")
    old_rows = conn.execute(
        "SELECT article_id, source_id, canonical_url, title, body, word_count, content_status "
        "FROM articles WHERE title_key = '' OR opening_fingerprint = ''"
    ).fetchall()
    for row in old_rows:
        title_key = normalized_title(row["title"])
        opening_text = first_two_sentences(row["body"])
        opening_hash = opening_fingerprint(row["body"])
        conn.execute(
            "UPDATE articles SET title_key = ?, opening_text = ?, opening_fingerprint = ? "
            "WHERE article_id = ?",
            (title_key, opening_text, opening_hash, row["article_id"]),
        )
        if row["content_status"] not in {"COMPLETE", "EXCERPT"} or int(row["word_count"] or 0) < MIN_ARTICLE_WORDS:
            conn.execute(
                "INSERT OR IGNORE INTO rejected_candidates "
                "(source_id, canonical_url, title, word_count, opening_fingerprint, reason, first_seen_at, last_seen_at) "
                "SELECT source_id, canonical_url, title, word_count, opening_fingerprint, 'LEGACY_REJECTED', first_seen_at, last_seen_on_homepage_at "
                "FROM articles WHERE article_id = ?",
                (row["article_id"],),
            )
    conn.commit()
    return conn


def source_language(source: dict[str, Any]) -> str:
    configured = source.get("language") or source.get("languages")
    if isinstance(configured, list) and configured:
        return str(configured[0])
    if isinstance(configured, str) and configured:
        return configured
    region = str(source.get("region", "")).lower()
    return {
        "poland": "pl",
        "germany": "de",
        "france": "fr",
        "italy": "it",
        "spain": "es",
        "china": "en/original",
        "russia": "ru/en",
        "ukraine": "uk/en",
    }.get(region, "en/original")


def is_candidate_url(url: str, homepage: str, link_text: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.lower()
    if not st.same_site(url, homepage):
        return False
    if path in {"", "/"}:
        return False
    if any(path.endswith(suffix) for suffix in HTML_ASSET_SUFFIXES):
        return False
    host = parsed.netloc.lower()
    if any(token in host for token in ("static", "image", "images", "cdn")) and not st.ARTICLE_HINTS.search(path):
        return False
    if any(part in path for part in IGNORED_PATH_PARTS):
        return False
    if path.startswith("/login") or path.startswith("/account") or path.startswith("/subscribe"):
        return False
    title_words = len(st.clean_text(link_text).split())
    return bool(
        st.ARTICLE_HINTS.search(path)
        or re.search(r"/20[0-9]{2}/", path)
        or path.endswith(".html")
        or title_words >= 6
    )


def homepage_candidates(text: str, homepage: str, limit: int) -> list[dict[str, str]]:
    parser = st.PageParser()
    try:
        parser.feed(text or "")
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in parser.links:
        url = st.canonicalize(link.get("href", ""), homepage)
        if not url or url in seen or not is_candidate_url(url, homepage, link.get("text", "")):
            continue
        seen.add(url)
        rows.append({"url": url, "title_hint": st.clean_text(link.get("text", ""))[:500]})
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def classify_item(extracted: dict[str, Any]) -> tuple[str, str]:
    if extracted.get("captcha"):
        return "CHALLENGE", "CAPTCHA"
    if extracted.get("paywall"):
        return "PAYWALL", "PAYWALL"
    title = st.clean_text(extracted.get("title", ""))
    words = int(extracted.get("word_count", 0) or 0)
    if words and words < MIN_ARTICLE_WORDS:
        return "TOO_SHORT", "TOO_SHORT"
    if extracted.get("body_success"):
        return "ARTICLE", "COMPLETE"
    if title and words >= MIN_ARTICLE_WORDS:
        return "ARTICLE_EXCERPT", "EXCERPT"
    if extracted.get("status") in st.BLOCK_STATUSES:
        return "CHALLENGE", "BLOCKED"
    if title:
        return "UNKNOWN", "METADATA_ONLY"
    return "UNKNOWN", "FAILED"


def existing_article(conn: sqlite3.Connection, source_id: str, canonical_url: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM articles WHERE source_id = ? AND canonical_url = ?",
        (source_id, canonical_url),
    ).fetchone()


def existing_rejection(conn: sqlite3.Connection, source_id: str, canonical_url: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM rejected_candidates WHERE source_id = ? AND canonical_url = ?",
        (source_id, canonical_url),
    ).fetchone()


def existing_logical_article(
    conn: sqlite3.Connection, source_id: str, title_key: str, opening_hash: str
) -> sqlite3.Row | None:
    if not title_key or not opening_hash:
        return None
    return conn.execute(
        "SELECT * FROM articles WHERE source_id = ? AND title_key = ? "
        "AND opening_fingerprint = ? AND content_status IN ('COMPLETE', 'EXCERPT') "
        "ORDER BY first_seen_at LIMIT 1",
        (source_id, title_key, opening_hash),
    ).fetchone()


def save_rejection(
    conn: sqlite3.Connection,
    source_id: str,
    canonical_url: str,
    title: str,
    word_count: int,
    opening_hash: str,
    reason: str,
    now: str,
) -> None:
    conn.execute(
        "INSERT INTO rejected_candidates "
        "(source_id, canonical_url, title, word_count, opening_fingerprint, reason, first_seen_at, last_seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(source_id, canonical_url) DO UPDATE SET "
        "title = excluded.title, word_count = excluded.word_count, "
        "opening_fingerprint = excluded.opening_fingerprint, reason = excluded.reason, "
        "last_seen_at = excluded.last_seen_at",
        (source_id, canonical_url, title, word_count, opening_hash, reason, now, now),
    )


def save_article(
    conn: sqlite3.Connection,
    run_id: str,
    source: dict[str, Any],
    candidate_url: str,
    extracted: dict[str, Any],
    fetch_method: str,
    now: str,
    title_hint: str = "",
) -> tuple[str, bool, bool, str]:
    source_id = str(source["id"])
    canonical_url = st.canonicalize(extracted.get("url", "") or candidate_url, source["homepage"]) or candidate_url
    item_kind, content_status = classify_item(extracted)
    title = st.clean_text(extracted.get("title", "") or title_hint)
    body = extracted.get("body", "") if item_kind in {"ARTICLE", "ARTICLE_EXCERPT"} else ""
    word_count = int(extracted.get("word_count", 0) or len(body.split()))
    title_key = normalized_title(title)
    opening_text = first_two_sentences(body)
    opening_hash = opening_fingerprint(body)
    if item_kind not in {"ARTICLE", "ARTICLE_EXCERPT"} or word_count < MIN_ARTICLE_WORDS:
        save_rejection(
            conn, source_id, canonical_url, title, word_count, opening_hash,
            content_status, now,
        )
        return "", False, False, "rejected"
    content_hash = extracted.get("content_hash", "") or (
        hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""
    )
    existing = existing_article(conn, source_id, canonical_url)
    if existing is not None:
        conn.execute(
            "UPDATE articles SET last_seen_on_homepage_at = ? WHERE article_id = ?",
            (now, existing["article_id"]),
        )
        return existing["article_id"], False, True, "existing"
    logical_existing = existing_logical_article(conn, source_id, title_key, opening_hash)
    if logical_existing is not None:
        conn.execute(
            "INSERT INTO article_url_aliases "
            "(source_id, candidate_url, duplicate_of_article_id, first_seen_at, last_seen_at, reason) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source_id, candidate_url) DO UPDATE SET last_seen_at = excluded.last_seen_at",
            (source_id, canonical_url, logical_existing["article_id"], now, now,
             "SAME_TITLE_AND_FIRST_TWO_SENTENCES"),
        )
        conn.execute(
            "UPDATE articles SET last_seen_on_homepage_at = ? WHERE article_id = ?",
            (now, logical_existing["article_id"]),
        )
        conn.execute(
            "INSERT OR REPLACE INTO run_articles "
            "(run_id, article_id, discovered_on_homepage, fetched_now) VALUES (?, ?, 1, 1)",
            (run_id, logical_existing["article_id"]),
        )
        return logical_existing["article_id"], False, True, "duplicate"
    article_id = stable_id(source_id, canonical_url)
    if existing is None:
        conn.execute(
            """
            INSERT INTO articles (
                article_id, source_id, source_name, source_profile, source_type,
                original_language, title, body, description, author, original_url,
                canonical_url, published_at, updated_at, section, item_kind,
                content_status, word_count, content_hash, title_key, opening_text,
                opening_fingerprint, sentiment, tone_hint, topic_hint, fetch_method,
                http_status, error, first_seen_at,
                fetched_at, last_seen_on_homepage_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?
            )
            """,
            (
                article_id, source_id, source.get("name", source_id),
                st.infer_editorial_profile(source),
                source.get("source_type", "UNCLASSIFIED"), source_language(source),
                title, body, extracted.get("description", "") or "",
                extracted.get("author", "") or "", candidate_url, canonical_url,
                extracted.get("published_at", "") or "", "", "", item_kind,
                content_status, word_count, content_hash, title_key, opening_text,
                opening_hash, None, "NOT_ANALYZED", "", fetch_method,
                extracted.get("status"), extracted.get("error", "") or "",
                now, now, now,
            ),
        )
        inserted = True
    else:
        conn.execute(
            "UPDATE articles SET last_seen_on_homepage_at = ? WHERE article_id = ?",
            (now, existing["article_id"]),
        )
        article_id = existing["article_id"]
        inserted = False
    conn.execute(
        "INSERT OR REPLACE INTO run_articles "
        "(run_id, article_id, discovered_on_homepage, fetched_now) VALUES (?, ?, 1, ?)",
        (run_id, article_id, 1),
    )
    return article_id, inserted, True, "inserted"


def fetch_one(
    client: st.HttpClient,
    page_obj: Any,
    source: dict[str, Any],
    url: str,
    browser_enabled: bool,
) -> tuple[dict[str, Any], str]:
    result = client.get(url)
    extracted = st.extract_article(result, source["homepage"], include_body=True)
    method = "HTTP_HTML"
    if browser_enabled and page_obj is not None and not extracted.get("body_success"):
        try:
            response = st.browser_navigate(
                page_obj, url, int(float(source.get("timeout_seconds", 15)) * 1000)
            )
            st.browser_prepare_page(page_obj, source)
            content = page_obj.content()
            browser_result = st.FetchResult(
                url=url,
                status=response.status if response else None,
                final_url=page_obj.url,
                content_type="text/html",
                body=content.encode("utf-8"),
            )
            browser_extracted = st.extract_article(
                browser_result, source["homepage"], include_body=True
            )
            if browser_extracted.get("body_success") or not extracted.get("title"):
                extracted = browser_extracted
                method = "BROWSER"
        except Exception as exc:
            extracted.setdefault("error", str(exc)[:300])
    return extracted, method


def harvest_source(
    conn: sqlite3.Connection,
    run_id: str,
    source: dict[str, Any],
    defaults: dict[str, Any],
    args: argparse.Namespace,
    page_obj: Any,
) -> dict[str, Any]:
    source_id = str(source["id"])
    client = st.HttpClient(
        float(source.get("timeout_seconds", defaults.get("timeout_seconds", 15))),
        int(source.get("min_delay_ms", defaults.get("min_delay_ms", 500))),
        int(source.get("max_retries", defaults.get("max_retries", 1))),
    )
    now = utc_now()
    homepage_result = client.get(source["homepage"])
    candidates = homepage_candidates(
        homepage_result.text, source["homepage"], args.max_articles_per_source
    )
    notes: list[str] = []
    if args.browser and page_obj is not None:
        needs_browser = not candidates or bool(
            source.get("browser_accept_selectors")
            or source.get("browser_close_selectors")
            or source.get("browser_click_texts")
        )
        if needs_browser:
            try:
                st.browser_navigate(
                    page_obj, source["homepage"],
                    int(float(source.get("timeout_seconds", 15)) * 1000)
                )
                st.browser_prepare_page(page_obj, source)
                browser_candidates = homepage_candidates(
                    page_obj.content(), source["homepage"], args.max_articles_per_source
                )
                merged = {row["url"]: row for row in candidates}
                for row in browser_candidates:
                    merged.setdefault(row["url"], row)
                candidates = list(merged.values())
                if args.max_articles_per_source > 0:
                    candidates = candidates[:args.max_articles_per_source]
                notes.append("browser_homepage")
            except Exception as exc:
                notes.append(f"browser_homepage_error:{str(exc)[:160]}")
    counts = {
        "discovered": len(candidates), "fetched": 0, "skipped": 0,
        "valid": 0, "failed": 0, "duplicates": 0, "rejected_short": 0,
    }
    for candidate in candidates:
        url = candidate["url"]
        canonical = st.canonicalize(url, source["homepage"]) or url
        existing = existing_article(conn, source_id, canonical)
        rejection = existing_rejection(conn, source_id, canonical)
        if existing is None and rejection is not None and not args.retry_rejected:
            conn.execute(
                "UPDATE rejected_candidates SET last_seen_at = ? "
                "WHERE source_id = ? AND canonical_url = ?",
                (now, source_id, canonical),
            )
            counts["skipped"] += 1
            continue
        should_fetch = existing is None or (
            args.retry_failed and existing["content_status"] in {"FAILED", "BLOCKED", "CAPTCHA"}
        )
        if not should_fetch:
            article_id = existing["article_id"]
            conn.execute(
                "UPDATE articles SET last_seen_on_homepage_at = ? WHERE article_id = ?",
                (now, article_id),
            )
            conn.execute(
                "INSERT OR REPLACE INTO run_articles "
                "(run_id, article_id, discovered_on_homepage, fetched_now) VALUES (?, ?, 1, 0)",
                (run_id, article_id),
            )
            counts["skipped"] += 1
            continue
        try:
            extracted, method = fetch_one(client, page_obj, source, url, args.browser)
            _, inserted, valid, outcome = save_article(
                conn, run_id, source, url, extracted, method, now, candidate.get("title_hint", "")
            )
            counts["fetched"] += 1
            counts["valid"] += int(valid and inserted)
            counts["duplicates"] += int(outcome == "duplicate")
            counts["rejected_short"] += int(
                outcome == "rejected" and classify_item(extracted)[1] == "TOO_SHORT"
            )
        except Exception as exc:
            failed = {
                "url": url, "status": None, "title": candidate.get("title_hint", ""),
                "body_success": False, "word_count": 0, "error": str(exc)[:300],
            }
            save_article(conn, run_id, source, url, failed, "ERROR", now, candidate.get("title_hint", ""))
            counts["fetched"] += 1
            counts["failed"] += 1
    conn.execute(
        """
        INSERT OR REPLACE INTO source_run_results
        (run_id, source_id, homepage_status, discovered_count, fetched_count,
         skipped_existing_count, valid_article_count, failed_count,
         duplicate_count, rejected_short_count, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, source_id, homepage_result.status, counts["discovered"],
            counts["fetched"], counts["skipped"], counts["valid"], counts["failed"],
            counts["duplicates"], counts["rejected_short"],
            "; ".join(notes),
        ),
    )
    conn.commit()
    return counts | {"source_id": source_id, "source": source.get("name", source_id)}


def export_files(conn: sqlite3.Connection, output_dir: Path, run_id: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT * FROM articles WHERE item_kind IN ('ARTICLE', 'ARTICLE_EXCERPT') "
        "AND word_count >= ? ORDER BY source_name, published_at DESC, article_id",
        (MIN_ARTICLE_WORDS,),
    ).fetchall()
    with (output_dir / "articles.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
    cards = []
    for row in rows:
        body = row["body"] or ""
        cards.append(
            "<article class='card'>"
            f"<h2>{html.escape(row['title'])}</h2>"
            f"<p><b>{html.escape(row['source_name'])}</b> · "
            f"{html.escape(row['source_profile'] or 'UNCLASSIFIED')} · "
            f"{html.escape(row['original_language'])} · {row['word_count']} słów · "
            f"<a href='{html.escape(row['canonical_url'])}' target='_blank'>źródło</a></p>"
            f"<p class='meta'>status: {html.escape(row['content_status'])} · "
            f"pobrano: {html.escape(row['fetched_at'])}</p>"
            f"<details><summary>Pokaż treść</summary><pre>{html.escape(body)}</pre></details>"
            "</article>"
        )
    html_text = (
        "<!doctype html><meta charset='utf-8'><title>Article harvest</title>"
        "<style>body{font:14px system-ui;margin:24px;background:#f6f6f6}"
        ".card{background:#fff;border:1px solid #ddd;padding:16px;margin:12px 0}"
        "pre{white-space:pre-wrap;line-height:1.45}a{color:#0645ad}.meta{color:#666}</style>"
        f"<h1>Article harvest</h1><p>Run: {html.escape(run_id)} · artykuły: {len(rows)}</p>"
        + "".join(cards)
    )
    (output_dir / "articles_review.html").write_text(html_text, encoding="utf-8")
    summary = {
        "run_id": run_id,
        "generated_at": utc_now(),
        "articles_exported": len(rows),
        "content_status": dict(
            conn.execute("SELECT content_status, COUNT(*) FROM articles GROUP BY content_status").fetchall()
        ),
        "sources": [
            dict(row)
            for row in conn.execute(
                "SELECT source_id, source_id AS source, discovered_count, fetched_count, "
                "skipped_existing_count, valid_article_count, failed_count, "
                "duplicate_count, rejected_short_count, notes "
                "FROM source_run_results WHERE run_id = ? ORDER BY source_id",
                (run_id,),
            ).fetchall()
        ],
    }
    (output_dir / "harvest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist articles found on active source homepages.")
    parser.add_argument("--config", type=Path, default=Path("sources.yaml"))
    parser.add_argument("--db", type=Path, default=Path("article_harvest/articles.sqlite3"))
    parser.add_argument("--output-dir", type=Path, default=Path("article_harvest"))
    parser.add_argument(
        "--max-articles-per-source", type=int, default=50,
        help="0 means no local cap; use a safety cap for the first run.",
    )
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--retry-rejected", action="store_true")
    parser.add_argument("--source", action="append")
    args = parser.parse_args()
    defaults, sources = st.load_config(args.config)
    sources = [source for source in sources if source.get("enabled", True)]
    selected = set(args.source or [])
    if selected:
        sources = [source for source in sources if source.get("id") in selected]
    if not sources:
        raise SystemExit("Brak aktywnych źródeł.")
    conn = open_db(args.db)
    run_id = f"harvest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    conn.execute(
        "INSERT INTO harvest_runs (run_id, started_at, status, source_count) VALUES (?, ?, ?, ?)",
        (run_id, utc_now(), "RUNNING", len(sources)),
    )
    for source in sources:
        conn.execute(
            "INSERT OR REPLACE INTO sources "
            "(source_id, name, homepage, region, editorial_profile, source_type, enabled, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source["id"], source.get("name", source["id"]), source["homepage"],
                source.get("region", ""), st.infer_editorial_profile(source),
                source.get("source_type", "UNCLASSIFIED"), 1, utc_now(),
            ),
        )
        conn.execute(
            "UPDATE articles SET source_profile = ? "
            "WHERE source_id = ? AND (source_profile IS NULL OR source_profile = 'UNCLASSIFIED')",
            (st.infer_editorial_profile(source), source["id"]),
        )
    conn.commit()
    page_obj = None
    browser_context = None
    playwright_context = None
    try:
        if args.browser:
            from playwright.sync_api import sync_playwright
            playwright_context = sync_playwright().start()
            browser_context = playwright_context.chromium.launch(headless=True)
            page_obj = browser_context.new_page(user_agent=st.USER_AGENT)
        totals = {
            "discovered": 0, "fetched": 0, "skipped": 0, "valid": 0,
            "failed": 0, "duplicates": 0, "rejected_short": 0,
        }
        for index, source in enumerate(sources, 1):
            print(f"[{index}/{len(sources)}] {source.get('name', source['id'])} ...", flush=True)
            try:
                counts = harvest_source(conn, run_id, source, defaults, args, page_obj)
            except Exception as exc:
                counts = {
                    "source_id": source["id"], "source": source.get("name", source["id"]),
                    "discovered": 0, "fetched": 0, "skipped": 0, "valid": 0, "failed": 1,
                    "duplicates": 0, "rejected_short": 0,
                }
                conn.execute(
                    "INSERT OR REPLACE INTO source_run_results (run_id, source_id, notes) VALUES (?, ?, ?)",
                    (run_id, source["id"], f"source_error:{str(exc)[:300]}"),
                )
                conn.commit()
            print(
                f"  discovered={counts['discovered']} fetched={counts['fetched']} "
                f"skipped={counts['skipped']} valid={counts['valid']} "
                f"duplicates={counts['duplicates']} short={counts['rejected_short']} "
                f"failed={counts['failed']}",
                flush=True,
            )
            for key in totals:
                totals[key] += counts[key]
        conn.execute(
            """
            UPDATE harvest_runs
            SET finished_at = ?, status = ?, discovered_count = ?, fetched_count = ?,
                skipped_existing_count = ?, valid_article_count = ?, failed_count = ?
            WHERE run_id = ?
            """,
            (
                utc_now(), "COMPLETED", totals["discovered"], totals["fetched"],
                totals["skipped"], totals["valid"], totals["failed"], run_id,
            ),
        )
        conn.commit()
        export_files(conn, args.output_dir, run_id)
        print(json.dumps({"run_id": run_id, **totals}, ensure_ascii=False))
    finally:
        if browser_context is not None:
            browser_context.close()
        if playwright_context is not None:
            playwright_context.stop()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
