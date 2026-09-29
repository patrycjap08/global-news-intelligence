#!/usr/bin/env python3
"""Persistent first-pass article harvester.

RSS/Atom/news sitemap/sitemap/sections/homepage -> article links -> article
title/body -> SQLite + JSONL/HTML export.

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
import time
from typing import Any
import unicodedata
import urllib.parse

from pipeline_logging import log, seconds
import source_tester as st

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Brak PyYAML.") from exc


IGNORED_PATH_PARTS = (
    "/tag/", "/tags/", "/author/", "/authors/", "/category/",
    "/categories/", "/search", "/newsletter", "/podcast", "/video/",
    "/wideo/", "/live/", "/na-zywo/", "/transmisja/", "/transmisje/",
    "/gallery/", "/galeria/", "/slideshow/",
)
HTML_ASSET_SUFFIXES = st.NON_ARTICLE_EXTENSIONS | {".xml", ".json", ".txt"}
MIN_ARTICLE_WORDS = 100


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
            discovery_duration_ms INTEGER NOT NULL DEFAULT 0,
            fetch_duration_ms INTEGER NOT NULL DEFAULT 0,
            total_duration_ms INTEGER NOT NULL DEFAULT 0,
            average_article_fetch_ms INTEGER NOT NULL DEFAULT 0,
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
    ensure_column(conn, "source_run_results", "discovery_duration_ms", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "source_run_results", "fetch_duration_ms", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "source_run_results", "total_duration_ms", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "source_run_results", "average_article_fetch_ms", "INTEGER NOT NULL DEFAULT 0")
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
    direct = conn.execute(
        "SELECT * FROM articles WHERE source_id = ? AND canonical_url = ?",
        (source_id, canonical_url),
    ).fetchone()
    if direct is not None:
        return direct
    return conn.execute(
        "SELECT article.* FROM article_url_aliases alias "
        "JOIN articles article ON article.article_id = alias.duplicate_of_article_id "
        "WHERE alias.source_id = ? AND alias.candidate_url = ?",
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
        candidate_canonical = (
            st.canonicalize(candidate_url, source["homepage"]) or candidate_url
        )
        if candidate_canonical != canonical_url:
            conn.execute(
                "INSERT INTO article_url_aliases "
                "(source_id, candidate_url, duplicate_of_article_id, first_seen_at, last_seen_at, reason) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_id, candidate_url) DO UPDATE SET "
                "duplicate_of_article_id = excluded.duplicate_of_article_id, "
                "last_seen_at = excluded.last_seen_at, reason = excluded.reason",
                (
                    source_id, candidate_canonical, existing["article_id"], now, now,
                    "REDIRECTS_TO_EXISTING_CANONICAL",
                ),
            )
        conn.execute(
            "UPDATE articles SET last_seen_on_homepage_at = ? WHERE article_id = ?",
            (now, existing["article_id"]),
        )
        conn.execute(
            "INSERT OR REPLACE INTO run_articles "
            "(run_id, article_id, discovered_on_homepage, fetched_now) VALUES (?, ?, 1, 1)",
            (run_id, existing["article_id"]),
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
    extracted = st.extract_article(
        result, source["homepage"], include_body=True, source_id=str(source.get("id", ""))
    )
    method = "HTTP_HTML"
    browser_preferred = (
        str(source.get("id", "")) == "tvn24"
        and str(source.get("content_method", "")).upper() == "BROWSER"
    )
    if browser_enabled and page_obj is not None and (browser_preferred or not extracted.get("body_success")):
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
                browser_result,
                source["homepage"],
                include_body=True,
                source_id=str(source.get("id", "")),
            )
            if browser_extracted.get("body_success") or not extracted.get("title"):
                extracted = browser_extracted
                method = "BROWSER"
        except Exception as exc:
            extracted.setdefault("error", str(exc)[:300])
    return extracted, method


def _same_site_non_asset(url: str, homepage: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if not st.same_site(url, homepage):
        return False
    if any(parsed.path.lower().endswith(suffix) for suffix in HTML_ASSET_SUFFIXES):
        return False
    return bool(parsed.netloc)


def _candidate_allowed(source: dict[str, Any], url: str, title: str) -> bool:
    """Apply optional, source-specific discovery filters before fetching a page."""
    return st.candidate_allowed(source, url, title)


def _strip_candidate_query_keys(source: dict[str, Any], url: str) -> str:
    """Drop source-specific tracking parameters before deduplication and fetching."""
    keys = {
        str(key).strip().lower()
        for key in source.get("candidate_strip_query_keys", [])
        if str(key).strip()
    }
    if not keys:
        return url
    parsed = urllib.parse.urlsplit(url)
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in keys
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )


def _listing_rows(client: st.HttpClient, source: dict[str, Any]) -> tuple[list[dict[str, str]], st.FetchResult, list[str]]:
    """Read the homepage and configured sections, preserving feed metadata."""
    homepage = str(source["homepage"])
    endpoints = [homepage] if source.get("discover_homepage", True) else []
    endpoints.extend(source.get("section_urls", [])[:5])
    if not endpoints:
        endpoints = [homepage]
    first_endpoint = st.canonicalize(endpoints[0], homepage) or homepage
    homepage_result = client.get(first_endpoint)
    rows: list[dict[str, str]] = []
    notes: list[str] = []
    seen: set[str] = set()
    per_endpoint_limit = int(source.get("candidate_pool_per_section", 50) or 0)
    for endpoint in endpoints:
        absolute_endpoint = st.canonicalize(endpoint, homepage)
        if not absolute_endpoint or not st.same_site(absolute_endpoint, homepage):
            continue
        result = homepage_result if absolute_endpoint == first_endpoint else client.get(absolute_endpoint)
        parser = st.PageParser()
        try:
            parser.feed(result.text)
        except Exception:
            continue
        endpoint_count = 0
        for raw in parser.links:
            url = st.canonicalize(raw.get("href", ""), absolute_endpoint)
            rel = raw.get("rel", "").lower()
            link_type = raw.get("type", "").lower()
            is_feed_link = "alternate" in rel and (
                "rss" in link_type or "atom" in link_type or "feed" in link_type
            )
            if not url or url in seen or (not _same_site_non_asset(url, homepage) and not is_feed_link):
                continue
            if not is_feed_link and not _candidate_allowed(source, url, raw.get("text", "")):
                continue
            seen.add(url)
            rows.append({
                "url": url,
                "title": st.clean_text(raw.get("text", ""))[:500],
                "rel": raw.get("rel", ""),
                "type": raw.get("type", ""),
                "section_key": absolute_endpoint,
            })
            if not is_feed_link:
                endpoint_count += 1
                if per_endpoint_limit > 0 and endpoint_count >= per_endpoint_limit:
                    break
    section_count = len(source.get("section_urls", [])[:5])
    if section_count:
        notes.append(f"sections={section_count}")
    return rows, homepage_result, notes


def _feed_candidates(
    client: st.HttpClient,
    source: dict[str, Any],
    listing_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[str]]:
    homepage = str(source["homepage"])
    feeds: list[tuple[str, str]] = []
    for row in listing_rows:
        rel = row.get("rel", "").lower()
        kind = row.get("type", "").lower()
        if "alternate" in rel and ("rss" in kind or "atom" in kind or "feed" in kind):
            feeds.append(("ATOM" if "atom" in kind else "RSS", row["url"]))
    feeds.extend(("RSS", st.canonicalize(url, homepage) or url) for url in source.get("rss_urls", []))
    feeds.extend(("ATOM", st.canonicalize(url, homepage) or url) for url in source.get("atom_urls", []))
    rows: list[dict[str, str]] = []
    notes: list[str] = []
    seen_feeds: set[str] = set()
    for kind, endpoint in feeds:
        if not endpoint or endpoint in seen_feeds:
            continue
        seen_feeds.add(endpoint)
        result = client.get(endpoint, accept="application/rss+xml,application/atom+xml,application/xml,text/xml,*/*;q=0.1")
        parsed = st.parse_feed(result.text, endpoint) if result.status and result.status < 400 else []
        if parsed:
            notes.append(f"{kind.lower()}={len(parsed)}")
            for item in parsed:
                url = st.canonicalize(item.get("url", ""), homepage)
                if url:
                    url = _strip_candidate_query_keys(source, url)
                if url and _same_site_non_asset(url, homepage):
                    rows.append({"url": url, "title": st.clean_text(item.get("title", ""))[:500]})
    return rows, notes


def _html_fragment_text(fragment: str) -> str:
    """Turn a trusted publisher API HTML fragment into article text."""
    if not fragment:
        return ""
    if st.BeautifulSoup is None:
        return st.clean_text(re.sub(r"<[^>]+>", " ", fragment))
    soup = st.BeautifulSoup(fragment, "html.parser")
    for node in soup.select("script, style, noscript, template, svg, figure, aside, nav, footer"):
        node.decompose()
    nodes = soup.select("p, h2, h3, li")
    if nodes:
        return st.clean_text(" ".join(node.get_text(" ", strip=True) for node in nodes))
    return st.clean_text(soup.get_text(" ", strip=True))


def _wordpress_api_candidates(
    client: st.HttpClient,
    source: dict[str, Any],
) -> tuple[list[dict[str, str]], list[str]]:
    """Read public WordPress posts including their publisher-supplied body."""
    endpoint = str(source.get("wordpress_api_url", "") or "").strip()
    if not endpoint:
        return [], []
    result = client.get(endpoint, accept="application/json,*/*;q=0.1")
    try:
        payload = json.loads(result.text) if result.status and result.status < 400 else []
    except (TypeError, ValueError):
        payload = []
    if not isinstance(payload, list):
        return [], [f"wordpress_api_status={result.status or 'FAILED'}"]
    rows: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = st.canonicalize(str(item.get("link", "")), str(source["homepage"]))
        title_data = item.get("title") if isinstance(item.get("title"), dict) else {}
        content_data = item.get("content") if isinstance(item.get("content"), dict) else {}
        excerpt_data = item.get("excerpt") if isinstance(item.get("excerpt"), dict) else {}
        body = _html_fragment_text(str(content_data.get("rendered", "")))
        title = _html_fragment_text(str(title_data.get("rendered", "")))
        if not url or not body:
            continue
        rows.append({
            "url": url,
            "title": title,
            "api_title": title,
            "api_body": body,
            "api_description": _html_fragment_text(str(excerpt_data.get("rendered", ""))),
            "api_published_at": str(item.get("date_gmt") or item.get("date") or ""),
        })
    return rows, [f"wordpress_api={len(rows)}"]


def _sitemap_candidates(
    client: st.HttpClient,
    source: dict[str, Any],
    defaults: dict[str, Any],
    max_probes: int,
    max_children: int,
) -> tuple[list[dict[str, str]], list[str]]:
    homepage = str(source["homepage"])
    root = urllib.parse.urlsplit(homepage)
    root_url = f"{root.scheme}://{root.netloc}"
    robots_url = urllib.parse.urljoin(homepage, "/robots.txt")
    robots = client.get(robots_url, accept="text/plain,*/*;q=0.1")
    robots_sitemaps = [st.canonicalize(value, homepage) or value for value in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots.text)]
    configured = [st.canonicalize(url, homepage) for url in source.get("sitemap_urls", [])]
    endpoints = list(dict.fromkeys(
        robots_sitemaps + [url for url in configured if url] + [
            f"{root_url}/news-sitemap.xml", f"{root_url}/sitemap-news.xml",
            f"{root_url}/sitemap.xml", f"{root_url}/sitemap_index.xml",
            f"{root_url}/sitemap-index.xml",
        ]
    ))
    news_urls: list[str] = []
    sitemap_urls: list[str] = []
    child_urls: list[str] = []
    notes: list[str] = []
    for endpoint in endpoints[:max(1, max_probes)]:
        result = client.get(endpoint, accept="application/xml,text/xml,*/*;q=0.1")
        if not result.text or (result.status and result.status >= 400):
            continue
        urls, is_news, is_index = st.parse_sitemap(result.text, endpoint)
        if is_news:
            news_urls.extend(urls)
            notes.append(f"news_sitemap={len(urls)}")
        elif is_index:
            child_urls.extend(urls)
        elif urls:
            sitemap_urls.extend(urls)
            notes.append(f"sitemap={len(urls)}")
    for child in child_urls[:max(1, max_children)]:
        result = client.get(child, accept="application/xml,text/xml,*/*;q=0.1")
        urls, is_news, _ = st.parse_sitemap(result.text, child) if result.text else ([], False, False)
        if is_news:
            news_urls.extend(urls)
        else:
            sitemap_urls.extend(urls)
    rows = [{"url": url, "title": ""} for url in news_urls + sitemap_urls if _same_site_non_asset(url, homepage)]
    return rows, notes


def _browser_listing_rows(page_obj: Any, source: dict[str, Any], timeout_ms: int) -> tuple[list[dict[str, str]], int]:
    homepage = str(source["homepage"])
    endpoints = ([homepage] if source.get("discover_homepage", True) else []) + source.get("section_urls", [])[:5]
    if not endpoints:
        endpoints = [homepage]
    per_endpoint_limit = int(source.get("candidate_pool_per_section", 50) or 0)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    filtered = 0
    for endpoint in endpoints:
        absolute_endpoint = st.canonicalize(endpoint, homepage)
        if not absolute_endpoint or not st.same_site(absolute_endpoint, homepage):
            continue
        try:
            st.browser_navigate(page_obj, absolute_endpoint, timeout_ms)
            st.browser_prepare_page(page_obj, source)
            parser = st.PageParser()
            parser.feed(page_obj.content())
        except Exception:
            continue
        endpoint_count = 0
        for raw in parser.links:
            url = st.canonicalize(raw.get("href", ""), absolute_endpoint)
            if not url or url in seen or not _same_site_non_asset(url, homepage):
                continue
            if not st.ARTICLE_HINTS.search(url) and len(st.clean_text(raw.get("text", ""))) < 30:
                continue
            if not _candidate_allowed(source, url, raw.get("text", "")):
                filtered += 1
                continue
            seen.add(url)
            rows.append({"url": url, "title": st.clean_text(raw.get("text", ""))[:500], "section_key": absolute_endpoint})
            endpoint_count += 1
            if per_endpoint_limit > 0 and endpoint_count >= per_endpoint_limit:
                break
    return rows, filtered


def discover_candidates(
    client: st.HttpClient,
    source: dict[str, Any],
    defaults: dict[str, Any],
    args: argparse.Namespace,
    page_obj: Any,
) -> tuple[st.FetchResult, list[dict[str, str]], list[str]]:
    """Use the same discovery families as the source tester, then deduplicate."""
    listing_rows, homepage_result, notes = _listing_rows(client, source)
    api_rows, api_notes = _wordpress_api_candidates(client, source)
    feed_rows, feed_notes = _feed_candidates(client, source, listing_rows)
    sitemap_rows, sitemap_notes = _sitemap_candidates(
        client, source, defaults, args.max_sitemap_probes, args.max_sitemap_children
    )
    section_rows = [
        {"url": row["url"], "title": row.get("title", ""), "section_key": row.get("section_key", "")}
        for row in listing_rows
        if st.ARTICLE_HINTS.search(row["url"]) or len(row.get("title", "")) >= 30
    ]
    discovery_method = str(source.get("discovery_method", "")).upper()
    ordered: list[dict[str, str]] = []
    if discovery_method == "API":
        ordered.extend(api_rows)
        ordered.extend(feed_rows)
        ordered.extend(section_rows)
        ordered.extend(sitemap_rows)
    elif discovery_method in {"RSS", "ATOM"}:
        ordered.extend(feed_rows)
        ordered.extend(api_rows)
        ordered.extend(sitemap_rows)
        ordered.extend(section_rows)
    elif discovery_method in {"NEWS_SITEMAP", "SITEMAP"}:
        ordered.extend(sitemap_rows)
        ordered.extend(feed_rows)
        ordered.extend(section_rows)
    elif discovery_method == "SECTION_HTML":
        ordered.extend(section_rows)
        ordered.extend(feed_rows)
        ordered.extend(sitemap_rows)
    else:
        ordered.extend(api_rows)
        ordered.extend(feed_rows)
        ordered.extend(sitemap_rows)
        ordered.extend(section_rows)

    needs_browser = bool(
        args.browser and source.get("browser_discovery", True) and (
            not ordered
            or discovery_method == "BROWSER"
            or source.get("browser_accept_selectors")
            or source.get("browser_close_selectors")
            or source.get("browser_click_texts")
        )
    )
    if needs_browser and page_obj is not None:
        try:
            browser_rows, browser_filtered = _browser_listing_rows(
                page_obj, source, int(float(source.get("timeout_seconds", defaults.get("timeout_seconds", 15))) * 1000)
            )
            ordered = browser_rows + ordered
            notes.append(f"browser_discovery={len(browser_rows)}")
            if browser_filtered:
                notes.append(f"browser_filtered={browser_filtered}")
        except Exception as exc:
            notes.append(f"browser_discovery_error:{str(exc)[:160]}")

    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in ordered:
        url = st.canonicalize(row.get("url", ""), source["homepage"])
        if not url or url in seen or not _same_site_non_asset(url, source["homepage"]):
            continue
        if not _candidate_allowed(source, url, row.get("title", "")):
            continue
        seen.add(url)
        candidate = {
            "url": url,
            "title_hint": row.get("title", ""),
            "section_key": row.get("section_key", ""),
        }
        for key in ("api_title", "api_body", "api_description", "api_published_at"):
            if row.get(key):
                candidate[key] = row[key]
        unique.append(candidate)
        if args.discovery_limit_per_source > 0 and len(unique) >= args.discovery_limit_per_source:
            break
    notes.extend(api_notes)
    notes.extend(feed_notes)
    notes.extend(sitemap_notes)
    if homepage_result.status and homepage_result.status >= 400:
        notes.append(f"homepage_status={homepage_result.status}")
    if not unique:
        notes.append("no_candidates")
    return homepage_result, unique, notes


def daily_fetched_attempts(conn: sqlite3.Connection, source_id: str, now: str) -> int:
    day = now[:10]
    row = conn.execute(
        "SELECT COALESCE(SUM(result.fetched_count), 0) "
        "FROM source_run_results result JOIN harvest_runs run ON run.run_id = result.run_id "
        "WHERE result.source_id = ? AND substr(run.started_at, 1, 10) = ?",
        (source_id, day),
    ).fetchone()
    return int(row[0] or 0)


def harvest_source(
    conn: sqlite3.Connection,
    run_id: str,
    source: dict[str, Any],
    defaults: dict[str, Any],
    args: argparse.Namespace,
    page_obj: Any,
) -> dict[str, Any]:
    source_started = time.monotonic()
    source_id = str(source["id"])
    client = st.HttpClient(
        float(source.get("timeout_seconds", defaults.get("timeout_seconds", 15))),
        int(source.get("min_delay_ms", defaults.get("min_delay_ms", 500))),
        int(source.get("max_retries", defaults.get("max_retries", 1))),
    )
    now = utc_now()
    discovery_started = time.monotonic()
    homepage_result, candidates, notes = discover_candidates(
        client, source, defaults, args, page_obj
    )
    discovery_duration_ms = round((time.monotonic() - discovery_started) * 1000)
    candidate_pool = candidates
    next_candidate_index = len(candidate_pool)
    top_articles_per_section = int(source.get("top_articles_per_section", 0) or 0)
    section_followups: dict[str, list[dict[str, str]]] = {}
    if top_articles_per_section > 0:
        selected_by_section: dict[str, int] = {}
        selected: list[dict[str, str]] = []
        for candidate in candidate_pool:
            section_key = candidate.get("section_key", "")
            if not section_key:
                continue
            if selected_by_section.get(section_key, 0) < top_articles_per_section:
                selected.append(candidate)
                selected_by_section[section_key] = selected_by_section.get(section_key, 0) + 1
            else:
                section_followups.setdefault(section_key, []).append(candidate)
        candidates = selected
        notes.append(f"section_window={top_articles_per_section}x{len(selected_by_section)}")
    top_articles_per_source = int(source.get("top_articles_per_source", args.top_articles_per_source) or 0)
    if top_articles_per_source > 0 and top_articles_per_section <= 0:
        discovered_before_window = len(candidate_pool)
        candidates = candidate_pool[:top_articles_per_source]
        next_candidate_index = len(candidates)
        notes.append(f"top_window={top_articles_per_source}")
        if discovered_before_window > len(candidates):
            notes.append(f"candidates_trimmed={discovered_before_window - len(candidates)}")
    attempts_today = daily_fetched_attempts(conn, source_id, now)
    remaining_daily = max(0, args.daily_max_articles_per_source - attempts_today) if args.daily_max_articles_per_source > 0 else None
    if remaining_daily == 0:
        notes.append(f"daily_limit_reached={args.daily_max_articles_per_source}")
    counts = {
        "discovered": len(candidates), "fetched": 0,
        "skipped_existing": 0, "skipped_rejected": 0,
        "valid": 0, "failed": 0, "duplicates": 0, "rejected_short": 0,
    }

    short_followups = 0
    resolved_existing_after_fetch = 0
    rejected_other: dict[str, int] = {}
    fetch_duration_ms = 0

    def queue_short_followup(candidate: dict[str, str]) -> None:
        nonlocal next_candidate_index, short_followups
        if top_articles_per_section > 0:
            section_queue = section_followups.get(candidate.get("section_key", ""), [])
            if not section_queue:
                return
            candidates.append(section_queue.pop(0))
            counts["discovered"] += 1
            short_followups += 1
            return
        if top_articles_per_source <= 0 or next_candidate_index >= len(candidate_pool):
            return
        candidates.append(candidate_pool[next_candidate_index])
        next_candidate_index += 1
        counts["discovered"] += 1
        short_followups += 1

    candidate_index = 0
    while candidate_index < len(candidates):
        candidate = candidates[candidate_index]
        candidate_index += 1
        url = candidate["url"]
        canonical = st.canonicalize(url, source["homepage"]) or url
        existing = existing_article(conn, source_id, canonical)
        rejection = existing_rejection(conn, source_id, canonical)
        rejection_is_still_below_threshold = bool(
            rejection is not None
            and str(rejection["reason"]) == "TOO_SHORT"
            and int(rejection["word_count"] or 0) < MIN_ARTICLE_WORDS
        )
        if existing is None and rejection is not None and not args.retry_rejected and rejection_is_still_below_threshold:
            conn.execute(
                "UPDATE rejected_candidates SET last_seen_at = ? "
                "WHERE source_id = ? AND canonical_url = ?",
                (now, source_id, canonical),
            )
            counts["skipped_rejected"] += 1
            counts["rejected_short"] += 1
            queue_short_followup(candidate)
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
            counts["skipped_existing"] += 1
            continue
        if remaining_daily is not None and counts["fetched"] >= remaining_daily:
            notes.append("daily_limit_stop")
            break
        fetch_started = time.monotonic()
        fetch_measured = False
        try:
            if candidate.get("api_body"):
                api_body = str(candidate.get("api_body", ""))
                extracted = {
                    "url": url,
                    "status": 200,
                    "title": str(candidate.get("api_title") or candidate.get("title_hint") or ""),
                    "description": str(candidate.get("api_description", "")),
                    "author": "",
                    "published_at": str(candidate.get("api_published_at", "")),
                    "body_success": bool(api_body),
                    "word_count": len(api_body.split()),
                    "paywall": False,
                    "captcha": False,
                    "content_hash": hashlib.sha256(api_body.encode("utf-8")).hexdigest(),
                    "body": api_body,
                }
                method = "WORDPRESS_API"
            else:
                extracted, method = fetch_one(client, page_obj, source, url, args.browser)
            fetch_duration_ms += round((time.monotonic() - fetch_started) * 1000)
            fetch_measured = True
            _, inserted, valid, outcome = save_article(
                conn, run_id, source, url, extracted, method, now, candidate.get("title_hint", "")
            )
            counts["fetched"] += 1
            counts["valid"] += int(valid and inserted)
            counts["duplicates"] += int(outcome == "duplicate")
            is_short = outcome == "rejected" and classify_item(extracted)[1] == "TOO_SHORT"
            counts["rejected_short"] += int(is_short)
            resolved_existing_after_fetch += int(outcome == "existing")
            if outcome == "rejected" and not is_short:
                rejection_status = classify_item(extracted)[1]
                rejected_other[rejection_status] = rejected_other.get(rejection_status, 0) + 1
            if is_short:
                queue_short_followup(candidate)
        except Exception as exc:
            if not fetch_measured:
                fetch_duration_ms += round((time.monotonic() - fetch_started) * 1000)
            failed = {
                "url": url, "status": None, "title": candidate.get("title_hint", ""),
                "body_success": False, "word_count": 0, "error": str(exc)[:300],
            }
            save_article(conn, run_id, source, url, failed, "ERROR", now, candidate.get("title_hint", ""))
            counts["fetched"] += 1
            counts["failed"] += 1
    if short_followups:
        notes.append(f"short_followups={short_followups}")
    if counts["skipped_rejected"]:
        notes.append(f"previously_rejected_short={counts['skipped_rejected']}")
    if resolved_existing_after_fetch:
        notes.append(f"existing_after_redirect={resolved_existing_after_fetch}")
    if rejected_other:
        notes.append(
            "rejected_other="
            + ",".join(
                f"{status}:{count}"
                for status, count in sorted(rejected_other.items())
            )
        )
    total_duration_ms = round((time.monotonic() - source_started) * 1000)
    average_article_fetch_ms = round(fetch_duration_ms / counts["fetched"]) if counts["fetched"] else 0
    conn.execute(
        """
        INSERT OR REPLACE INTO source_run_results
        (run_id, source_id, homepage_status, discovered_count, fetched_count,
         skipped_existing_count, valid_article_count, failed_count,
         duplicate_count, rejected_short_count, discovery_duration_ms,
         fetch_duration_ms, total_duration_ms, average_article_fetch_ms, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, source_id, homepage_result.status, counts["discovered"],
            counts["fetched"], counts["skipped_existing"], counts["valid"], counts["failed"],
            counts["duplicates"], counts["rejected_short"],
            discovery_duration_ms, fetch_duration_ms, total_duration_ms,
            average_article_fetch_ms,
            "; ".join(notes),
        ),
    )
    conn.commit()
    return counts | {
        "skipped": counts["skipped_existing"] + counts["skipped_rejected"],
        "source_id": source_id,
        "source": source.get("name", source_id),
        "discovery_duration_ms": discovery_duration_ms,
        "fetch_duration_ms": fetch_duration_ms,
        "total_duration_ms": total_duration_ms,
        "average_article_fetch_ms": average_article_fetch_ms,
        "notes": "; ".join(notes),
    }


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
    parser = argparse.ArgumentParser(description="Discover and persist new articles from configured source feeds, sitemaps and listings.")
    parser.add_argument("--config", type=Path, default=Path("sources.yaml"))
    parser.add_argument("--runtime-config", type=Path, default=Path("source_runtime.yaml"))
    parser.add_argument("--db", type=Path, default=Path("article_harvest/articles.sqlite3"))
    parser.add_argument("--output-dir", type=Path, default=Path("article_harvest"))
    parser.add_argument("--daily-max-articles-per-source", type=int, default=0)
    parser.add_argument(
        "--top-articles-per-source", type=int, default=10,
        help="Only inspect the first N discovered articles per source in this run; do not fill from older links.",
    )
    parser.add_argument("--max-articles-per-source", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--discovery-limit-per-source", type=int, default=500)
    parser.add_argument("--max-sitemap-probes", type=int, default=6)
    parser.add_argument("--max-sitemap-children", type=int, default=3)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--retry-rejected", action="store_true")
    parser.add_argument("--source", action="append")
    args = parser.parse_args()
    if args.max_articles_per_source is not None:
        # Backward-compatible alias. Its meaning is now the daily cap.
        args.daily_max_articles_per_source = args.max_articles_per_source
    defaults, sources = st.load_config(args.config)
    if args.runtime_config.exists():
        runtime_data = yaml.safe_load(args.runtime_config.read_text(encoding="utf-8")) or {}
        runtime_by_id = {str(row.get("id")): row for row in runtime_data.get("sources", [])}
        for source in sources:
            runtime = runtime_by_id.get(str(source.get("id")), {})
            for key in ("discovery_method", "content_method", "technical_status"):
                # A hand-maintained source override is newer and more precise
                # than the historical tester recommendation in source_runtime.
                if runtime.get(key) and not source.get(key):
                    source[key] = runtime[key]
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
            # Keep the normal Chromium user-agent for JS/browser fallbacks.
            # TVN24 rejects the crawler-identifying HTTP user-agent with 403;
            # HTTP discovery still uses st.USER_AGENT separately.
            page_obj = browser_context.new_page()
        totals = {
            "discovered": 0, "fetched": 0, "skipped_existing": 0,
            "skipped_rejected": 0, "valid": 0,
            "failed": 0, "duplicates": 0, "rejected_short": 0,
        }
        for index, source in enumerate(sources, 1):
            source_name = source.get("name", source["id"])
            log("HARVEST", f"Źródło {index}/{len(sources)}: {source_name} — wyszukuję nowe materiały.")
            try:
                counts = harvest_source(conn, run_id, source, defaults, args, page_obj)
            except Exception as exc:
                counts = {
                    "source_id": source["id"], "source": source.get("name", source["id"]),
                    "discovered": 0, "fetched": 0, "skipped_existing": 0,
                    "skipped_rejected": 0, "valid": 0, "failed": 1,
                    "duplicates": 0, "rejected_short": 0, "notes": f"source_error:{str(exc)[:300]}",
                }
                conn.execute(
                    "INSERT OR REPLACE INTO source_run_results (run_id, source_id, notes) VALUES (?, ?, ?)",
                    (run_id, source["id"], f"source_error:{str(exc)[:300]}"),
                )
                conn.commit()
            log(
                "HARVEST",
                f"Źródło {index}/{len(sources)} zakończone: "
                f"znaleziono: {counts['discovered']}, pobrano: {counts['fetched']}, "
                f"zapisano: {counts['valid']}, już zapisane: {counts['skipped_existing']}, "
                f"wcześniej odrzucone jako za krótkie: {counts['skipped_rejected']}, "
                f"odrzucone teraz jako za krótkie: {counts['rejected_short']}, "
                f"duplikaty: {counts['duplicates']}, błędy: {counts['failed']}"
                + (
                    f", czas {seconds(counts['total_duration_ms'] / 1000)}"
                    if counts.get("total_duration_ms") is not None else ""
                ),
            )
            if "daily_limit_stop" in counts.get("notes", ""):
                log("HARVEST", "Osiągnięto limit pobierania dla tego źródła; reszta kandydatów czeka na kolejny przebieg.", level="WARN")
            if counts.get("notes", "").startswith("source_error:"):
                log("HARVEST", counts["notes"][len("source_error:"):], level="ERROR")
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
                totals["skipped_existing"], totals["valid"], totals["failed"], run_id,
            ),
        )
        conn.commit()
        export_files(conn, args.output_dir, run_id)
        log(
            "HARVEST",
            f"Zakończono run {run_id}: zapisano: {totals['valid']}; "
            f"już zapisane: {totals['skipped_existing']}; "
            f"wcześniej odrzucone jako za krótkie: {totals['skipped_rejected']}; "
            f"odrzucone teraz jako za krótkie: {totals['rejected_short']}; "
            f"duplikaty: {totals['duplicates']}; błędy: {totals['failed']}.",
        )
    finally:
        if browser_context is not None:
            browser_context.close()
        if playwright_context is not None:
            playwright_context.stop()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
