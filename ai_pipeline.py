#!/usr/bin/env python3
"""Three-stage OpenAI processing for the harvested articles.

The worker deliberately stores model output as JSON and keeps article_ids next
to claims. This makes the UI able to show the evidence instead of presenting a
citation-free model narrative.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import heapq
import hashlib
from itertools import combinations
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import time
from typing import Any
import unicodedata

from pipeline_logging import log, quantity, seconds, short_text
from supabase_client import SupabaseRestClient


PROMPT_VERSION = "ai-prompts-v42-stricter-merges-nonrepeating-updates"
# Keep a longer matching window than the UI's current-topic window. A topic
# may leave the "Aktualne" tab after 30 hours and still accept a matching
# article until it has been quiet for 55 hours.
TOPIC_MATCH_LOOKBACK_HOURS = 55
UNASSIGNED_ARTICLE_LOOKBACK_HOURS = max(
    1, int(os.environ.get("AI_UNASSIGNED_ARTICLE_LOOKBACK_HOURS", "24"))
)
# The merge pass should recover near-duplicate stories split across grouping
# batches.  The prompt still requires a concrete shared event/story anchor;
# this threshold leaves room for different headlines and reporting angles.
TOPIC_MERGE_MIN_CONFIDENCE = float(
    os.environ.get("AI_TOPIC_MERGE_MIN_CONFIDENCE", "0.84")
)
TOPIC_MERGE_MAX_TOPICS_PER_REQUEST = max(
    10, int(os.environ.get("AI_TOPIC_MERGE_MAX_TOPICS_PER_REQUEST", "100"))
)
TOPIC_MERGE_MAX_RECENT_TITLES = max(
    1, int(os.environ.get("AI_TOPIC_MERGE_MAX_RECENT_TITLES", "1"))
)
TOPIC_MERGE_TITLE_CHAR_LIMIT = max(
    80, int(os.environ.get("AI_TOPIC_MERGE_TITLE_CHAR_LIMIT", "220"))
)
TOPIC_MERGE_DESCRIPTION_CHAR_LIMIT = max(
    160, int(os.environ.get("AI_TOPIC_MERGE_DESCRIPTION_CHAR_LIMIT", "450"))
)
TOPIC_MERGE_SUMMARY_CHAR_LIMIT = max(
    500, int(os.environ.get("AI_TOPIC_MERGE_SUMMARY_CHAR_LIMIT", "1800"))
)
TOPIC_MERGE_MAX_OUTPUT_TOKENS = max(
    1000, int(os.environ.get("AI_TOPIC_MERGE_MAX_OUTPUT_TOKENS", "12000"))
)
TOPIC_MERGE_MAX_REQUESTS = min(
    20, max(1, int(os.environ.get("AI_TOPIC_MERGE_MAX_REQUESTS", "20")))
)
TOPIC_MERGE_EMBEDDINGS_ENABLED = (
    os.environ.get("AI_TOPIC_MERGE_EMBEDDINGS_ENABLED", "1").strip().lower()
    not in {"0", "false", "no", "off"}
)
TOPIC_MERGE_EMBEDDING_MODEL = os.environ.get(
    "OPENAI_TOPIC_EMBEDDING_MODEL", "text-embedding-3-small"
)
TOPIC_MERGE_EMBEDDING_BATCH_SIZE = max(
    25, int(os.environ.get("AI_TOPIC_MERGE_EMBEDDING_BATCH_SIZE", "100"))
)
TOPIC_MERGE_EMBEDDING_DIMENSIONS = max(
    64, int(os.environ.get("AI_TOPIC_MERGE_EMBEDDING_DIMENSIONS", "256"))
)
TOPIC_MERGE_EMBEDDING_TOP_K = min(
    3, max(1, int(os.environ.get("AI_TOPIC_MERGE_EMBEDDING_TOP_K", "3")))
)
TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY = max(
    0.90, float(os.environ.get("AI_TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY", "0.90"))
)
TOPIC_MERGE_EMBEDDING_REQUEST_TIMEOUT_SECONDS = max(
    20.0,
    float(os.environ.get("AI_TOPIC_MERGE_EMBEDDING_REQUEST_TIMEOUT_SECONDS", "60")),
)
TOPIC_MERGE_EMBEDDING_MAX_RETRIES = max(
    1, int(os.environ.get("AI_TOPIC_MERGE_EMBEDDING_MAX_RETRIES", "2"))
)
CATEGORY_BATCH_SIZE = max(
    10, int(os.environ.get("AI_CATEGORY_BATCH_SIZE", "30"))
)
CATEGORY_MIN_RETRY_BATCH_SIZE = max(
    5, int(os.environ.get("AI_CATEGORY_MIN_RETRY_BATCH_SIZE", "10"))
)
CATEGORY_MAX_OUTPUT_TOKENS = max(
    1000, int(os.environ.get("AI_CATEGORY_MAX_OUTPUT_TOKENS", "5000"))
)
CATEGORY_REQUEST_TIMEOUT_SECONDS = max(
    15.0, float(os.environ.get("AI_CATEGORY_REQUEST_TIMEOUT_SECONDS", "45"))
)
CATEGORY_MAX_RETRIES = max(
    1, int(os.environ.get("AI_CATEGORY_MAX_RETRIES", "2"))
)
DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
LABEL_MODEL = os.environ.get("OPENAI_LABEL_MODEL", "gpt-4o-mini")
TITLE_MODEL = os.environ.get("OPENAI_TITLE_MODEL", LABEL_MODEL)
GROUPING_EXCERPT_WORDS = min(
    100,
    max(20, int(os.environ.get("AI_GROUPING_EXCERPT_WORDS", "100"))),
)
LABEL_EXCERPT_WORDS = min(
    100,
    max(20, int(os.environ.get("AI_LABEL_EXCERPT_WORDS", "100"))),
)
MIN_ARTICLE_WORDS = 100
MAX_GROUPING_BATCH_SIZE = 50
MIN_GROUPING_RETRY_BATCH_SIZE = 25
# Naming is a separate, smaller request, so keep its payload below the
# legacy repair grouper's limit.
MAX_LABEL_BATCH_SIZE = 25
MIN_LABEL_RETRY_BATCH_SIZE = max(5, MAX_LABEL_BATCH_SIZE // 2)
LABEL_MAX_OUTPUT_TOKENS = max(
    16000, int(os.environ.get("AI_LABEL_MAX_OUTPUT_TOKENS", "16000"))
)
LABEL_REQUEST_TIMEOUT_SECONDS = max(
    20.0, float(os.environ.get("AI_LABEL_REQUEST_TIMEOUT_SECONDS", "60"))
)
LABEL_MAX_RETRIES = max(
    1, int(os.environ.get("AI_LABEL_MAX_RETRIES", "2"))
)
TITLE_NORMALIZATION_BATCH_SIZE = max(
    5, int(os.environ.get("AI_TITLE_NORMALIZATION_BATCH_SIZE", "25"))
)
TITLE_NORMALIZATION_MAX_OUTPUT_TOKENS = max(
    1000, int(os.environ.get("AI_TITLE_NORMALIZATION_MAX_OUTPUT_TOKENS", "4000"))
)
TITLE_NORMALIZATION_REQUEST_TIMEOUT_SECONDS = max(
    20.0,
    float(os.environ.get("AI_TITLE_NORMALIZATION_REQUEST_TIMEOUT_SECONDS", "60")),
)
TITLE_NORMALIZATION_MAX_RETRIES = max(
    1, int(os.environ.get("AI_TITLE_NORMALIZATION_MAX_RETRIES", "2"))
)
GROUPING_MIN_CONFIDENCE = float(os.environ.get("AI_GROUPING_MIN_CONFIDENCE", "0.70"))
OPENAI_MAX_RETRIES = max(2, int(os.environ.get("OPENAI_MAX_RETRIES", "4")))
OPENAI_RETRY_BASE_SECONDS = max(
    0.5, float(os.environ.get("OPENAI_RETRY_BASE_SECONDS", "2"))
)
OPENAI_REQUEST_TIMEOUT_SECONDS = max(
    15.0, float(os.environ.get("OPENAI_REQUEST_TIMEOUT_SECONDS", "90"))
)
SUMMARY_REQUEST_TIMEOUT_SECONDS = max(
    30.0, float(os.environ.get("AI_SUMMARY_REQUEST_TIMEOUT_SECONDS", "180"))
)
SUMMARY_MAX_PAYLOAD_CHARS = max(
    50000, int(os.environ.get("AI_SUMMARY_MAX_PAYLOAD_CHARS", "300000"))
)
SUMMARY_FALLBACK_EXCERPT_WORDS = max(
    200, int(os.environ.get("AI_SUMMARY_FALLBACK_EXCERPT_WORDS", "900"))
)
AI_BREAK_TAG_RE = re.compile(r"<\s*/?\s*br\s*/?\s*>", re.IGNORECASE)

TITLE_PREFIX_RE = re.compile(r"^\[([^\]\r\n]{2,80})\]\s+(\S.*)$")
COMPOSITE_GEO_PREFIX_RE = re.compile(r"(?:,|/|&|\s+(?:i|oraz)\s+)", re.IGNORECASE)
# These are single country names even though their Polish names contain the
# conjunction "i". They must not be mistaken for a list of countries.
SINGLE_COUNTRY_GEO_PREFIXES = {
    "antigua i barbuda",
    "bośnia i hercegowina",
    "trynidad i tobago",
    "wyspy świętego tomasza i książęca",
}
PLACEHOLDER_TOPIC_TITLES = {
    "neutralna nazwa wydarzenia",
    "neutralny wspólny tytuł",
    "temat bez tytułu",
    "połączony temat",
    "konkretny tytuł",
    "konkretny tytuł wydarzenia",
    "wymaga doprecyzowania tematu",
}

TOPIC_CATEGORY_VALUES = (
    "POLSKA",
    "POLITYKA",
    "SWIAT",
    "GOSPODARKA",
    "SPOLECZENSTWO",
    "TECHNOLOGIA",
    "ZDROWIE",
    "KULTURA_SPORT",
)

TOPIC_CATEGORY_ALIASES = {
    "POLSKA": "POLSKA",
    "POLAND": "POLSKA",
    "POLITYKA": "POLITYKA",
    "POLITICS": "POLITYKA",
    "SWIAT": "SWIAT",
    "ŚWIAT": "SWIAT",
    "WORLD": "SWIAT",
    "GOSPODARKA": "GOSPODARKA",
    "ECONOMY": "GOSPODARKA",
    "SPOLECZENSTWO": "SPOLECZENSTWO",
    "SPOŁECZEŃSTWO": "SPOLECZENSTWO",
    "SOCIETY": "SPOLECZENSTWO",
    "TECHNOLOGIA": "TECHNOLOGIA",
    "TECHNOLOGY": "TECHNOLOGIA",
    "ZDROWIE": "ZDROWIE",
    "HEALTH": "ZDROWIE",
    "KULTURA_SPORT": "KULTURA_SPORT",
    "KULTURA I SPORT": "KULTURA_SPORT",
    "CULTURE_AND_SPORT": "KULTURA_SPORT",
    "CULTURE_SPORT": "KULTURA_SPORT",
}


def normalize_topic_categories(value: Any) -> list[str]:
    """Return unique public category keys while preserving model order."""
    values = value if isinstance(value, list) else [value]
    categories: list[str] = []
    for item in values:
        raw = re.sub(r"\s+", " ", str(item or "").strip()).upper()
        category = TOPIC_CATEGORY_ALIASES.get(raw)
        if category and category not in categories:
            categories.append(category)
    return categories[:3]


def normalize_topic_category(value: Any) -> str | None:
    """Compatibility helper for older scalar category payloads."""
    return (normalize_topic_categories(value) or [None])[0]


def _title_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold().rstrip(".!?")


def is_placeholder_topic_title(value: Any) -> bool:
    """Reject prompt examples and code fallbacks as published topic titles."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return True
    match = TITLE_PREFIX_RE.match(text)
    core = match.group(2).strip() if match else text
    key = _title_key(core)
    return (
        key in PLACEHOLDER_TOPIC_TITLES
        or key.startswith("neutralna nazwa")
        or key.startswith("neutralny wspólny")
        or key.startswith("temat bez tytułu")
        or key.startswith("połączony temat")
    )


def is_usable_topic_title(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(TITLE_PREFIX_RE.match(text)) and not is_placeholder_topic_title(text)


def has_composite_geo_prefix(value: Any) -> bool:
    """Return whether a title prefix lists more than one geographic scope."""
    match = TITLE_PREFIX_RE.match(str(value or "").strip())
    if not match:
        return False
    prefix = re.sub(r"\s+", " ", match.group(1).strip()).casefold()
    if prefix in SINGLE_COUNTRY_GEO_PREFIXES:
        return False
    return bool(COMPOSITE_GEO_PREFIX_RE.search(prefix))


def format_topic_title_candidate(candidate: Any, current_title: Any = "") -> str:
    """Give a real title a prefix when the model forgot the required format."""
    text = re.sub(r"\s+", " ", str(candidate or "").strip())[:300]
    if not text or is_placeholder_topic_title(text):
        return ""
    if TITLE_PREFIX_RE.match(text):
        return text
    if text.startswith("["):
        return ""
    current_match = TITLE_PREFIX_RE.match(str(current_title or "").strip())
    prefix = f"[{current_match.group(1)}]" if current_match else "[Świat]"
    return f"{prefix} {text}"[:300]


def _topic_title_core(value: Any) -> str:
    """Return a topic title without its optional geographic prefix."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    match = TITLE_PREFIX_RE.match(text)
    return match.group(2).strip() if match else text


def _headline_key(value: Any) -> str:
    """Normalize a headline enough to detect verbatim topic-title copying."""
    return re.sub(r"[^\w]+", " ", _topic_title_core(value).casefold()).strip()


def is_article_title_copy(candidate: Any, article_titles: list[str]) -> bool:
    """Detect a topic label that merely repeats one of its article headlines."""
    candidate_key = _headline_key(candidate)
    if not candidate_key:
        return False
    return any(
        candidate_key == _headline_key(article_title)
        for article_title in article_titles
        if str(article_title or "").strip()
    )


MERGE_NON_DISTINCTIVE_TOKENS = frozenset({
    # Polish function words and common newsroom language.
    "aby", "albo", "ale", "bez", "byc", "być", "co", "czy", "dla", "do",
    "gdzie", "gdy", "jego", "jej", "jest", "juz", "już", "jak", "jako",
    "jeden", "jedna", "jedno", "jego", "ich", "inne", "inny", "innych",
    "iż", "ktora", "która", "ktore", "które", "ktory", "który", "miedzy",
    "między", "na", "nad", "nie", "nim", "niż", "nowe", "nowy", "nowa",
    "oraz", "po", "pod", "przed", "przez", "się", "swoje", "swoim", "ta",
    "tak", "takze", "także", "te", "ten", "tej", "temat", "to", "tu", "tylko",
    "tym", "tytuł", "tytul", "w", "wedlug", "według", "we", "wobec", "z", "za",
    "ze", "że",
    # Words that occur in many unrelated news headlines.
    "aktualizacja", "aktualizacje", "artykul", "artykuł", "decyzja", "decyzje",
    "dzis", "dzisiaj", "dzisiejszy", "dzisiejsza", "dzisiejsze", "doniesienia",
    "informacja", "informacje", "komentarz", "kontekst", "kraj", "kraju",
    "minister", "najnowze", "najnowsze", "nowosci", "nowości", "polityka",
    "prezydent", "prezydenci", "wspolna", "wspolne", "wspolny",
    "wspólna", "wspólne", "wspólny",
    "powiedzial", "powiedział", "reakcja", "reakcje", "relacja", "relacje",
    "raport", "sprawa", "sprawie", "sytuacja", "slowa", "słowa", "wazne",
    "ważne", "wiadomosci", "wiadomości", "wydarzenie", "wydarzenia", "wystapienie",
    "wystąpienie", "zapowiedzial", "zapowiedział", "zobacz", "zobaczcie",
    # Common English headline words from international sources.
    "about", "after", "also", "and", "are", "been", "before", "from", "has",
    "have", "his", "how", "into", "its", "latest", "more", "new", "news", "not",
    "over", "said", "says", "that", "the", "their", "these", "this", "today", "what",
    "when", "where", "which", "while", "with", "will", "would", "government", "president",
    # Countries, regions and broad institutions should not create a candidate alone.
    "afryka", "ameryka", "azja", "brytania", "chiny", "chin", "china", "europa",
    "europejski", "europejska", "iran", "izrael", "izraelski", "niemcy", "niemiecki",
    "nato", "polska", "polski", "polskie", "rosja", "rosyjski", "ukraina", "ukrainski",
    "usa", "unii", "unia", "unijne", "swiat", "świat", "swiata", "świata",
    "wielka", "wegry", "węgry", "wegierski", "węgierski",
})
MERGE_WORD_RE = re.compile(r"[^\W\d_][\w'-]{2,}", re.UNICODE)


def _merge_token_base(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", folded.casefold())


MERGE_NON_DISTINCTIVE_BASES = frozenset(
    _merge_token_base(token) for token in MERGE_NON_DISTINCTIVE_TOKENS
)
# These endings cover the most common inflection differences without using a
# blind five-character prefix.  The old prefix made unrelated words such as
# "energia" and "energetyczny" look identical.
MERGE_TOKEN_SUFFIXES = (
    "owego", "owej", "owych", "owym", "owie", "ami", "ach", "ania",
    "enie", "enia", "eniu", "owej", "owy", "owa", "owe", "owi",
    "em", "om", "ie", "ia", "iu", "ą", "ę", "a", "e", "i", "y", "u", "o",
)


def _merge_token_forms(value: str) -> set[str]:
    base = _merge_token_base(value)
    if len(base) < 4 or base in MERGE_NON_DISTINCTIVE_BASES:
        return set()
    forms = {base}
    # Catch simple Polish inflections of names/objects, e.g. Trump/Trumpa,
    # without collapsing every word that happens to share its first letters.
    for suffix in MERGE_TOKEN_SUFFIXES:
        if base.endswith(suffix) and len(base) - len(suffix) >= 5:
            stem = base[:-len(suffix)]
            if stem in MERGE_NON_DISTINCTIVE_BASES:
                return set()
            forms.add(stem)
            break
    return forms


def _topic_merge_features(topic: dict[str, Any]) -> dict[str, set[str]]:
    """Return exact/stemmed tokens and two-token anchors for a topic.

    A single shared token is deliberately not enough to make two topics local
    merge candidates.  The two-token anchors are built after removing generic
    words, so a phrase such as ``sankcje Iran`` is stronger evidence than an
    isolated word such as ``Trump``.
    """
    fields = [
        str(topic.get("headline_pl") or ""),
        str(topic.get("what_happened_one_sentence_pl") or ""),
        str(topic.get("summary_pl") or ""),
        *(str(title) for title in (topic.get("recent_article_titles") or [])),
    ]
    exact_tokens: set[str] = set()
    stemmed_tokens: set[str] = set()
    phrases: set[str] = set()
    for field in fields:
        content_sequence: list[str] = []
        for match in MERGE_WORD_RE.finditer(field):
            raw = match.group(0)
            forms = _merge_token_forms(raw)
            if not forms:
                continue
            exact = _merge_token_base(raw)
            stem = min(forms, key=lambda value: (len(value), value))
            exact_tokens.add(exact)
            stemmed_tokens.add(stem)
            content_sequence.append(stem)
        phrases.update(
            f"{left} {right}"
            for left, right in zip(content_sequence, content_sequence[1:])
            if left != right
        )
    return {
        "exact": exact_tokens,
        "stems": stemmed_tokens,
        "phrases": phrases,
    }


def _topic_merge_candidate_edges(
    topics: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str], float], dict[str, set[str]]]:
    """Find local pairs with three lexical anchors or a shared two-word phrase.

    This is a high-precision blocking step before the AI request.  It is not
    trying to decide whether topics are the same story; it only decides which
    pairs are worth showing to the model.  In particular, one shared person,
    country, company or other word can never create an edge by itself.
    """
    features = {
        str(topic["topic_id"]): _topic_merge_features(topic)
        for topic in topics
    }
    token_postings: dict[str, list[str]] = defaultdict(list)
    phrase_postings: dict[str, list[str]] = defaultdict(list)
    for topic_id, topic_features in features.items():
        for token in topic_features["stems"]:
            token_postings[token].append(topic_id)
        for phrase in topic_features["phrases"]:
            phrase_postings[phrase].append(topic_id)

    topic_count = len(topics)
    max_common_token_frequency = max(8, min(30, topic_count // 5 or 1))
    max_common_phrase_frequency = max(5, min(20, topic_count // 10 or 1))
    shared_tokens: dict[tuple[str, str], set[str]] = defaultdict(set)
    for token, topic_ids in token_postings.items():
        unique_ids = sorted(set(topic_ids))
        if len(unique_ids) > max_common_token_frequency:
            continue
        for left, right in combinations(unique_ids, 2):
            shared_tokens[(left, right)].add(token)

    shared_phrases: dict[tuple[str, str], set[str]] = defaultdict(set)
    for phrase, topic_ids in phrase_postings.items():
        unique_ids = sorted(set(topic_ids))
        if len(unique_ids) > max_common_phrase_frequency:
            continue
        for left, right in combinations(unique_ids, 2):
            shared_phrases[(left, right)].add(phrase)

    edges: dict[tuple[str, str], float] = {}
    neighbors: dict[str, set[str]] = defaultdict(set)
    for pair in set(shared_tokens) | set(shared_phrases):
        overlap = shared_tokens.get(pair, set())
        phrase_overlap = shared_phrases.get(pair, set())
        # A shared phrase is a concrete anchor. Scattered words are weaker:
        # require three distinct stems rather than two to avoid broad matches.
        if len(overlap) < 3 and not phrase_overlap:
            continue
        exact_overlap = (
            features[pair[0]]["exact"] & features[pair[1]]["exact"]
        )
        score = (
            float(len(overlap))
            + 2.0 * len(phrase_overlap)
            + 0.25 * len(exact_overlap)
        )
        edges[pair] = score
        left, right = pair
        neighbors[left].add(right)
        neighbors[right].add(left)
    return edges, neighbors


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def build_embedding_candidate_edges(
    topic_ids: list[str],
    embeddings: list[list[float]],
    *,
    top_k: int = TOPIC_MERGE_EMBEDDING_TOP_K,
    min_similarity: float = TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY,
) -> dict[tuple[str, str], float]:
    """Return nearest semantic neighbors that deserve AI verification.

    Embeddings only create *candidate* edges.  The merge prompt remains the
    final authority and must still identify the same concrete story before a
    database merge is applied.
    """
    if len(topic_ids) != len(embeddings) or len(topic_ids) < 2:
        return {}
    edges: dict[tuple[str, str], float] = {}
    for index, vector in enumerate(embeddings):
        scored: list[tuple[float, int]] = []
        for other_index, other_vector in enumerate(embeddings):
            if index == other_index:
                continue
            similarity = _cosine_similarity(vector, other_vector)
            if similarity >= min_similarity:
                scored.append((similarity, other_index))
        for similarity, other_index in heapq.nlargest(top_k, scored):
            pair = tuple(sorted((str(topic_ids[index]), str(topic_ids[other_index]))))
            edges[pair] = max(edges.get(pair, 0.0), similarity)
    return edges


def _topic_embedding_text(topic: dict[str, Any]) -> str:
    summary = str(topic.get("summary_pl") or "").strip()
    recent_titles = [
        str(title).strip()
        for title in (topic.get("recent_article_titles") or [])[:3]
        if str(title or "").strip()
    ]
    parts = [
        f"Tytuł wątku: {str(topic.get('headline_pl') or '').strip()}",
        f"Opis: {str(topic.get('what_happened_one_sentence_pl') or '').strip()}",
    ]
    if summary:
        parts.append(f"Synteza wątku: {summary[:1200]}")
    if recent_titles:
        parts.append("Ostatnie nagłówki: " + " | ".join(recent_titles))
    return "\n".join(parts)[:1800]


def build_topic_embedding_candidate_edges(
    topics: list[dict[str, Any]],
) -> dict[tuple[str, str], float]:
    """Embed compact topic descriptions and return semantic candidate edges.

    The whole operation is intentionally best-effort.  A temporary embedding
    outage must leave the older lexical blocking algorithm available rather
    than stopping ingestion or the merge pass.
    """
    if not TOPIC_MERGE_EMBEDDINGS_ENABLED or len(topics) < 2:
        return {}
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        return {}

    from openai import OpenAI

    topic_ids = [str(topic.get("topic_id") or "") for topic in topics]
    texts = [_topic_embedding_text(topic) for topic in topics]
    client = OpenAI(
        api_key=openai_api_key(),
        timeout=TOPIC_MERGE_EMBEDDING_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
    embeddings: list[list[float]] = []
    batch_count = (len(texts) + TOPIC_MERGE_EMBEDDING_BATCH_SIZE - 1) // TOPIC_MERGE_EMBEDDING_BATCH_SIZE
    log(
        "AI",
        f"Semantyczna selekcja: tworzę embeddingi dla {len(texts)} tematów "
        f"w {batch_count} paczkach (model {TOPIC_MERGE_EMBEDDING_MODEL}); "
        "paczki dotyczą tylko API, potem porównuję wszystkie pary lokalnie.",
    )
    for offset in range(0, len(texts), TOPIC_MERGE_EMBEDDING_BATCH_SIZE):
        batch = texts[offset:offset + TOPIC_MERGE_EMBEDDING_BATCH_SIZE]
        last_error: Exception | None = None
        for attempt in range(TOPIC_MERGE_EMBEDDING_MAX_RETRIES):
            try:
                response = client.embeddings.create(
                    input=batch,
                    model=TOPIC_MERGE_EMBEDDING_MODEL,
                    dimensions=TOPIC_MERGE_EMBEDDING_DIMENSIONS,
                )
                data = sorted(
                    list(getattr(response, "data", []) or []),
                    key=lambda item: int(getattr(item, "index", 0)),
                )
                if len(data) != len(batch):
                    raise RuntimeError(
                        f"Embedding API zwróciło {len(data)} wektorów zamiast {len(batch)}."
                    )
                embeddings.extend([
                    [float(value) for value in item.embedding]
                    for item in data
                ])
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if not is_retryable_openai_error(exc) or attempt + 1 >= TOPIC_MERGE_EMBEDDING_MAX_RETRIES:
                    raise
                wait_before_openai_retry(
                    attempt,
                    exc,
                    retry_limit=TOPIC_MERGE_EMBEDDING_MAX_RETRIES,
                )
        if last_error is not None:
            raise last_error

    edges = build_embedding_candidate_edges(topic_ids, embeddings)
    log(
        "AI",
        f"Semantyczna selekcja zakończona: {len(edges)} par ponad progiem "
        f"{TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY:.2f}; "
        f"AI zweryfikuje je razem z lokalnymi kandydatami.",
    )
    return edges


def build_topic_merge_candidate_groups(
    topics: list[dict[str, Any]],
    *,
    max_topics_per_group: int = TOPIC_MERGE_MAX_TOPICS_PER_REQUEST,
    semantic_edges: dict[tuple[str, str], float] | None = None,
    preserve_candidate_edges: bool = False,
) -> list[list[str]]:
    """Build bounded candidate groups before asking the model to merge them.

    Lexical and semantic edges are useful for finding possible relationships,
    but connected components can become enormous through weak transitive
    bridges (A resembles B, B resembles C, and so on). Split every component
    into bounded, graph-local chunks before it reaches the model.
    """
    if len(topics) < 2:
        return []
    edges, _neighbors = _topic_merge_candidate_edges(topics)
    topic_ids_set = {str(topic["topic_id"]) for topic in topics}
    for raw_pair, score in (semantic_edges or {}).items():
        if len(raw_pair) != 2:
            continue
        left, right = (str(raw_pair[0]), str(raw_pair[1]))
        if left == right or left not in topic_ids_set or right not in topic_ids_set:
            continue
        pair = tuple(sorted((left, right)))
        edges[pair] = max(edges.get(pair, 0.0), 3.0 + float(score))
        _neighbors.setdefault(left, set()).add(right)
        _neighbors.setdefault(right, set()).add(left)
    if not edges:
        return []

    if preserve_candidate_edges:
        # A component can be larger than one AI request.  Build an overlapping
        # edge cover instead of cutting it into disjoint chunks, so every pair
        # that passed the local filter remains together in at least one request.
        remaining_edges = set(edges)
        edge_groups: list[list[str]] = []
        while remaining_edges:
            seed = max(
                remaining_edges,
                key=lambda pair: (edges[pair], pair),
            )
            group: set[str] = set(seed)
            while len(group) < max_topics_per_group:
                candidate_scores: dict[str, float] = defaultdict(float)
                candidate_degrees: dict[str, int] = defaultdict(int)
                for left, right in remaining_edges:
                    if left in group and right not in group:
                        candidate_scores[right] += edges[(left, right)]
                        candidate_degrees[right] += 1
                    elif right in group and left not in group:
                        candidate_scores[left] += edges[(left, right)]
                        candidate_degrees[left] += 1
                if not candidate_scores:
                    break
                candidate = max(
                    candidate_scores,
                    key=lambda topic_id: (
                        candidate_scores[topic_id],
                        candidate_degrees[topic_id],
                        topic_id,
                    ),
                )
                group.add(candidate)
            covered_edges = {
                pair for pair in remaining_edges if set(pair).issubset(group)
            }
            edge_groups.append(sorted(group))
            remaining_edges.difference_update(covered_edges)
        return edge_groups

    topic_ids = [str(topic["topic_id"]) for topic in topics]
    parent = {topic_id: topic_id for topic_id in topic_ids}

    def find(topic_id: str) -> str:
        while parent[topic_id] != topic_id:
            parent[topic_id] = parent[parent[topic_id]]
            topic_id = parent[topic_id]
        return topic_id

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left, right in edges:
        union(left, right)

    components: dict[str, list[str]] = defaultdict(list)
    for topic_id in topic_ids:
        components[find(topic_id)].append(topic_id)

    groups: list[list[str]] = []
    for component in components.values():
        if len(component) < 2:
            continue
        remaining = set(component)
        orphan_ids: list[str] = []
        while remaining:
            # Start each chunk near the densest remaining node, then walk its
            # local neighbors. This preserves more of the graph structure
            # than slicing the component alphabetically.
            start = max(
                remaining,
                key=lambda topic_id: (len(_neighbors.get(topic_id, set()) & remaining), topic_id),
            )
            queue = [start]
            chunk: list[str] = []
            queued: set[str] = {start}
            while queue and len(chunk) < max_topics_per_group:
                topic_id = queue.pop(0)
                if topic_id not in remaining:
                    continue
                remaining.remove(topic_id)
                chunk.append(topic_id)
                neighbors = sorted(
                    _neighbors.get(topic_id, set()) & remaining,
                    key=lambda candidate: (
                        -len(_neighbors.get(candidate, set()) & remaining),
                        candidate,
                    ),
                )
                for candidate in neighbors:
                    if candidate not in queued:
                        queued.add(candidate)
                        queue.append(candidate)
            if len(chunk) >= 2:
                groups.append(sorted(chunk))
            else:
                # A hub may consume the only direct edge of many nodes in
                # the first chunk. Preserve those nodes for bounded review;
                # the AI step will reject pairs that are only transitively
                # related and would otherwise never be examined.
                orphan_ids.extend(chunk)
        orphan_chunks = [
            orphan_ids[offset:offset + max_topics_per_group]
            for offset in range(0, len(orphan_ids), max_topics_per_group)
        ]
        if len(orphan_chunks) >= 2 and len(orphan_chunks[-1]) == 1:
            orphan_chunks[-1].insert(0, orphan_chunks[-2].pop())
        for chunk in orphan_chunks:
            if len(chunk) >= 2:
                groups.append(sorted(chunk))
    return groups


def merge_overlapping_candidate_groups(
    groups: list[list[str]],
) -> list[list[str]]:
    """Collapse any directly or transitively overlapping groups into unions."""
    merged: list[set[str]] = []
    group_by_topic: dict[str, int] = {}
    for raw_group in groups:
        group = {str(topic_id) for topic_id in raw_group if str(topic_id)}
        if len(group) < 2:
            continue
        matching_indexes = {
            group_by_topic[topic_id]
            for topic_id in group
            if topic_id in group_by_topic
        }
        if not matching_indexes:
            merged.append(group)
            group_index = len(merged) - 1
        else:
            group_index = min(matching_indexes)
            for matching_index in sorted(matching_indexes, reverse=True):
                if matching_index == group_index:
                    continue
                group.update(merged[matching_index])
                merged[matching_index] = set()
            group.update(merged[group_index])
            merged[group_index] = group
        for topic_id in group:
            group_by_topic[topic_id] = group_index
    return [sorted(group) for group in merged if group]


def compact_topic_merge_record(
    topic: dict[str, Any],
    *,
    candidate_group_id: str = "",
) -> dict[str, Any]:
    """Keep only the evidence needed by AI after local candidate filtering."""
    record = {
        "topic_id": str(topic.get("topic_id") or ""),
        "headline_pl": str(topic.get("headline_pl") or "")[:TOPIC_MERGE_TITLE_CHAR_LIMIT],
        "categories": normalize_topic_categories(topic.get("categories") or topic.get("category")),
        "what_happened_one_sentence_pl": str(
            topic.get("what_happened_one_sentence_pl") or ""
        )[:TOPIC_MERGE_DESCRIPTION_CHAR_LIMIT],
        "recent_article_titles": [
            str(title)[:TOPIC_MERGE_TITLE_CHAR_LIMIT]
            for title in (topic.get("recent_article_titles") or [])[:TOPIC_MERGE_MAX_RECENT_TITLES]
            if str(title or "").strip()
        ],
    }
    summary = str(topic.get("summary_pl") or "").strip()
    if summary:
        record["summary_pl"] = summary[:TOPIC_MERGE_SUMMARY_CHAR_LIMIT]
    if candidate_group_id:
        record["candidate_group_id"] = candidate_group_id
    return record


def build_topic_merge_requests(
    topics: list[dict[str, Any]],
    *,
    max_topics_per_request: int = TOPIC_MERGE_MAX_TOPICS_PER_REQUEST,
    candidate_groups: list[list[str]] | None = None,
    preserve_candidate_group_overlap: bool = False,
) -> list[list[dict[str, Any]]]:
    """Pack disjoint candidate groups together, preserving each group's scope.

    Overlapping edge-cover groups go into separate requests so each record
    keeps one candidate_group_id. Disjoint groups can share a request without
    introducing cross-group comparisons.
    """
    topic_by_id = {str(topic["topic_id"]): topic for topic in topics}
    raw_groups = candidate_groups
    if raw_groups is None:
        raw_groups = build_topic_merge_candidate_groups(
            topics,
            max_topics_per_group=max_topics_per_request,
            preserve_candidate_edges=preserve_candidate_group_overlap,
        )
    groups = (
        raw_groups
        if preserve_candidate_group_overlap
        else merge_overlapping_candidate_groups(raw_groups)
    )
    requests: list[list[dict[str, Any]]] = []
    current_records: dict[str, dict[str, Any]] = {}
    for group_index, group in enumerate(groups, start=1):
        group_ids = list(dict.fromkeys(group))
        # Keep this defensive split even though the graph builder already
        # applies the same bound. It also protects callers that provide their
        # own overlapping/oversized candidate groups.
        chunks = [
            group_ids[offset:offset + max_topics_per_request]
            for offset in range(0, len(group_ids), max_topics_per_request)
        ]
        for chunk_index, chunk in enumerate(chunks, start=1):
            if not chunk:
                continue
            if preserve_candidate_group_overlap and current_records:
                # A topic may occur in several edge-cover groups.  Flush a
                # request before adding an overlapping group so every record
                # keeps the correct candidate_group_id and the model compares
                # all members of that edge-cover group.
                if set(chunk).intersection(current_records):
                    requests.append(list(current_records.values()))
                    current_records = {}
            if len(chunk) >= max_topics_per_request:
                if current_records:
                    requests.append(list(current_records.values()))
                    current_records = {}
                candidate_group_id = f"local_{group_index}_{chunk_index}"
                requests.append([
                    compact_topic_merge_record(
                        topic_by_id[topic_id],
                        candidate_group_id=candidate_group_id,
                    )
                    for topic_id in chunk
                ])
                continue
            merged_ids = list(dict.fromkeys([*current_records, *chunk]))
            if current_records and len(merged_ids) > max_topics_per_request:
                requests.append(list(current_records.values()))
                current_records = {}
            candidate_group_id = f"local_{group_index}_{chunk_index}"
            for topic_id in chunk:
                current_records.setdefault(
                    topic_id,
                    compact_topic_merge_record(
                        topic_by_id[topic_id],
                        candidate_group_id=candidate_group_id,
                    ),
                )
    if current_records:
        requests.append(list(current_records.values()))
    return requests


def fallback_topic_title(
    current_title: Any,
    one_sentence: Any,
    article_titles: list[str],
) -> str:
    """Build a non-placeholder title from evidence already attached to a topic."""
    for candidate in [current_title, one_sentence, *article_titles]:
        formatted = format_topic_title_candidate(candidate, current_title)
        if is_usable_topic_title(formatted):
            return formatted
    raise RuntimeError(
        "Nie można nadać tematowi konkretnego tytułu: brak tytułu artykułu "
        "i brak jednozdaniowego opisu do użycia jako fallback."
    )

TOPIC_LABELING_INSTRUCTIONS = """
Jesteś modułem nadawania roboczych nazw wątków wiadomości w aplikacji Global
News Intelligence. Otrzymujesz artykuły i dla KAŻDEGO artykułu utwórz jeden
osobny kandydat wątku. W tym kroku nie grupuj artykułów, nie porównuj ich ze
sobą i nie dopasowuj ich do innych tematów — scalanie odbędzie się dopiero w
następnym etapie.

Nazwę twórz zawsze łącznie na podstawie `title_original` oraz
`body_excerpt_original`, czyli początku artykułu. Początek tekstu ma pomóc
rozpoznać sedno materiału, zwłaszcza gdy nagłówek jest clickbaitem, pytaniem
albo ogólną zapowiedzią. Nie wybieraj nazwy wyłącznie z tytułu.

`working_title_pl` musi być zawsze po polsku, niezależnie od języka źródła.
Ma być krótką, konkretną i ogólniejszą nazwą wątku redakcyjnego, a nie kopią
tytułu artykułu. Nie przepisuj `title_original` słowo w słowo ani prawie słowo
w słowo. Usuń clickbait i nazwij sedno wydarzenia, decyzji, sporu, śledztwa
albo innej sprawy tak, aby nazwa pasowała także do kolejnych materiałów.
Nie używaj placeholderów ani ogólników typu „Nowe informacje” lub „Sytuacja”.
Nazwa ma mieć zwykle 8–14 słów i maksymalnie 180 znaków. Nie dodawaj
uzasadnienia, opisu ani żadnego tekstu poza nazwą.

Każda nazwa musi zaczynać się od jednego prefiksu geograficznego w nawiasach
kwadratowych. Dla jednego głównego kraju użyj jego polskiej nazwy, dla kilku
państw europejskich `[Europa]`, a dla spraw międzynarodowych, globalnych lub
bez jednego głównego kraju `[Świat]`. Nigdy nie wypisuj kilku państw w jednym
prefiksie.

Zwróć dokładnie jeden wpis w `labels` dla każdego `article_id` z wejścia,
bez dodawania obcych identyfikatorów.

Zwróć WYŁĄCZNIE poprawny JSON:
{"labels":[{"article_id":"...","working_title_pl":"[Kraj] Ogólna
nazwa konkretnej sprawy"}]}
""".strip()

GROUPING_INSTRUCTIONS = """
Jesteś modułem grupowania wiadomości w aplikacji Global News Intelligence.
Pracujesz wyłącznie na przekazanych artykułach. Twoim celem jest pogrupować
artykuły możliwie kompletnie według wspólnej osi konkretnej historii. Jeśli
kilka artykułów opisuje tę samą historię, połącz je już tutaj — nie czekaj na
etap późniejszego scalania. Preferuj wysoką czułość grupowania, ale nie łącz
materiałów bez konkretnego wspólnego wydarzenia lub sprawy.

Wspólna oś wystarcza, nawet gdy artykuły mają różne tytuły, pochodzą z różnych
źródeł albo jeden opisuje wydarzenie, drugi reakcję, a trzeci skutki. Liczby,
szczegóły, miejsce, czas i perspektywa mogą się różnić. Sama wspólna osoba,
państwo, partia, firma lub słowo tematyczne nie wystarcza. Tytuł artykułu jest
ważnym sygnałem razem z wyciągiem treści — nie odrzucaj zgodnej pary tylko
dlatego, że pierwsze słowa tekstu nie powtarzają nazwy wydarzenia.

Najpierw odrzuć materiały wyraźnie niezwiązane z głównym zakresem aplikacji:
sport, pogodę i prognozy pogody, celebrytów, rozrywkę, lifestyle, przepisy,
zwykłe treści konsumenckie i inne materiały bez znaczenia dla polityki,
gospodarki, bezpieczeństwa, dyplomacji, konfliktów, prawa publicznego lub
istotnych wydarzeń społecznych.

Materiały, których głównym tematem jest sport, wynik lub przebieg zawodów,
transfer zawodnika, zwykła prognoza pogody, temperatura, spodziewane opady bez
istotnych skutków, celebryta albo życie prywatne osoby publicznej, zawsze
umieść w excluded_articles — nie twórz dla nich grupy, tematu ani syntezy.
Sama duża popularność materiału nie czyni go istotnym dla aplikacji.

Nie wykluczaj natomiast klęsk żywiołowych i ekstremalnych zjawisk pogodowych,
jeżeli spowodowały albo bezpośrednio powodują powódź, ofiary, ewakuacje,
rozległe zniszczenia, poważne awarie infrastruktury, istotne skutki gospodarcze
lub nadzwyczajne działania władz. Taki materiał jest newsem o skutkach i
bezpieczeństwie, a nie zwykłą prognozą pogody. Artykuł o decyzji publicznej,
gospodarce albo bezpieczeństwie może też pozostać, gdy sport, pogoda lub
celebryta są jedynie tłem, a nie główną osią tekstu.
Jeżeli związek jest niepewny, nie odrzucaj materiału — zostaw go w grupie lub
unassigned_article_ids i ustaw needs_review.

Treść artykułu w tym etapie jest tylko krótkim wyciągiem pierwszych około 100
słów, więc nie dopowiadaj faktów, których nie ma w tytule ani wyciągu.

Zwróć WYŁĄCZNIE poprawny JSON:
{"groups":[{"group_id":"new_group_001","existing_topic_id":"",
"topic_action":"NEW_TOPIC|DEVELOPMENT|BACKGROUND_OR_CONTEXT",
"working_title_pl":"[Kraj] Konkretny tytuł wydarzenia","article_ids":["..."],
"categories":["POLITYKA"],
"confidence":0.0,"needs_review":false,"grouping_reason":"...",
"topic_anchor_pl":"jednozdaniowa oś wspólnej historii",
"article_relevance":[{"article_id":"...","why_same_event":"..."}]}],
"unassigned_article_ids":[],"excluded_articles":[{"article_id":"...",
"category":"SPORT|WEATHER|CELEBRITY|ENTERTAINMENT|LIFESTYLE|OTHER_NON_CORE",
"reason":"krótkie uzasadnienie"}]}

Każdy article_id z wejścia ma wystąpić dokładnie raz: w jednej grupie,
unassigned_article_ids albo excluded_articles. Najpierw sprawdź active_topics
z ostatnich 55 godzin. Każdy wpis active_topics zawiera wyłącznie tytuł
istniejącego tematu, jednozdaniowy opis oraz tytuły artykułów już przypisanych
do tego tematu. Używaj tych tytułów i opisu do dopasowania nowego artykułu;
nie zakładaj, że active_topics zawiera pełne teksty artykułów.
Każda grupa ma oznaczać jeden konkretny wątek redakcyjny: jedno wydarzenie,
bezpośredni ciąg aktualizacji albo jedną trwającą sprawę, negocjację, decyzję
lub politykę. Artykuły mogą dodawać różne, uzupełniające informacje — nie muszą
powtarzać tych samych faktów. Zadaj pytanie: „czy wszystkie materiały opisują
to, co dzieje się w tej samej sprawie?”. Jeśli tak, połącz je pod jednym
tematem. Jeśli wspólna oś jest wiarygodna, ale któryś artykuł ma słabszy
związek, nadal dołącz go i ustaw needs_review=true.

Przed zwróceniem wyniku wykonaj test: tytuł i topic_anchor_pl muszą trafnie
opisywać każdy artykuł z article_ids. Jeżeli dla któregokolwiek artykułu trzeba
dopisać „a ponadto zupełnie inna sprawa”, rozbij grupę. Wspólny kraj, polityk,
organizacja, branża, wojna albo wzmianka o USA, Rosji, Chinach, NATO czy UE nie
oznacza jeszcze tego samego wątku. Przykład błędny: wypowiedź Trumpa oraz wzrost
cen zbóż w Szkocji. Przykład poprawny: różne wypowiedzi i decyzje dotyczące tej
samej rundy negocjacji, różne aktualizacje tego samego śledztwa albo różne
relacje o pierwszym orbitalnym locie Starshipa.

Łącz artykuły opisujące tę samą historię nawet wtedy, gdy jeden przedstawia
decyzję, drugi reakcję, a trzeci skutki. Użyj grupy jednoartykułowej dopiero
wtedy, gdy po porównaniu tytułu i wyciągu naprawdę nie da się wskazać
konkretnej wspólnej osi wydarzeń — nie twórz singletona tylko dlatego, że
artykuł ma inny kąt albo nie powtarza wszystkich słów z pozostałych tytułów.

Dla każdego article_id w grupie dodaj dokładnie jeden wpis article_relevance.
why_same_event ma wskazywać konkretny wspólny fakt, decyzję, wypowiedź, ciąg
aktualizacji albo sprawę, a nie tylko wspólne słowo, osobę albo państwo. Jeśli
nie potrafisz wskazać takiej osi, artykuł musi znaleźć się w osobnej grupie albo
w unassigned_article_ids. confidence oceniaj dla najsłabiej pasującego artykułu,
nie dla większości grupy. Dla identycznego wydarzenia użyj zwykle 0.90+, ale
dla tej samej trwającej historii z różnymi aspektami 0.70–0.89 jest prawidłowe.
Nie rozbijaj grupy tylko dlatego, że confidence nie wynosi 0.90.
Jeżeli artykuł jest dalszym ciągiem istniejącego tematu, wpisz jego topic_id i
topic_action=DEVELOPMENT. Jeżeli tylko uzupełnia kontekst lub wcześniejszą
agregację, wpisz topic_action=BACKGROUND_OR_CONTEXT. Nowe wydarzenie ma
topic_action=NEW_TOPIC i pusty existing_topic_id.

Nie twórz nowego tematu tylko dlatego, że artykuł pojawił się w kolejnym
uruchomieniu tego samego dnia. Jeśli dopasowanie do istniejącego tematu jest
niepewne, zostaw existing_topic_id puste i ustaw needs_review. Profil źródła
służy wyłącznie do opisu perspektywy, nie do łączenia artykułów.
working_title_pl ma być krótkim, konkretnym i informacyjnym tytułem po polsku,
napisanym w jednolitym stylu dobrej gazety: ma jasno mówić, czego dotyczy
wydarzenie, decyzja lub spór, i — gdy to pomaga — wskazywać głównego aktora
oraz miejsce. Tytuł ma być ciekawy i zachęcający do lektury, ale nie może być
clickbaitem, sensacyjną obietnicą, pytaniem retorycznym ani ogólnikiem typu
„Azja”, „Nowe informacje” lub „Sytuacja jest napięta”. Nie używaj krzykliwych
zapisów wielkimi literami ani ocen sugerujących, kto ma rację. Stosuj zwykłą
polską kapitalizację tytułową i nie dodawaj informacji, których nie ma w
artykułach. Tytuł powinien być zwięzły — zwykle około 8–16 słów.

Przy tworzeniu working_title_pl korzystaj łącznie z `title_original` oraz
`body_excerpt_original`. Początek artykułu ma pomóc ustalić, czego naprawdę
dotyczy materiał, zwłaszcza gdy nagłówek jest pytaniem, clickbaitem albo używa
ogólnych słów. Nie wybieraj nazwy wyłącznie na podstawie brzmienia nagłówka.

Najważniejsza zasada: working_title_pl jest nazwą wątku redakcyjnego, a nie
tytułem żadnego artykułu. Ma abstrahować od formy nagłówka i nazywać sedno
wydarzenia tak, aby pasował także do kolejnych materiałów o tej samej sprawie.
Nigdy nie przepisuj title_original słowo w słowo ani prawie słowo w słowo —
dotyczy to także grup jednoartykułowych. Usuń clickbait, ciekawość i emocjonalne
obietnice („Nie uwierzycie…”, „szokujące słowa”, „to zmieni wszystko”), a z
treści artykułu wyciągnij konkretny podmiot, czynność i przedmiot sprawy.
Zamień określenia niejasne lub chwilowe („co powiedział”, „ten polityk”,
„dzisiaj”) na nazwę wydarzenia i osobę, a datę dodaj tylko wtedy, gdy pomaga
odróżnić wydarzenie od innych. Nazwa ma być szersza od pojedynczego nagłówka,
ale nadal konkretna — nie zastępuj jej nazwą państwa ani ogólną kategorią.

Przykład: dla artykułu zatytułowanego „Nie uwierzycie, co Trump powiedział w
swoim dzisiejszym wystąpieniu” nie zwracaj tego samego tekstu. Jeśli treść nie
podaje węższego tematu, zwróć np. „[USA] Dzisiejsze wystąpienie Trumpa” albo
„[USA] Wystąpienie Trumpa z datą artykułu” (wstaw właściwą datę); jeśli treść
wskazuje konkretny temat wypowiedzi, nazwij właśnie ten temat. Dla dwóch artykułów wybierz jedną
wspólną nazwę sedna wydarzenia, a nie jeden z ich nagłówków.
Każdy working_title_pl musi zaczynać się od jednego prefiksu geograficznego
w nawiasach kwadratowych. Prefiks nie jest listą wszystkich państw
wspomnianych w artykule, tylko wskazuje główny obszar wydarzenia:

- jeśli historia dotyczy przede wszystkim jednego kraju, użyj wyłącznie tego
  kraju, np. `[USA]`, nawet jeśli drugi kraj jest tylko wspomniany, jest
  stroną wypowiedzi albo pojawia się w tle;
- jeśli historia dotyczy co najmniej dwóch państw europejskich, użyj
  `[Europa]`;
- jeśli dotyczy co najmniej dwóch państw, a przynajmniej jedno z nich leży
  poza Europą, użyj `[Świat]`;
- dla spraw globalnych, międzynarodowych lub bez jednego głównego kraju użyj
  `[Świat]`.

Nigdy nie łącz nazw państw w prefiksie — nie używaj form typu `[USA i Iran]`,
`[USA, Iran]` ani `[Wielka Brytania i USA]`. Używaj polskich nazw państw.
Używaj `[Wielka Brytania]`, chyba że wydarzenie dotyczy konkretnie tylko
Anglii. Nie wpisuj w prefiksie miasta ani ogólnika typu `[Zagranica]`.
grouping_reason ma być krótkie i nie przekraczać około 160 znaków.
Nigdy nie wpisuj tekstu przykładowego „neutralna nazwa wydarzenia”, „Temat bez
tytułu” ani żadnego innego placeholdera. Każda grupa musi mieć konkretny tytuł
wynikający z przekazanych artykułów.

categories wybierz jako jedną lub maksymalnie trzy wartości z listy: POLSKA,
POLITYKA, SWIAT, GOSPODARKA, SPOLECZENSTWO, TECHNOLOGIA, ZDROWIE albo
KULTURA_SPORT. POLSKA oznacza, że głównym miejscem, aktorem lub przedmiotem
wydarzenia jest Polska, polskie instytucje, polskie społeczeństwo albo polskie
regiony. Może występować razem z kategorią tematyczną, np. POLSKA i POLITYKA.
To kategorie redakcyjne, a nie ocena źródeł ani prefiks geograficzny tytułu.
SWIAT oznacza przede wszystkim międzynarodowe relacje, geopolitykę lub
wydarzenia globalne; nie przypisuj do niej automatycznie każdej historii spoza
Polski. Dodaj więcej niż jedną kategorię tylko wtedy, gdy każda z nich wnosi
istotny wymiar tematu, a nie jako luźne skojarzenie.
""".strip()

TOPIC_MERGE_INSTRUCTIONS = """
Jesteś modułem porządkowania tematów w aplikacji Global News Intelligence.
Otrzymujesz grupy kandydatów wyłonione wcześniej lokalnie na podstawie
wielu sygnałów: wspólnych charakterystycznych słów lub fraz, podobieństwa
znaczeniowego opisów i tytułów oraz wspólnych aktorów lub obiektów. Są to
wyłącznie kandydatury do weryfikacji, a nie decyzje o scaleniu. Twoim celem jest
potwierdzić, które z tych tematów opisują tę samą konkretną historię, nawet
jeśli wcześniejsze grupowanie rozdzieliło je na różne tematy. Porównuj tylko
tematy przekazane w bieżącym żądaniu; brak tematu w żądaniu nie oznacza, że
jest on niepowiązany. Jeśli rekordy mają `candidate_group_id`, porównuj i
scalaj tematy tylko w obrębie tego samego identyfikatora. Jest to ograniczona
grupa lokalnych kandydatów; rekordy z innych identyfikatorów nie należą do
tego porównania.
W tym kroku preferuj wysoką czułość: lepiej połączyć dwa bardzo podobne
relacje o tej samej historii niż zostawić je jako duplikaty.

SCALAJ, gdy tematy mają wspólny rozpoznawalny punkt zaczepienia, na przykład:
- ten sam konkretny incydent, lot, misję, operację, wypadek albo mecz;
- tę samą decyzję, umowę, głosowanie, wypowiedź lub ogłoszenie;
- tę samą sprawę, śledztwo, protest, negocjacje albo rozwój wcześniej opisanej
  historii;
- ten sam charakterystyczny obiekt i zdarzenie, nawet jeśli artykuły skupiają
  się na innych szczegółach, skutkach lub wypowiedziach;
- ten sam ongoing story, gdy nowszy artykuł dodaje szczegóły do wydarzenia,
  a nie opisuje tylko ogólnej tematyki.

Różne źródła, różne kąty relacji, różne liczby, szczegóły miejsca/czasu oraz
tytuły skupione na różnych uczestnikach NIE są powodem, by zostawić tematy
osobno, jeśli całość wskazuje na tę samą historię. Przykład: artykuły o
pierwszym orbitalnym locie Starshipa, locie z bazy w Teksasie i osiągnięciu
orbity przez Starship należy połączyć, nawet gdy każdy tytuł akcentuje inny
szczegół.

NIE SCALAJ tylko dlatego, że tematy dotyczą tego samego państwa, osoby,
partii, firmy, wojny, wyborów albo ogólnego problemu. Sama wspólna osoba lub
organizacja nie wystarcza: Trump może występować w wielu niezależnych
wydarzeniach, a wzrost zbóż w Szkocji nie jest tą samą historią co wypowiedź
Trumpa. Nie łącz też dwóch różnych incydentów z tą samą osobą ani dwóch
różnych etapów tylko dlatego, że mają podobne słowa. Jeżeli nie ma żadnego
konkretnego wspólnego wydarzenia, zostaw tematy osobno.

Porównuj przede wszystkim charakterystyczne nazwy, obiekty, zdarzenia i
relacje w `recent_article_titles`, `headline_pl` i `what_happened_one_sentence_pl`.
Jeżeli rekord zawiera `summary_pl`, jest to wcześniejsza synteza całego wątku:
wykorzystaj ją jako dodatkowe źródło kontekstu, zwłaszcza gdy paczka dotyczy
istniejących już syntez. Krótkie podsumowanie lub wcześniejsza synteza może być
nieaktualna albo obejmować szerszy kontekst; nie pozwól, aby samo rozbieżne
sformułowanie zablokowało połączenie, gdy tytuły i faktyczny punkt zaczepienia
są zgodne. Dodatkowy kontekst w jednym wątku nie oznacza automatycznie innej
historii — połącz wątki, jeśli ich głównym wydarzeniem jest ta sama decyzja,
informacja lub ciąg dalszy tej samej sprawy.

merged_title_pl zachowuje te same zasady co working_title_pl: ma być konkretnym,
informacyjnym i ciekawym tytułem w jednolitym stylu prasowym, bez clickbaitu,
krzykliwych ocen i ogólników.
Nie przepisuj żadnego `recent_article_titles` słowo w słowo ani prawie słowo w
słowo. Nazwa ma opisywać wspólne wydarzenie lub sprawę, a nie jeden konkretny
artykuł; powinna pozostać trafna także wtedy, gdy do tematu dojdą kolejne
materiały z innym nagłówkiem.
Musi także zaczynać się od jednego prefiksu geograficznego. Dla jednego
głównego kraju użyj jego nazwy, dla co najmniej dwóch państw europejskich
`[Europa]`, a dla wielu państw, w tym co najmniej jednego spoza Europy,
`[Świat]`. Nigdy nie wypisuj kilku państw w jednym prefiksie.

Zwróć WYŁĄCZNIE poprawny JSON:
{"merge_groups":[{"topic_ids":["topic_a","topic_b"],
"merged_title_pl":"[Kraj] Konkretny wspólny tytuł wydarzenia","confidence":0.0,
"categories":["POLITYKA"],
"reason":"krótkie wyjaśnienie, dlaczego to to samo wydarzenie"}]}

W każdej grupie muszą być co najmniej dwa różne topic_id. Nie umieszczaj
jednego tematu w dwóch grupach. confidence ma oznaczać pewność, że chodzi o
ten sam konkretny incydent lub ciąg dalszy tej samej historii. Używaj wartości
co najmniej 0.84 dla mocnych, ale niekoniecznie identycznych relacji; wartości
poniżej 0.84 zostaw osobno. Nie twórz grup z tematów, które są już oznaczone
 jako scalone. categories wybierz z dokładnie tej samej listy ośmiu kategorii
co w module grupowania. Zwróć jedną lub maksymalnie trzy kategorie, ale dodaj
więcej niż jedną wyłącznie wtedy, gdy każda opisuje istotny wymiar wspólnej
historii. POLSKA może oznaczać krajowy wymiar historii i może występować razem
z kategorią tematyczną.
Nie opisuj tematów, których nie łączysz. Jeśli w tej paczce nie ma pewnego
połączenia, zwróć dokładnie `{"merge_groups":[]}`.
""".strip()

TITLE_NORMALIZATION_INSTRUCTIONS = """
Ujednolić tytuły tematów wiadomości. Nie zmieniaj znaczenia ani nie dodawaj
faktów. Każdy title_pl musi zaczynać się od jednego prefiksu geograficznego.
Jeśli sprawa dotyczy jednego głównego kraju, wpisz tylko ten kraj, np.
`[USA]`. Jeśli dotyczy co najmniej dwóch państw europejskich, wpisz
`[Europa]`. Jeśli dotyczy wielu państw i choć jedno leży poza Europą, wpisz
`[Świat]`. Dla spraw globalnych lub bez jednego głównego kraju również użyj
`[Świat]`. Nigdy nie wpisuj kilku państw w prefiksie, np. `[USA i Iran]` albo
`[USA, Iran]`. Używaj `[Wielka Brytania]`, chyba że sprawa dotyczy wyłącznie
Anglii.
Po prefiksie zachowaj konkretny, prasowy tytuł bez clickbaitu. Nazwa ma być
krótką, ogólniejszą nazwą wątku redakcyjnego, a nie kopią nagłówka artykułu.
Korzystaj z `one_sentence_pl`, `summary_pl` i `article_openings`, aby nazwać
sedno wydarzenia lub sprawy. `article_titles` są tylko materiałem pomocniczym
do rozpoznania kontekstu.
Nigdy nie przepisuj żadnego `article_titles` słowo w słowo ani prawie słowo w
słowo — dotyczy to również tematów mających tylko jeden artykuł. Usuń
clickbait, pytania retoryczne, emocjonalne obietnice i szczegóły będące tylko
formą pojedynczego nagłówka. Nazwa powinna pasować także do kolejnych artykułów
o tej samej sprawie.
Nie używaj placeholderów typu „neutralna nazwa wydarzenia”, „neutralny wspólny
tytuł” ani „Temat bez tytułu”.

Zwróć WYŁĄCZNIE JSON:
{"titles":[{"topic_id":"","title_pl":"[Kraj] Konkretny tytuł"}]}
Każdy wejściowy topic_id musi wystąpić dokładnie raz.
""".strip()

CATEGORY_INSTRUCTIONS = """
Jesteś redaktorem porządkującym katalog tematów wiadomości. Przypisz każdy
temat do jednej, dwóch albo maksymalnie trzech kategorii na podstawie tytułu,
jednozdaniowego opisu
i tytułów ostatnich artykułów. Nie kieruj się profilem politycznym źródeł ani
samym krajem opisanym w tytule przy wyborze kategorii tematycznych; kategorię
POLSKA przypisz, gdy Polska jest głównym miejscem, aktorem lub przedmiotem
wydarzenia.

W tej paczce znajdują się wyłącznie tematy wieloźródłowe, dla których aplikacja
może przygotować syntezę. Nie twórz kategorii dla tematów jednoźródłowych ani
nie zwracaj topic_id, którego nie ma w wejściu. Zwróć dokładnie jeden wpis dla
każdego topic_id z wejścia, także wtedy, gdy nie ma dodatkowych kategorii.

Dozwolone kategorie:
- POLSKA — wydarzenia dotyczące Polski, polskich instytucji, polskiego
  społeczeństwa, prawa, regionów lub firm; może współistnieć z kategorią
  tematyczną;
- POLITYKA — decyzje władz, wybory, partie, parlament, administracja i spory
  polityczne;
- SWIAT — relacje międzynarodowe, geopolityka, konflikty między państwami i
  wydarzenia globalne;
- GOSPODARKA — firmy, rynki, handel, finanse, praca, ceny i budżety;
- SPOLECZENSTWO — prawo życia codziennego, edukacja, migracja, demografia,
  protesty i ważne wydarzenia społeczne;
- TECHNOLOGIA — nauka stosowana, internet, AI, cyberbezpieczeństwo i nowe
  technologie;
- ZDROWIE — medycyna, zdrowie publiczne, epidemie i system ochrony zdrowia;
- KULTURA_SPORT — kultura, media, rozrywka i sport.

Wybierz kategorie głównego tematu, nie przypadkowych pobocznych szczegółów. Jeśli temat
dotyczy zagranicy, ale jego sednem jest gospodarka, wybierz GOSPODARKA; SWIAT
nie oznacza automatycznie „wszystkiego poza Polską”.

Zwróć WYŁĄCZNIE poprawny JSON:
{"categories":[{"topic_id":"...","categories":["POLITYKA"]}]}
Każdy topic_id z wejścia musi wystąpić dokładnie raz.
Nie dodawaj komentarza, markdownu, tekstu przed JSON-em ani tekstu po JSON-ie.
""".strip()

CATEGORY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic_id": {"type": "string"},
                    "categories": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(TOPIC_CATEGORY_VALUES),
                        },
                    },
                },
                "required": ["topic_id", "categories"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["categories"],
    "additionalProperties": False,
}

SUMMARY_INSTRUCTIONS = """
Jesteś redaktorem analitycznym aplikacji Global News Intelligence. Przygotuj
neutralne polskie opracowanie jednego tematu wyłącznie na podstawie
dostarczonych artykułów. Każde istotne twierdzenie musi mieć article_ids.
Identyfikatory są techniczne: aplikacja ma prezentować czytelnikowi
odpowiadające im nazwy źródeł, a nie surowe numery lub identyfikatory.
Pokaż osobno fakty zgodne, informacje jednostkowe, różnice i sprzeczności.
Nie rozstrzygaj, które źródło ma rację. Profil lewicowe/prawicowe/centralne
służy wyłącznie do pokazania sposobu przedstawienia tematu.

Wszystkie teksty przeznaczone dla czytelnika muszą być napisane po polsku —
w szczególności `summary_pl`, `facts[].text_pl`, `agreement[].text_pl`,
`differences[].text_pl`, `contradictions[].text_pl`, opisy kontekstu,
`sources[].description_pl` oraz tekst aktualizacji. W `facts[].text_pl` zawsze
przetłumacz albo sparafrazuj treść faktu po polsku; nie kopiuj angielskiego
tytułu, zdania ani opisu tylko dlatego, że artykuł źródłowy jest po angielsku.
Możesz pozostawić oryginalną nazwę własną, skrót lub krótki cytat, ale reszta
zdania musi być naturalną polszczyzną i wyjaśniać sens faktu. Polskie pola nie
mogą zawierać angielskich zdań ani technicznych komentarzy.

Nie nazywaj artykułu kłamliwym. Możesz wskazać konkretny sygnał wymagający
sprawdzenia: wartościujący język, brak kontekstu, nagłówek mocniejszy niż
treść, niezweryfikowane twierdzenie albo konflikt z innym materiałem. Nie
wymyślaj cytatów ani informacji spoza artykułów. Kontekst ogólny wpisz tylko
do background_context i oznacz needs_verification=true.

summary_pl ma być właściwą, rzeczową syntezą faktów, a nie opisem tego, o czym
piszą artykuły. Nie zaczynaj od sformułowań typu „artykuły opisują”, „źródła
przedstawiają” ani „materiały dotyczą”. Zacznij od tego, co się wydarzyło.
Podział na akapity jest obowiązkowy: nie zwracaj głównej syntezy jako jednego
zwartego bloku tekstu. Podziel ją na krótkie akapity, z których każdy rozwija
jeden etap wydarzenia albo jedną grupę faktów. Każdy akapit oddziel pustą linią
— w JSON zapisz separator jako `\\n\\n`, aby po odczytaniu powstała rzeczywista
pusta linia. Nie zastępuj pustej linii pojedynczym `\\n` ani spacją. Przy 2–3
artykułach użyj co najmniej 3 akapitów, a przy większej liczbie materiałów co
najmniej 5 akapitów, o ile treść dostarcza wystarczająco dużo faktów. Ta sama
zasada dotyczy `update.new_information_pl` i `update.what_changed_pl`: jeśli
tekst zawiera więcej niż jedno zdanie lub kilka etapów wydarzenia, również
podziel go na logiczne akapity oddzielone `\\n\\n`.
Pogrubienia `**...**` są opcjonalne. Jeśli ich używasz, obejmuj nimi tylko
pojedyncze najważniejsze nazwiska, instytucje, liczby, daty lub decyzje — nigdy
całe zdania ani większość tekstu.
Używaj wyłącznie tego ograniczonego Markdownu. Nie używaj HTML, nagłówków
Markdown, list, tabel, emotikonów ani innych znaczników formatowania.
Tekst ma odpowiadać na pytanie „co dokładnie się wydarzyło”, a nie „o czym
były artykuły”. Przy co najmniej 4 artykułach napisz zwykle 5–8 akapitów i
około 550–900 słów, a przy 2–3 artykułach zwykle 3–5 akapitów i około 350–600
słów, jeżeli materiały zawierają taką ilość konkretnych informacji. To zakresy
orientacyjne: kompletność faktów jest ważniejsza niż limit. Nie dopisuj
wstępu, zakończenia ani kontekstu tylko po to, żeby wydłużyć tekst.

Buduj tekst w tej kolejności, o ile materiał na to pozwala: (1) najważniejsze
wydarzenie — kto, co, gdzie i kiedy; (2) szczegółowy przebieg i kolejność
działań; (3) decyzje, liczby, wypowiedzi i reakcje uczestników; (4) skutki,
znaczenie i aktualny stan sprawy; (5) rozbieżności oraz informacje
niepotwierdzone. Zbieraj w tekście konkretne fakty z artykułów, zamiast
referować ich istnienie. Nie dopisuj faktów tylko po to, żeby osiągnąć limit
słów.

Wykonaj przed zwróceniem JSON-u dwie osobne kontrole redakcyjne. Najpierw
sprawdź zgodność faktów, dat, liczb, nazw własnych i relacji przyczynowo-
skutkowych z artykułami. Następnie zredaguj tekst w naturalnej współczesnej
polszczyźnie. Nie tłumacz dosłownie składni angielskiej ani nagłówków. Nie
używaj kalk językowych, spolszczonych anglicyzmów, sztucznych zwrotów,
niepoprawnej odmiany nazw własnych ani zdań brzmiących jak maszynowe
tłumaczenie. Popraw interpunkcję, zgodę gramatyczną, szyk zdania, odmianę
liczb i nazwisk oraz polski zapis dat. Jeśli nie ma pewnego polskiego
odpowiednika terminu, zachowaj oryginalną nazwę i krótko ją objaśnij zamiast
tworzyć fałszywe tłumaczenie. Nie zmieniaj przy tym znaczenia ani poziomu
pewności informacji.

Nie wolno ignorować dostarczonego artykułu. Każdy artykuł należący do tematu
ma wnieść do opracowania konkretną informację albo zostać jawnie opisany jako
materiał powtarzający informacje już obecne. Tablica sources musi łącznie
zawierać wszystkie article_id z wejścia; w description_pl krótko napisz, co
dany materiał wniósł albo że nie wniósł nowego ustalenia. Jeśli artykułu nie da
się logicznie wykorzystać w tym temacie, zaznacz ten problem w
quality.limitations_pl zamiast tworzyć sztuczne połączenie faktów.

summary_pl ma być kompletnym, samodzielnym opisem wydarzenia dla czytelnika.
Muszą się w nim znaleźć wszystkie ważne fakty ze wszystkich artykułów:
przebieg wydarzeń, daty, liczby, osoby, decyzje, skutki, informacje obecne
tylko w jednym źródle oraz istotne rozbieżności. Nie przenoś żadnego ważnego
faktu wyłącznie do pola `facts`, ponieważ ta techniczna lista nie jest
prezentowana użytkowniczce.

Pole `facts` jest wyłącznie indeksem dowodowym: przypisuje atomowe twierdzenia
do article_ids i może powtarzać fakty opisane w `summary_pl`. Nie traktuj go
jako drugiego, alternatywnego podsumowania. `agreement`, `differences`,
`potential_manipulation_signals` i `background_context` mogą zawierać tylko
informacje dodatkowe, których nie trzeba przepisywać do głównej narracji;
każda z tych sekcji może pozostać pusta. Nie powtarzaj tej samej informacji
w kilku zdaniach głównej syntezy.

differences ma wskazywać konkretną różnicę, a nie ogólnik typu „źródła różnie
przedstawiają temat”. W każdym wpisie nazwij wymiar różnicy, na przykład
liczbę, kolejność wydarzeń, zakres skutków, przypisywaną odpowiedzialność albo
ocenę znaczenia. Jeśli różnica nie ma znaczenia dla zrozumienia sprawy, pomiń
ją.

potential_manipulation_signals może zawierać tylko obserwowalny sygnał, który
czytelnik może sam sprawdzić. Zamiast oceny „artykuł manipuluje” napisz np.
„Nagłówek sugeruje X, ale treść potwierdza jedynie Y — warto sprawdzić, czy
wniosek z nagłówka wynika z materiału”. Jeśli nie ma konkretnego sygnału,
pozostaw tablicę pustą.

Pisz dla polskiego czytelnika, który może nie znać specjalistycznego
kontekstu, ale nie twórz osobnego słowniczka ani sekcji `reader_context`.
Objaśnienia mają pojawić się bezpośrednio w `summary_pl`, przy pierwszym
użyciu danego terminu — najlepiej w krótkim nawiasie. Przykłady:
`DMDC (Defense Manpower Data Center, amerykański system danych o personelu
wojskowym)` albo `Defense Builder (ukraiński akcelerator technologii
obronnych)`. Przy osobie dodaj funkcję lub rolę tylko wtedy, gdy wynika z
materiałów i pomaga zrozumieć fakt.

Wyjaśniaj tylko terminy, skróty, organizacje, stanowiska i osoby, które mogą
nie być oczywiste dla polskiego czytelnika. Nie objaśniaj oczywistych nazw
państw, takich jak Polska, Ukraina, Rosja czy USA, ani zwykłych miast wyłącznie
dlatego, że występują w tekście. Nie twórz listy haseł, osobnych definicji ani
encyklopedycznych biogramów. Nie dopowiadaj biografii, funkcji ani znaczenia
skrótów, którego nie da się wiarygodnie ustalić. Jeśli wyjaśnienie nie wynika
z artykułów, pomiń je albo zaznacz niepewność w odpowiednim fakcie — nie
przenoś go do słowniczka.

Nie twórz osobnej osi wydarzeń ani listy powtarzających się dat. Jeżeli data
jest konieczna do zrozumienia sprawy, umieść ją w summary_pl, facts albo
differences przy odpowiednim fakcie. W przeciwnym razie pomiń ją.

Jeżeli previous_aggregation nie jest null, zawiera `base_summary` oraz
`prior_updates`. Potraktuj oba elementy jako opublikowaną wcześniej, NIEZMIENNĄ
historię. Nie przepisuj jej, nie skracaj i nie aktualizuj
summary_pl, facts, agreement, differences, potential_manipulation_signals ani
background_context — program
zachowa te pola z poprzedniej wersji. W takim przypadku wygeneruj wyłącznie
delta-update w polu update, opisujący bieżące new_articles.

Jeżeli nowe artykuły dodają istotne fakty, opisz je konkretnie i wyczerpująco
w update.new_information_pl. Nie skracaj aktualizacji na siłę do kilku zdań
ani do z góry ustalonej liczby akapitów. Uwzględnij wszystkie istotne nowe
ustalenia, liczby, decyzje, wypowiedzi, reakcje, skutki i rozbieżności, których
nie było w previous_aggregation. Długość ma wynikać z ilości nowych informacji:
przy jednym drobnym fakcie wystarczy krótki akapit, ale przy kilku obszernych
artykułach aktualizacja może mieć kilka rozwiniętych akapitów i około 300–700
słów, jeżeli materiał uzasadnia taką długość. Aktualizacja ma przekazywać treść
nowych materiałów, a nie tylko informować, że pojawiły się nowe doniesienia.
Zaczynaj od faktów, nie od zdania „najnowszy artykuł dotyczy…”. Zamiast
opisywać, o czym jest materiał, napisz co konkretnie ustalono: liczby, osoby,
daty, wyniki badań, decyzje, działania, cytowane stanowiska i ich znaczenie.
Jeżeli nowy materiał dotyczy pobocznego, ale zaakceptowanego aspektu wątku,
przedstaw go jako nowy aspekt tej historii, np. „W osobnym aspekcie sprawy…”.
Nie oceniaj w tekście, czy materiał został dobrze czy źle przypisany do wątku.
Nie pisz, że artykuł jest „nie na temat”, „nic nie wnosi”, „nie zmienia
narracji”, jest „logicznym błędem grupowania” ani że trzeba go odrzucić.
Nie opisuj procesu grupowania ani decyzji systemu — czytelnik ma dostać fakty.
ZASADA BRAKU POWTÓRZEŃ W AKTUALIZACJACH:
Przed napisaniem update porównaj każdy fakt z całą opublikowaną historią:
base_summary (w tym summary_pl i wszystkie pola faktograficzne) oraz KAŻDĄ
wcześniejszą aktualizacją w prior_updates, nie tylko z ostatnią. Porównuj
znaczenie informacji, a nie brzmienie zdań. Parafraza, inna kolejność zdań,
tłumaczenie, nowy artykuł lub inne źródło opisujące ten sam fakt NIE czynią
go nową informacją. Nie powielaj faktów z syntezy w pierwszej aktualizacji
ani z syntezy lub dowolnej wcześniejszej aktualizacji w kolejnych.

W update.new_information_pl umieść wyłącznie przyrost wiedzy: nowe fakty,
nowe istotne szczegóły, decyzje, skutki albo rzeczywistą zmianę lub korektę
wcześniejszych ustaleń. Dla zmiany lub korekty wskaż krótko, co się zmieniło;
przywołaj poprzednie ustalenie tylko w zakresie koniecznym do zrozumienia
różnicy. Nie odtwarzaj wcześniejszego opisu wydarzenia jako wprowadzenia.

Jeżeli nowe materiały wyłącznie potwierdzają wcześniejsze ustalenia, wystarczy
jedno krótkie zdanie, np. „Kolejne artykuły potwierdzają wcześniejsze ustalenia
o terminie rozpoczęcia protestu”. Nazwij krótko potwierdzony aspekt, ale nie
wyliczaj ponownie znanych liczb, dat, cytatów i pozostałych szczegółów.
Nie dopisuj nowych szczegółów, jeśli artykuły ich nie dostarczają. Jeśli tylko
część materiałów wnosi nowe fakty, opisz te fakty bez streszczania pozostałych
artykułów; zbiorcze potwierdzenie wcześniejszych ustaleń jest opcjonalne.
Nie rozciągaj aktualizacji powtórzeniami, aby osiągnąć sugerowaną długość.
update.what_changed_pl ma krótko nazwać zmianę lub samo potwierdzenie,
bez kopiowania opisu z update.new_information_pl.
new_article_ids musi zawierać wyłącznie artykuły z bieżącego zestawu.
Jeżeli previous_aggregation jest null, utwórz pełną syntezę bazową i ustaw
update.is_update=false.

Jeżeli wejście zawiera previous_aggregation, nie twórz drugiej pełnej wersji
tekstu i nie zastępuj wcześniejszej syntezy nową. Zachowaj ją jako bazę na
zawsze, a nowe informacje pokaż tylko w update. Nie twórz drugiego tematu dla
dalszego ciągu tej samej historii. Dla nowych tematów previous_aggregation
będzie null.
Pole new_articles zawiera materiały z bieżącego uruchomienia. Pole
all_articles jest obecne przy pierwszym opracowaniu tematu; przy aktualizacji
starsze materiały są reprezentowane przez previous_aggregation i ich article_id.

DODATKOWE ZASADY WYKONANIA:

Priorytet zasad jest następujący:
1. poprawny JSON i dokładna struktura pól;
2. zgodność z dostarczonymi artykułami;
3. brak wymyślania informacji;
4. kompletność ustaleń;
5. styl, długość i płynność języka.

article_ids muszą być kopiowane dokładnie z wejścia. Nie wolno tworzyć,
modyfikować ani zgadywać identyfikatorów. Nie wpisuj nazw źródeł do
article_ids.
Identyfikatory artykułów są wyłącznie technicznym śladem dowodowym. Nie wolno
wstawiać ich do summary_pl, update.new_information_pl,
update.what_changed_pl ani do żadnego innego tekstu przeznaczonego dla
czytelnika. Jeśli trzeba rozróżnić materiały, użyj `source_name` z wejścia,
np. „PAP podaje…”, ale zaraz potem przedstaw konkretne fakty, a nie opis
samego artykułu.

Każdy element tablic facts, agreement, differences, potential_manipulation_signals
i contradictions powinien zawierać
jedno główne, możliwie atomowe twierdzenie. Jeżeli zdanie zawiera kilka
niezależnych faktów, podziel je na kilka elementów.

Pola tekstowe, które nie mają własnego article_ids, w szczególności
summary_pl, topic.what_happened_one_sentence_pl, update.new_information_pl
i update.what_changed_pl, mogą zawierać wyłącznie informacje mające
bezpośrednie potwierdzenie w artykułach. Każde istotne twierdzenie z tych pól
musi mieć dokładne odzwierciedlenie w co najmniej jednym elemencie tablic
zawierającym właściwe article_ids.

Nie dodawaj do agreement informacji tylko dlatego, że jest oczywistym faktem
opisanym w summary_pl. Agreement zawiera wyłącznie dodatkowe ustalenia,
które co najmniej dwa artykuły przedstawiają zgodnie.

differences oznacza rozbieżności, które mogą współistnieć, na przykład różne
liczby, kolejność działań, zakres skutków, interpretacje lub poziom
szczegółowości.

contradictions oznacza wyłącznie twierdzenia wzajemnie wykluczające się,
dotyczące tego samego faktu. Nie rozstrzygaj sprzeczności i nie przenoś do
contradictions zwykłych różnic akcentów. Jeśli nie ma rzeczywistego konfliktu,
zostaw contradictions jako pustą tablicę. Nigdy nie wpisuj tam zdania typu
„nie ma sprzeczności”, „brak sprzecznych twierdzeń” ani wyjaśnienia, że różnice
nie są sprzecznością — takie rozbieżności należą do differences.

Nie generuj pola `framing_and_tone` ani osobnej analizy tonu lub sposobu
przedstawienia materiałów.

potential_manipulation_signals nie jest oceną, że artykuł manipuluje.
Wpisz wyłącznie obserwowalny sygnał oraz krótko wyjaśnij, dlaczego wymaga
dodatkowego sprawdzenia.

W trybie aktualizacji, gdy previous_aggregation nie jest null, zwróć pełną
strukturę JSON, ale skopiuj 1:1 wszystkie wcześniejsze pola poza update.
Nie parafrazuj, nie skracaj, nie poprawiaj stylistycznie i nie aktualizuj
wcześniejszej syntezy. Nowe ustalenia mogą pojawić się wyłącznie w update.

W trybie aktualizacji:
- update.is_update musi mieć wartość true;
- update.new_article_ids może zawierać wyłącznie article_id z bieżącego
  new_articles;
- każdy nowy article_id musi znaleźć się w update.new_article_ids i sources;
  jeśli artykuł tylko potwierdza znany fakt, opisz ten wkład w sources,
  bez wymuszania ponownego opisania faktu w update.new_information_pl;
- nie pisz metakomentarza o tym, czy materiał pasuje do grupy;
- nie dodawaj do update faktów obecnych już w previous_aggregation lub
  prior_updates.

Każdy artykuł z wejścia musi pojawić się w sources. Jeżeli nie wnosi nowej
informacji, nie opisuj tego jako wady grupowania ani nie pokazuj takiej oceny
czytelnikowi. W `sources.description_pl` napisz krótko, jaki fakt lub aspekt
artykuł potwierdza, rozwija albo dokumentuje. Nie wpisuj tam technicznych
identyfikatorów.

topic.categories musi zawierać jedną, dwie albo maksymalnie trzy kategorie z
listy POLSKA, POLITYKA, SWIAT, GOSPODARKA, SPOLECZENSTWO, TECHNOLOGIA, ZDROWIE,
KULTURA_SPORT. Zwracaj pełny aktualny zestaw kategorii także w trybie
aktualizacji. Nie dodawaj kategorii tematycznych tylko na podstawie kraju lub
profilu źródła; każda kategoria musi wynikać z głównego tematu albo jego
istotnego wymiaru. POLSKA może wskazywać geograficzny wymiar krajowy i może
łączyć się z kategorią tematyczną. Jeśli wątek łączy np. politykę i zdrowie
publiczne, zwróć obie.

Przed zwróceniem odpowiedzi sprawdź wewnętrznie, czy:
- wynik zawiera wyłącznie dozwolone pola;
- nie ma komentarza, markdownu ani tekstu poza JSON-em;
- JSON jest poprawnie parsowalny;
- wszystkie article_id z wejścia występują w sources;
- article_count oznacza liczbę unikalnych artykułów;
- source_count oznacza liczbę unikalnych źródeł;
- puste sekcje są reprezentowane przez [] lub "";
- żadne twierdzenie nie zostało dodane wyłącznie dla zwiększenia długości.

Zwróć WYŁĄCZNIE poprawny JSON o następującej strukturze:
{"topic":{"headline_pl":"","what_happened_one_sentence_pl":"",
"categories":["POLITYKA"],
"status":"ONGOING","time_scope":""},
"update":{"is_update":false,"new_information_pl":"",
"what_changed_pl":"","new_article_ids":[]},"summary_pl":"",
"facts":[{"text_pl":"","article_ids":[]}],
"agreement":[{"text_pl":"","article_ids":[]}],
"differences":[{"text_pl":"","article_ids":[]}],
"potential_manipulation_signals":[{"text_pl":"","article_ids":[]}],
"contradictions":[{"text_pl":"","article_ids":[]}],
"background_context":[{"text_pl":"","article_ids":[],"needs_verification":true}],
"sources":[{"source_name":"","description_pl":"","article_ids":[]}],
"quality":{"article_count":0,"source_count":0,
"has_multiple_perspectives":false,"overall_confidence":"MEDIUM",
"limitations_pl":""}}

topic.headline_pl musi zaczynać się od identycznego, pojedynczego prefiksu
geograficznego jak tytuł roboczy. Jeśli temat dotyczy jednego głównego kraju,
użyj tylko jego nazwy, np. `[USA]`. Dla co najmniej dwóch państw europejskich
użyj `[Europa]`, a dla wielu państw, w tym co najmniej jednego spoza Europy,
użyj `[Świat]`. Dla spraw globalnych lub bez jednego głównego kraju również
użyj `[Świat]`. Nigdy nie wpisuj kilku państw w prefiksie, np. `[USA i Iran]`
albo `[USA, Iran]`.

W elementach tablic używaj dokładnie nazw pól pokazanych powyżej. Nie używaj
zamienników typu agreement_pl, point_pl, difference_pl, tone, signal, reason,
context, notes ani event. Nie dodawaj innych pól. article_ids to techniczna
lista identyfikatorów dowodowych i nie należy wstawiać jej do tekstu
text_pl. Jeśli element nie ma oparcia w konkretnym artykule, zostaw
article_ids jako [] i ustaw needs_verification=true tam, gdzie to pole istnieje.
""".strip()

SUMMARY_UPDATE_REPAIR_INSTRUCTIONS = SUMMARY_INSTRUCTIONS + """

TRYB NAPRAWY AKTUALIZACJI: poprzednia odpowiedź nie spełniła wymogu
faktograficznej aktualizacji. Wygeneruj ponownie pełny JSON z tym samym
wejściem. W `update.new_information_pl` nie opisuj artykułu, procesu
grupowania ani tego, czy materiał pasuje do tematu. Nie używaj zdań o tym, że
artykuł jest „nie na temat”, „nic nie wnosi”, „nie zmienia narracji” albo nie
zawiera informacji o głównym wątku. Zamiast tego wybierz z każdego nowego
materiału konkretne, sprawdzalne NOWE fakty: osoby, liczby, daty, wyniki,
działania, stanowiska i skutki, których nie ma w base_summary ani w żadnej
wcześniejszej aktualizacji prior_updates. Jeśli materiał tylko potwierdza
znane ustalenia, zastosuj krótkie zbiorcze potwierdzenie zgodnie z zasadą
braku powtórzeń; nie wymuszaj nowego faktu ani nie przepisuj znanych faktów.
Zaczynaj od faktu, np. „Dwa badania wykazały…”, a nazwę
źródła dodaj tylko wtedy, gdy pomaga rozróżnić relacje. Nie umieszczaj
technicznych article_id w żadnym tekście.
""".strip()


def _json_schema_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_JSON_STRING_ARRAY_SCHEMA = {"type": "array", "items": {"type": "string"}}
_JSON_CATEGORY_ARRAY_SCHEMA = {
    "type": "array",
    "items": {
        "type": "string",
        "enum": list(TOPIC_CATEGORY_VALUES),
    },
}

TOPIC_LABEL_RESPONSE_SCHEMA = _json_schema_object({
    "labels": {
        "type": "array",
        "items": _json_schema_object({
            "article_id": {"type": "string"},
            "working_title_pl": {"type": "string"},
        }),
    },
})

GROUPING_RESPONSE_SCHEMA = _json_schema_object({
    "groups": {
        "type": "array",
        "items": _json_schema_object({
            "group_id": {"type": "string"},
            "existing_topic_id": {"type": "string"},
            "topic_action": {
                "type": "string",
                "enum": ["NEW_TOPIC", "DEVELOPMENT", "BACKGROUND_OR_CONTEXT"],
            },
            "working_title_pl": {"type": "string"},
            "article_ids": _JSON_STRING_ARRAY_SCHEMA,
            "categories": _JSON_CATEGORY_ARRAY_SCHEMA,
            "confidence": {"type": "number"},
            "needs_review": {"type": "boolean"},
            "grouping_reason": {"type": "string"},
            "topic_anchor_pl": {"type": "string"},
            "article_relevance": {
                "type": "array",
                "items": _json_schema_object({
                    "article_id": {"type": "string"},
                    "why_same_event": {"type": "string"},
                }),
            },
        }),
    },
    "unassigned_article_ids": _JSON_STRING_ARRAY_SCHEMA,
    "excluded_articles": {
        "type": "array",
        "items": _json_schema_object({
            "article_id": {"type": "string"},
            "category": {
                "type": "string",
                "enum": ["SPORT", "WEATHER", "CELEBRITY", "ENTERTAINMENT", "LIFESTYLE", "OTHER_NON_CORE"],
            },
            "reason": {"type": "string"},
        }),
    },
})

TOPIC_MERGE_RESPONSE_SCHEMA = _json_schema_object({
    "merge_groups": {
        "type": "array",
        "items": _json_schema_object({
            "topic_ids": _JSON_STRING_ARRAY_SCHEMA,
            "merged_title_pl": {"type": "string"},
            "confidence": {"type": "number"},
            "categories": _JSON_CATEGORY_ARRAY_SCHEMA,
            "reason": {"type": "string"},
        }),
    },
})

TITLE_RESPONSE_SCHEMA = _json_schema_object({
    "titles": {
        "type": "array",
        "items": _json_schema_object({
            "topic_id": {"type": "string"},
            "title_pl": {"type": "string"},
        }),
    },
})

_SUMMARY_EVIDENCE_ITEM_SCHEMA = _json_schema_object({
    "text_pl": {"type": "string"},
    "article_ids": _JSON_STRING_ARRAY_SCHEMA,
})
_SUMMARY_BACKGROUND_ITEM_SCHEMA = _json_schema_object({
    "text_pl": {"type": "string"},
    "article_ids": _JSON_STRING_ARRAY_SCHEMA,
    "needs_verification": {"type": "boolean"},
})
_SUMMARY_SOURCE_ITEM_SCHEMA = _json_schema_object({
    "source_name": {"type": "string"},
    "description_pl": {"type": "string"},
    "article_ids": _JSON_STRING_ARRAY_SCHEMA,
})

SUMMARY_RESPONSE_SCHEMA = _json_schema_object({
    "topic": _json_schema_object({
        "headline_pl": {"type": "string"},
        "what_happened_one_sentence_pl": {"type": "string"},
        "categories": _JSON_CATEGORY_ARRAY_SCHEMA,
        "status": {"type": "string"},
        "time_scope": {"type": "string"},
    }),
    "update": _json_schema_object({
        "is_update": {"type": "boolean"},
        "new_information_pl": {"type": "string"},
        "what_changed_pl": {"type": "string"},
        "new_article_ids": _JSON_STRING_ARRAY_SCHEMA,
    }),
    "summary_pl": {"type": "string"},
    "facts": {"type": "array", "items": _SUMMARY_EVIDENCE_ITEM_SCHEMA},
    "agreement": {"type": "array", "items": _SUMMARY_EVIDENCE_ITEM_SCHEMA},
    "differences": {"type": "array", "items": _SUMMARY_EVIDENCE_ITEM_SCHEMA},
    "potential_manipulation_signals": {
        "type": "array", "items": _SUMMARY_EVIDENCE_ITEM_SCHEMA,
    },
    "contradictions": {"type": "array", "items": _SUMMARY_EVIDENCE_ITEM_SCHEMA},
    "background_context": {
        "type": "array", "items": _SUMMARY_BACKGROUND_ITEM_SCHEMA,
    },
    "sources": {"type": "array", "items": _SUMMARY_SOURCE_ITEM_SCHEMA},
    "quality": _json_schema_object({
        "article_count": {"type": "integer"},
        "source_count": {"type": "integer"},
        "has_multiple_perspectives": {"type": "boolean"},
        "overall_confidence": {"type": "string"},
        "limitations_pl": {"type": "string"},
    }),
})

UPDATE_META_PATTERNS = (
    re.compile(r"\bnajnowsz(?:y|a|e) artykuł\b", re.IGNORECASE),
    re.compile(r"\bartykuł[^.]{0,80}\bdotycz(?:y|ą)\b", re.IGNORECASE),
    re.compile(r"\bnie (?:jest|są) na temat\b", re.IGNORECASE),
    re.compile(r"\bnie wnosi(?:ą)?\b", re.IGNORECASE),
    re.compile(r"\bnie zmienia(?:ją)? narracji\b", re.IGNORECASE),
    re.compile(r"\bnie zawiera(?:ją)? informacji\b", re.IGNORECASE),
    re.compile(r"\bbłęd(?:ne|nie) (?:przypisanie|grupowanie)\b", re.IGNORECASE),
)


def update_text_value(summary: dict[str, Any]) -> str:
    update = summary.get("update") if isinstance(summary.get("update"), dict) else {}
    return normalize_generated_text(
        update.get("new_information_pl") or update.get("what_changed_pl") or ""
    ).strip()


def update_needs_repair(summary: dict[str, Any]) -> bool:
    text = update_text_value(summary)
    return not text or any(pattern.search(text) for pattern in UPDATE_META_PATTERNS)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_generated_text(value: Any) -> str:
    """Keep model text as plain text, including when it emits HTML breaks."""
    text = str(value or "")
    # Some model/storage paths preserve JSON-escaped line breaks literally.
    # Convert both escaped and real variants before the UI receives the text.
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return AI_BREAK_TAG_RE.sub("\n", text).strip()


class AIResponseParseError(ValueError):
    def __init__(self, message: str, raw_output: str):
        super().__init__(message)
        self.raw_output = raw_output


class ParsedAIResponse(dict[str, Any]):
    def __init__(self, value: dict[str, Any], raw_output: str):
        super().__init__(value)
        self.raw_output = raw_output


def extract_json(text: str) -> dict[str, Any]:
    raw_output = text or ""
    cleaned = raw_output.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        decoder = json.JSONDecoder()
        last_error: json.JSONDecodeError = exc
        for match in re.finditer(r"\{", cleaned):
            try:
                candidate, _ = decoder.raw_decode(cleaned, match.start())
            except json.JSONDecodeError as candidate_error:
                last_error = candidate_error
                continue
            if isinstance(candidate, dict):
                return candidate
        raise AIResponseParseError(
            f"AI nie zwróciło poprawnego JSON: {last_error}", raw_output
        ) from last_error
    if not isinstance(value, dict):
        raise AIResponseParseError("AI zwróciło JSON inny niż obiekt.", raw_output)
    return value


SUMMARY_ARRAY_FIELDS = (
    "facts",
    "agreement",
    "differences",
    "potential_manipulation_signals",
    "contradictions",
    "background_context",
    "reader_context",
    "sources",
)

SUMMARY_TEXT_ALIASES = {
    "facts": ("text_pl", "fact_pl", "fact", "claim", "description_pl", "description"),
    "agreement": ("text_pl", "agreement_pl", "agreement", "point_pl", "point", "claim"),
    "differences": ("text_pl", "differences_pl", "difference_pl", "difference", "point_pl", "point"),
    "potential_manipulation_signals": ("text_pl", "signal_pl", "signal", "reason", "description_pl", "description"),
    "contradictions": ("text_pl", "contradiction_pl", "contradiction", "difference_pl", "difference", "reason"),
    "background_context": ("text_pl", "context_pl", "context", "reason", "description_pl", "description", "notes_pl", "notes"),
}


def _as_article_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if item is not None and str(item)))


def _first_text(item: dict[str, Any], aliases: tuple[str, ...]) -> str:
    for key in aliases:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_generated_text(value)
    return ""


NON_CONTRADICTION_RE = re.compile(
    r"(?:\b(?:brak|żadne?|nie\s+ma|nie\s+występuj\w*|nie\s+wyłaniaj\w*|"
    r"nie\s+wynikaj\w*)\b.{0,120}\b(?:sprzecz|kontradyk|wyklucz)"
    r"|\b(?:sprzecz|kontradyk|wyklucz)\w*.{0,120}\b(?:brak|nie\s+ma|"
    r"nie\s+występuj\w*|nie\s+wyłaniaj\w*|nie\s+wynikaj\w*)"
    r"|\b(?:różnic|rozbieżn)\w*.{0,100}\b(?:nie\s+oznacz|nie\s+są|"
    r"nie\s+stanow)\w*.{0,60}\b(?:sprzecz|kontradyk)"
    r")",
    re.IGNORECASE,
)


def is_non_contradiction_statement(value: Any) -> bool:
    """Identify redundant text saying that the sources are not contradictory."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return bool(text and NON_CONTRADICTION_RE.search(text))


def _normalize_summary_item(field: str, item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        item = {"text_pl": item}
    if not isinstance(item, dict):
        return None
    article_ids = _as_article_ids(item.get("article_ids"))

    if field == "reader_context":
        name = normalize_generated_text(item.get("name") or item.get("term") or item.get("label"))
        explanation = _first_text(item, ("explanation_pl", "text_pl", "description_pl", "description", "context"))
        if not explanation:
            return None
        return {
            "type": str(item.get("type") or "TERM"),
            "name": name,
            "explanation_pl": explanation,
            "article_ids": article_ids,
            "needs_verification": bool(item.get("needs_verification", False)),
        }

    if field == "sources":
        source_name = normalize_generated_text(item.get("source_name") or item.get("source"))
        description = _first_text(item, ("description_pl", "text_pl", "stance_or_focus_pl", "tone_pl", "description"))
        if not source_name and not description:
            return None
        return {
            "source_name": source_name,
            "description_pl": description,
            "article_ids": article_ids,
        }

    text = _first_text(item, SUMMARY_TEXT_ALIASES[field])
    if field == "background_context" and not text:
        name = str(item.get("name") or item.get("term") or "").strip()
        explanation = _first_text(item, ("explanation_pl",))
        if name and explanation:
            text = f"{name} — {explanation}"
    if not text:
        return None
    normalized = {"text_pl": text, "article_ids": article_ids}
    if field == "background_context":
        normalized["needs_verification"] = bool(item.get("needs_verification", False))
    return normalized


def normalize_summary_response(response: dict[str, Any]) -> ParsedAIResponse:
    """Convert older/model-variant summary keys to the canonical UI schema."""
    topic = response.get("topic") if isinstance(response.get("topic"), dict) else {}
    topic = dict(topic)
    for key in ("headline_pl", "what_happened_one_sentence_pl"):
        if key in topic:
            topic[key] = normalize_generated_text(topic[key])
    topic["categories"] = normalize_topic_categories(
        topic.get("categories") or topic.get("category")
    )
    raw_update = response.get("update") if isinstance(response.get("update"), dict) else {}
    update = dict(raw_update)
    for key in ("new_information_pl", "what_changed_pl"):
        if key in update:
            update[key] = normalize_generated_text(update[key])
    normalized: dict[str, Any] = {
        "topic": topic,
        "update": update or {
            "is_update": False,
            "new_information_pl": "",
            "what_changed_pl": "",
            "new_article_ids": [],
        },
        "summary_pl": normalize_generated_text(response.get("summary_pl")),
    }
    for field in SUMMARY_ARRAY_FIELDS:
        raw_items = response.get(field, [])
        if not isinstance(raw_items, list):
            raw_items = [raw_items] if raw_items else []
        normalized[field] = [
            item for raw_item in raw_items
            if (item := _normalize_summary_item(field, raw_item)) is not None
        ]
    normalized["contradictions"] = [
        item for item in normalized["contradictions"]
        if not is_non_contradiction_statement(item.get("text_pl"))
    ]
    quality = response.get("quality")
    normalized["quality"] = quality if isinstance(quality, dict) else {
        "article_count": 0,
        "source_count": 0,
        "has_multiple_perspectives": False,
        "overall_confidence": "MEDIUM",
        "limitations_pl": "",
    }
    return ParsedAIResponse(normalized, getattr(response, "raw_output", ""))


def stored_base_summary(value: Any) -> dict[str, Any]:
    """Read both legacy direct summaries and the immutable-summary envelope."""
    if not isinstance(value, dict):
        return {}
    base = value.get("base_summary")
    if isinstance(base, dict):
        return base
    return value


def stored_latest_update(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    latest = value.get("latest_update")
    if isinstance(latest, dict):
        return latest
    update = value.get("update")
    return update if isinstance(update, dict) else {}


def stored_updates(value: Any) -> list[dict[str, Any]]:
    """Read cumulative updates and transparently support legacy envelopes."""
    if not isinstance(value, dict):
        return []
    raw_updates = value.get("updates")
    updates = [dict(item) for item in raw_updates if isinstance(item, dict)] if isinstance(raw_updates, list) else []
    if not updates:
        legacy = stored_latest_update(value)
        text = str(legacy.get("new_information_pl") or legacy.get("what_changed_pl") or "").strip()
        if text:
            updates = [dict(legacy)]
    return updates


def previous_aggregation_context(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "base_summary": stored_base_summary(value),
        "prior_updates": stored_updates(value),
    }


def empty_update() -> dict[str, Any]:
    return {
        "is_update": False,
        "new_information_pl": "",
        "what_changed_pl": "",
        "new_article_ids": [],
    }


def response_for_storage(response: dict[str, Any]) -> dict[str, Any]:
    raw_output = getattr(response, "raw_output", None)
    if raw_output is None:
        return response
    return {"parsed": dict(response), "raw_response": raw_output[:20000]}


def parse_failure_for_storage(exc: Exception) -> dict[str, Any] | None:
    if not isinstance(exc, AIResponseParseError):
        return None
    return {
        "parse_error": str(exc)[:2000],
        "raw_response": exc.raw_output[:20000],
    }


def log_parse_failure(stage: str, exc: Exception) -> None:
    if not isinstance(exc, AIResponseParseError):
        return
    log(
        "AI",
        f"Etap {stage}: odpowiedź AI była niepoprawna ({short_text(exc, 240)}). "
        "Szczegóły zapisano w historii topic_runs.",
        level="ERROR",
    )


def openai_api_key() -> str:
    """Read the key safely and explain pasted line breaks clearly."""
    value = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not value:
        raise RuntimeError("Brakuje OPENAI_API_KEY; AI nie może zostać uruchomione.")
    if "\r" in value or "\n" in value:
        raise RuntimeError(
            "OPENAI_API_KEY zawiera znak nowej linii. Zapisz w GitHub Secret sam klucz, bez Entera, cudzysłowów i spacji."
        )
    return value


def is_retryable_openai_error(exc: Exception) -> bool:
    from openai import APIConnectionError, APIError, APITimeoutError

    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if not isinstance(exc, APIError):
        return False
    return getattr(exc, "status_code", None) in {408, 409, 429, 500, 502, 503, 504}


def openai_error_details(exc: Exception) -> str:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None) or "unknown"
    request_id = getattr(exc, "request_id", None)
    suffix = f", request_id={request_id}" if request_id else ""
    return f"status={status}{suffix}: {exc}"


def wait_before_openai_retry(
    attempt: int,
    exc: Exception,
    *,
    retry_limit: int = OPENAI_MAX_RETRIES,
) -> None:
    delay = min(OPENAI_RETRY_BASE_SECONDS * (2 ** attempt), 30.0)
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    retry_after = headers.get("retry-after") if headers else None
    if retry_after:
        try:
            delay = max(delay, float(retry_after))
        except (TypeError, ValueError):
            pass
    delay += random.uniform(0, min(1.0, delay * 0.25))
    log(
        "AI",
        f"Chwilowy błąd OpenAI; ponawiam za {delay:.1f} s "
        f"(próba {attempt + 1}/{retry_limit}). Szczegóły: {short_text(openai_error_details(exc), 220)}.",
        level="WARN",
    )
    time.sleep(delay)


def call_openai(
    instructions: str,
    payload: dict[str, Any],
    model: str,
    *,
    max_output_tokens: int | None = None,
    timeout_seconds: float | None = None,
    retry_limit: int | None = None,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str = "structured_response",
) -> dict[str, Any]:
    from openai import OpenAI

    effective_retry_limit = max(1, retry_limit or OPENAI_MAX_RETRIES)
    client = OpenAI(
        api_key=openai_api_key(),
        timeout=timeout_seconds or OPENAI_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
    last_error: Exception | None = None
    parse_failures = 0
    last_parse_error = ""
    for attempt in range(effective_retry_limit):
        input_text = (
            json.dumps(payload, ensure_ascii=False)
            + "\n\nReturn only valid JSON. Do not add any commentary outside the JSON object."
        )
        if parse_failures:
            input_text += (
                "\nThe previous attempt was empty or invalid. Return the requested "
                "JSON object now, even when there are no matches."
                + (f" Validation error: {last_parse_error[:500]}" if last_parse_error else "")
            )
        try:
            request = {
                "model": model,
                "instructions": instructions,
                "input": input_text,
                "text": {
                    "format": (
                        {
                            "type": "json_schema",
                            "name": response_schema_name,
                            "strict": True,
                            "schema": response_schema,
                        }
                        if response_schema is not None
                        else {"type": "json_object"}
                    )
                },
            }
            if max_output_tokens is not None:
                request["max_output_tokens"] = max_output_tokens
            response = client.responses.create(**request)
        except Exception as exc:
            if not is_retryable_openai_error(exc):
                raise
            last_error = exc
            if attempt + 1 >= effective_retry_limit:
                raise
            wait_before_openai_retry(
                attempt,
                exc,
                retry_limit=effective_retry_limit,
            )
            continue
        try:
            if getattr(response, "status", None) == "incomplete":
                incomplete_details = getattr(response, "incomplete_details", None)
                reason = getattr(incomplete_details, "reason", None) or "unknown"
                raise AIResponseParseError(
                    f"OpenAI zwróciło niekompletną odpowiedź (reason={reason}).",
                    response.output_text,
                )
            return ParsedAIResponse(extract_json(response.output_text), response.output_text)
        except ValueError as exc:
            last_error = exc
            # A response stopped at max_output_tokens cannot become complete
            # by repeating the identical request. Let the caller split the
            # batch immediately instead of spending another full timeout on
            # the same deterministic failure.
            if (
                isinstance(exc, AIResponseParseError)
                and "reason=max_output_tokens" in str(exc)
            ):
                raise
            parse_failures += 1
            last_parse_error = str(exc)
            if parse_failures >= 2:
                raise
            log(
                "AI",
                f"Niepoprawny JSON z OpenAI; ponawiam próbę "
                f"({parse_failures}/2): {short_text(exc, 220)}.",
                level="WARN",
            )
    assert last_error is not None
    raise last_error


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


def distinct_source_keys(rows: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("source_id") or row.get("source_name") or "").strip()
        for row in rows
        if str(row.get("source_id") or row.get("source_name") or "").strip()
    }


STATE_SOURCE_PROFILES = {"STATE_ALIGNED", "STATE_MEDIA", "GOVERNMENT_AGENCY"}


def is_state_source(row: dict[str, Any]) -> bool:
    """Return whether an article comes from a state-aligned/state outlet."""
    profile = str(row.get("source_profile") or "").strip().upper()
    source_type = str(row.get("source_type") or "").strip().upper()
    return profile in STATE_SOURCE_PROFILES or source_type in STATE_SOURCE_PROFILES


def has_independent_source(rows: list[dict[str, Any]]) -> bool:
    """Require at least one source outside the state-media classification."""
    return any(not is_state_source(row) for row in rows)


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


def article_for_topic_label(
    row: dict[str, Any],
    *,
    excerpt_words_limit: int,
) -> dict[str, Any]:
    """Build the minimal payload needed to name one article candidate."""
    return {
        "article_id": row["article_id"],
        "title_original": row["title"],
        "language": row["original_language"],
        "body_excerpt_original": first_words(
            row.get("body") or "",
            excerpt_words_limit,
        ),
        "excerpt_word_limit": excerpt_words_limit,
    }


def build_bounded_summary_input(
    base_input: dict[str, Any],
    new_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], int, str]:
    """Build a summary payload without allowing article bodies to grow unbounded.

    Full article bodies are useful for small topics, but a first synthesis can
    otherwise duplicate every article in both ``new_articles`` and
    ``all_articles``. Reduce body detail only when the serialized request is
    above the configured limit, preserving article IDs and metadata throughout.
    """

    def build(excerpt_words: int | None) -> dict[str, Any]:
        def render(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if excerpt_words is None:
                return [article_for_ai(row) for row in rows]
            if excerpt_words > 0:
                return [
                    article_for_ai(row, excerpt_words_limit=excerpt_words)
                    for row in rows
                ]
            metadata_rows = []
            for row in rows:
                item = article_for_ai(row, excerpt_words_limit=1)
                item.pop("body_excerpt_original", None)
                item.pop("excerpt_word_limit", None)
                metadata_rows.append(item)
            return metadata_rows

        payload = dict(base_input)
        payload["new_articles"] = render(new_rows)
        if all_rows is not None:
            payload["all_articles"] = render(all_rows)
        return payload

    candidates: list[tuple[int | None, str]] = [(None, "pełne treści")]
    excerpt_words = SUMMARY_FALLBACK_EXCERPT_WORDS
    while excerpt_words >= 200:
        candidates.append((excerpt_words, f"wyciągi do {excerpt_words} słów"))
        excerpt_words //= 2
    candidates.append((0, "same metadane"))

    for excerpt_limit, mode in candidates:
        payload = build(excerpt_limit)
        payload_chars = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        if payload_chars <= SUMMARY_MAX_PAYLOAD_CHARS or excerpt_limit == 0:
            return payload, payload_chars, mode
    raise AssertionError("Nie udało się zbudować ograniczonego payloadu syntezy.")


def active_topic_payload(
    client: SupabaseRestClient,
    *,
    excluded_topic_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, dict[str, Any]]]:
    excluded = excluded_topic_ids or set()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=TOPIC_MATCH_LOOKBACK_HOURS)).isoformat()
    topics = client.select_all(
        "topics",
        filters=[("status", "eq.ACTIVE"), ("last_seen_at", f"gte.{cutoff}")],
    )
    topics = [row for row in topics if str(row.get("topic_id") or "") not in excluded]
    category_rows = client.select_all("topic_categories", columns="topic_id,category")
    categories_by_topic: dict[str, list[str]] = {}
    for row in category_rows:
        category = normalize_topic_category(row.get("category"))
        if category:
            categories_by_topic.setdefault(str(row["topic_id"]), []).append(category)
    summaries = client.select_all("topic_summaries", columns="topic_id,summary")
    summary_by_topic = {
        str(row["topic_id"]): stored_base_summary(row.get("summary"))
        for row in summaries
    }
    links = [
        row for row in client.select_all("topic_articles", columns="topic_id,article_id")
        if str(row.get("topic_id") or "") not in excluded
    ]
    link_map: dict[str, list[str]] = {}
    for row in links:
        link_map.setdefault(str(row["topic_id"]), []).append(str(row["article_id"]))

    article_titles = {
        str(row["article_id"]): str(row.get("title") or "").strip()
        for row in client.select_all("articles", columns="article_id,title")
    }
    titles_by_topic: dict[str, list[str]] = {}
    for topic_id, article_ids in link_map.items():
        titles_by_topic[topic_id] = [
            article_titles[article_id]
            for article_id in article_ids
            if article_titles.get(article_id)
        ]

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
            "last_seen_at": row.get("last_seen_at", ""),
            "first_seen_at": row.get("first_seen_at", ""),
            "article_count": row.get("article_count", 0),
            "categories": categories_by_topic.get(topic_id, []),
            "previous_one_sentence_pl": previous_topic.get("what_happened_one_sentence_pl", ""),
        }
        payload.append({
            "topic_id": topic_id,
            "topic_title_pl": row.get("headline_pl", ""),
            "categories": context["categories"],
            "one_sentence_description_pl": context["previous_one_sentence_pl"],
            "article_titles": titles_by_topic.get(topic_id, []),
        })
        topic_context[topic_id] = context
    return payload, link_map, topic_context


def stable_merged_topic_id(topic_ids: list[str]) -> str:
    return "topic_merge_" + digest({"topic_ids": sorted(topic_ids)})[:24]


def choose_merge_canonical_topic_id(
    topic_ids: list[str],
    topic_by_id: dict[str, Any],
    summary_by_topic: dict[str, dict[str, Any]] | None = None,
    summary_metadata_by_topic: dict[str, dict[str, Any]] | None = None,
    prefer_oldest_synthesis: bool = False,
) -> str:
    """Keep the most established topic as the identity after a merge.

    A topic with an existing synthesis wins over an unsummarized topic so the
    next summary pass can append an update to the existing aggregation. Among
    equally established topics, preserve the one seen first; article count and
    topic_id make the choice deterministic for ties.
    """
    summary_by_topic = summary_by_topic or {}
    summary_metadata_by_topic = summary_metadata_by_topic or {}

    def sort_key(topic_id: str) -> tuple[int, int, str, int, str]:
        topic = topic_by_id.get(topic_id, {})
        has_summary = 0 if topic_id in summary_by_topic else 1
        summary_row = summary_metadata_by_topic.get(topic_id, {})
        synthesis_created_at = str(
            summary_row.get("generated_at")
            or summary_row.get("created_at")
            or summary_row.get("updated_at")
            or ""
        )
        first_seen = str(topic.get("first_seen_at") or "")
        missing_first_seen = 1 if not first_seen else 0
        try:
            article_count = int(topic.get("article_count") or 0)
        except (TypeError, ValueError):
            article_count = 0
        if prefer_oldest_synthesis and has_summary == 0:
            return (
                has_summary,
                0 if synthesis_created_at else 1,
                synthesis_created_at or "9999-12-31T23:59:59+00:00",
                -article_count,
                topic_id,
            )
        return (
            has_summary,
            missing_first_seen,
            first_seen or "9999-12-31T23:59:59+00:00",
            -article_count,
            topic_id,
        )

    return min((str(topic_id) for topic_id in topic_ids), key=sort_key)


def merge_active_topics(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
    existing_summaries_only: bool = False,
    max_topics: int = 0,
    merged_article_ids_by_topic: dict[str, list[str]] | None = None,
) -> dict[str, int]:
    """Merge duplicate active topics before any final summary is generated.

    The repair mode deliberately keeps the normal 55-hour active-topic window,
    but narrows the input to topics that already have a saved synthesis. This
    lets it repair historical grouping mistakes without reopening archived
    topics or creating a first synthesis for a topic that never had one.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=TOPIC_MATCH_LOOKBACK_HOURS)).isoformat()
    topic_filters: list[tuple[str, str]] = [
        ("status", "eq.ACTIVE"),
        ("last_seen_at", f"gte.{cutoff}"),
    ]
    topics = client.select_all(
        "topics",
        columns=(
            "topic_id,headline_pl,status,first_seen_at,last_seen_at,"
            "article_count,source_count,coverage_status,needs_review"
        ),
        filters=topic_filters,
    )
    stats = {
        "merge_candidates": 0,
        "topics_merged": 0,
        "merge_failed": 0,
        "local_candidate_groups": 0,
        "local_candidate_topics": 0,
        "largest_candidate_group": 0,
        "semantic_candidate_edges": 0,
        "merge_requests": 0,
    }
    if len(topics) < 2:
        return stats

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        links = client.select_all("topic_articles", columns="topic_id,article_id")
        summaries = client.select_all(
            "topic_summaries",
            columns="topic_id,summary,input_hash,version,model,generated_at,updated_at",
        )
        summary_metadata_by_topic = {
            str(row["topic_id"]): row
            for row in summaries
        }
        summary_by_topic = {
            str(row["topic_id"]): stored_base_summary(row.get("summary"))
            for row in summaries
        }
        if existing_summaries_only:
            topics = [
                topic for topic in topics
                if str(topic.get("topic_id") or "") in summary_by_topic
            ]
            if max_topics > 0:
                topics = sorted(
                    topics,
                    key=lambda topic: (
                        str(topic.get("last_seen_at") or ""),
                        str(topic.get("topic_id") or ""),
                    ),
                    reverse=True,
                )[:max_topics]
            if len(topics) < 2:
                return stats
        ids_by_topic: dict[str, list[str]] = {}
        for row in links:
            ids_by_topic.setdefault(str(row["topic_id"]), []).append(str(row["article_id"]))
        category_rows = client.select_all("topic_categories", columns="topic_id,category")
        categories_by_topic: dict[str, list[str]] = {}
        for row in category_rows:
            category = normalize_topic_category(row.get("category"))
            if category:
                categories_by_topic.setdefault(str(row["topic_id"]), []).append(category)

        payload_topics: list[dict[str, Any]] = []
        topic_by_id = {str(row["topic_id"]): row for row in topics}
        for topic in topics:
            topic_id = str(topic["topic_id"])
            article_ids = list(dict.fromkeys(ids_by_topic.get(topic_id, [])))
            article_rows = local_articles(conn, article_ids)
            article_rows.sort(
                key=lambda row: (
                    str(row.get("published_at") or row.get("fetched_at") or ""),
                    str(row["article_id"]),
                ),
                reverse=True,
            )
            previous = summary_by_topic.get(topic_id) or {}
            previous_topic = previous.get("topic") if isinstance(previous.get("topic"), dict) else {}
            previous_summary = str(previous.get("summary_pl") or "").strip()
            payload_topics.append({
                "topic_id": topic_id,
                "headline_pl": str(topic.get("headline_pl") or ""),
                "categories": categories_by_topic.get(topic_id, []),
                "what_happened_one_sentence_pl": str(
                    previous_topic.get("what_happened_one_sentence_pl") or ""
                ),
                "summary_pl": previous_summary[:TOPIC_MERGE_SUMMARY_CHAR_LIMIT],
                "article_count": len(article_ids),
                "source_count": topic.get("source_count", 0),
                "first_seen_at": topic.get("first_seen_at", ""),
                "last_seen_at": topic.get("last_seen_at", ""),
                "recent_article_titles": [
                    str(row.get("title") or "")[:300]
                    for row in article_rows[:5]
                    if str(row.get("title") or "").strip()
                ],
            })

        semantic_edges: dict[tuple[str, str], float] = {}
        try:
            semantic_edges = build_topic_embedding_candidate_edges(payload_topics)
            stats["semantic_candidate_edges"] = len(semantic_edges)
        except Exception as exc:
            log(
                "AI",
                "Semantyczna selekcja niedostępna; używam lokalnego filtra "
                f"słów i fraz. Szczegóły: {short_text(exc, 180)}.",
                level="WARN",
            )
        candidate_groups = build_topic_merge_candidate_groups(
            payload_topics,
            semantic_edges=semantic_edges,
            preserve_candidate_edges=True,
        )
        merge_requests = build_topic_merge_requests(
            payload_topics,
            candidate_groups=candidate_groups,
            preserve_candidate_group_overlap=True,
        )
        stats["local_candidate_groups"] = len(candidate_groups)
        stats["local_candidate_topics"] = len({
            topic_id
            for group in candidate_groups
            for topic_id in group
        })
        stats["largest_candidate_group"] = max(
            (len(group) for group in candidate_groups),
            default=0,
        )
        total_merge_requests = len(merge_requests)
        if total_merge_requests > TOPIC_MERGE_MAX_REQUESTS:
            log(
                "AI",
                f"Scalanie: ograniczam liczbę zapytań z {total_merge_requests} do "
                f"{TOPIC_MERGE_MAX_REQUESTS}; reszta zostaje na kolejny przebieg.",
                level="WARN",
            )
            merge_requests = merge_requests[:TOPIC_MERGE_MAX_REQUESTS]
        stats["merge_requests"] = len(merge_requests)
        log(
            "AI",
            f"Scalanie: tematów: {len(payload_topics)}, "
            f"grup kandydackich: {stats['local_candidate_groups']}, "
            f"kandydatów w grupach: {stats['local_candidate_topics']}, "
            f"największa grupa: {stats['largest_candidate_group']}, "
            f"par semantycznych: {stats['semantic_candidate_edges']}, "
            f"zapytań do AI: {len(merge_requests)}.",
        )
        if not merge_requests:
            return stats

        raw_groups: list[dict[str, Any]] = []
        for request_index, request_topics in enumerate(merge_requests, start=1):
            started_at = time.monotonic()
            request_group_ids = {
                str(topic.get("candidate_group_id") or "")
                for topic in request_topics
                if str(topic.get("candidate_group_id") or "")
            }
            log(
                "AI",
                f"Scalanie {request_index}/{len(merge_requests)}: "
                f"tematów: {len(request_topics)}, "
                f"grup kandydackich: {len(request_group_ids)}.",
            )
            merge_input = {
                "active_topics": request_topics,
                "topic_memory_window_hours": TOPIC_MATCH_LOOKBACK_HOURS,
            }
            merge_hash = digest(merge_input)
            merge_run_id = "topicrun_" + digest({
                "run": run_id,
                "stage": "TOPIC_MERGE",
                "batch": request_index,
                "input": merge_hash,
            })[:24]
            try:
                result = call_openai(
                    TOPIC_MERGE_INSTRUCTIONS,
                    merge_input,
                    model,
                    max_output_tokens=TOPIC_MERGE_MAX_OUTPUT_TOKENS,
                    response_schema=TOPIC_MERGE_RESPONSE_SCHEMA,
                    response_schema_name="topic_merge",
                )
                client.upsert("topic_runs", [{
                    "topic_run_id": merge_run_id,
                    "run_id": run_id,
                    "stage": "TOPIC_MERGE",
                    "prompt_version": PROMPT_VERSION,
                    "model": model,
                    "input_hash": merge_hash,
                    "status": "COMPLETED",
                    "raw_output": response_for_storage(result),
                    "error": None,
                }], on_conflict="topic_run_id")
                batch_groups = result.get("merge_groups")
                if isinstance(batch_groups, list):
                    request_scope = {
                        str(topic["topic_id"]): str(topic.get("candidate_group_id") or "")
                        for topic in request_topics
                    }
                    for group in batch_groups:
                        if not isinstance(group, dict):
                            continue
                        raw_ids = group.get("topic_ids")
                        if not isinstance(raw_ids, list):
                            continue
                        ids = set(str(value) for value in raw_ids)
                        # Several disjoint groups now share one request. Enforce
                        # the prompt's scope in code too, including foreign IDs.
                        if (
                            len(ids) < 2
                            or not ids.issubset(request_scope)
                            or len({request_scope[topic_id] for topic_id in ids}) != 1
                        ):
                            log("AI", "Pominięto scalenie spoza jednej grupy kandydatów.", level="WARN")
                            continue
                        raw_groups.append(group)
                log(
                    "AI",
                    f"Scalanie {request_index}/{len(merge_requests)} zakończone: "
                    f"grup: {len(batch_groups or [])}, "
                    f"czas {seconds(time.monotonic() - started_at)}.",
                )
            except Exception as exc:
                log_parse_failure("TOPIC_MERGE", exc)
                client.upsert("topic_runs", [{
                    "topic_run_id": merge_run_id,
                    "run_id": run_id,
                    "stage": "TOPIC_MERGE",
                    "prompt_version": PROMPT_VERSION,
                    "model": model,
                    "input_hash": merge_hash,
                    "status": "FAILED",
                    "raw_output": parse_failure_for_storage(exc),
                    "error": str(exc)[:2000],
                }], on_conflict="topic_run_id")
                stats["merge_failed"] += 1
                log(
                    "AI",
                    f"Scalanie {request_index}/{len(merge_requests)} nieudane po "
                    f"{seconds(time.monotonic() - started_at)}; przechodzę dalej.",
                    level="ERROR",
                )

        if not raw_groups:
            return stats

        used_topic_ids: set[str] = set()
        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                continue
            try:
                confidence = float(raw_group.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0
            group_ids = list(dict.fromkeys(
                str(value) for value in raw_group.get("topic_ids", [])
                if str(value) in topic_by_id
            ))
            if (
                confidence < TOPIC_MERGE_MIN_CONFIDENCE
                or len(group_ids) < 2
                or used_topic_ids.intersection(group_ids)
            ):
                continue
            stats["merge_candidates"] += 1
            used_topic_ids.update(group_ids)

            article_ids = list(dict.fromkeys(
                article_id
                for topic_id in group_ids
                for article_id in ids_by_topic.get(topic_id, [])
            ))
            article_rows = local_articles(conn, article_ids)
            if len(article_rows) < 2:
                continue
            source_ids = {str(row["source_id"]) for row in article_rows}
            first_seen_values = [
                str(topic_by_id[topic_id].get("first_seen_at") or "")
                for topic_id in group_ids
            ]
            last_seen_values = [
                str(topic_by_id[topic_id].get("last_seen_at") or "")
                for topic_id in group_ids
            ]
            title = str(raw_group.get("merged_title_pl") or "").strip()
            article_titles = [
                str(row.get("title") or "")
                for row in article_rows
                if str(row.get("title") or "").strip()
            ]
            if (
                not is_usable_topic_title(title)
                or is_article_title_copy(title, article_titles)
            ):
                title = fallback_topic_title(
                    "",
                    "",
                    [
                        str(topic_by_id[topic_id].get("headline_pl") or "")
                        for topic_id in group_ids
                    ] + article_titles,
                )
            # Preserve the identity of an established topic. In particular,
            # keep a topic that already has a synthesis so the final summary
            # pass appends an update instead of starting a new aggregation.
            canonical_id = choose_merge_canonical_topic_id(
                group_ids,
                topic_by_id,
                summary_by_topic,
                summary_metadata_by_topic=summary_metadata_by_topic,
                prefer_oldest_synthesis=existing_summaries_only,
            )
            merge_timestamp = now()
            if len(article_ids) == 1:
                coverage_status = "SINGLE_ARTICLE"
            elif len(source_ids) == 1:
                coverage_status = "SINGLE_SOURCE"
            else:
                coverage_status = "MULTI_SOURCE"
            client.upsert("topics", [{
                "topic_id": canonical_id,
                "headline_pl": title[:300],
                "status": "ACTIVE",
                "first_seen_at": min(value for value in first_seen_values if value) if any(first_seen_values) else now(),
                "last_seen_at": max(last_seen_values) if any(last_seen_values) else now(),
                "article_count": len(article_ids),
                "source_count": len(source_ids),
                "coverage_status": coverage_status,
                "needs_review": any(bool(topic_by_id[topic_id].get("needs_review")) for topic_id in group_ids),
                "updated_at": now(),
            }], on_conflict="topic_id")
            merged_categories = normalize_topic_categories(raw_group.get("categories"))
            if not merged_categories:
                merged_categories = list(dict.fromkeys(
                    category
                    for topic_id in group_ids
                    for category in categories_by_topic.get(topic_id, [])
                ))[:3]
            if len(source_ids) >= 2 and has_independent_source(article_rows) and merged_categories:
                persist_topic_categories(client, canonical_id, merged_categories)
            canonical_article_ids = set(ids_by_topic.get(canonical_id, []))
            existing_link_rows = [
                {
                    "topic_id": canonical_id,
                    "article_id": article_id,
                    "confidence": confidence,
                }
                for article_id in article_ids
                if article_id in canonical_article_ids
            ]
            moved_link_rows = [
                {
                    "topic_id": canonical_id,
                    "article_id": article_id,
                    "confidence": confidence,
                    "assigned_at": merge_timestamp,
                }
                for article_id in article_ids
                if article_id not in canonical_article_ids
            ]
            if merged_article_ids_by_topic is not None and moved_link_rows:
                merged_article_ids_by_topic.setdefault(canonical_id, []).extend(
                    row["article_id"] for row in moved_link_rows
                )
            # PostgREST requires every object in one upsert payload to have
            # the same keys. Keep rows with the optional assigned_at field in
            # a separate request from links that already existed.
            client.upsert(
                "topic_articles",
                existing_link_rows,
                on_conflict="topic_id,article_id",
            )
            client.upsert(
                "topic_articles",
                moved_link_rows,
                on_conflict="topic_id,article_id",
            )

            for old_topic_id in group_ids:
                if old_topic_id == canonical_id:
                    continue
                client.update(
                    "article_topic_assignments",
                    # Reassignment makes these articles new material for the
                    # retained topic, so its existing synthesis receives an
                    # update even when the merged-in topic had its own history.
                    {"topic_id": canonical_id, "created_at": merge_timestamp},
                    filters=[("topic_id", f"eq.{old_topic_id}")],
                )
                client.delete(
                    "topic_articles",
                    filters=[("topic_id", f"eq.{old_topic_id}")],
                )
                try:
                    client.update(
                        "topics",
                        {
                            "status": "MERGED",
                            "merged_into_topic_id": canonical_id,
                            "merged_at": now(),
                            "updated_at": now(),
                        },
                        filters=[("topic_id", f"eq.{old_topic_id}")],
                    )
                except Exception as exc:
                    # The status fallback keeps the duplicate out of the app
                    # even before the optional redirect-column migration runs.
                    log(
                        "AI",
                        "Nie zapisano przekierowania scalonego tematu; "
                        "uruchom supabase_migration_topic_merges.sql. "
                        f"Szczegóły: {short_text(exc, 180)}.",
                        level="WARN",
                    )
                    client.update(
                        "topics",
                        {"status": "MERGED", "updated_at": now()},
                        filters=[("topic_id", f"eq.{old_topic_id}")],
                    )
            stats["topics_merged"] += len(group_ids)
            log(
                "AI",
                f"Scalono grupę tematów: {len(group_ids)} "
                f"(pewność: {confidence:.2f}); synteza zachowanego tematu zostanie zaktualizowana.",
            )
        return stats
    finally:
        conn.close()


def merge_existing_summaries(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
    max_topics: int = 0,
) -> dict[str, int]:
    """Repair duplicate active synthesized topics and update retained summaries.

    This is intentionally separate from the normal pending-article pipeline:
    it never labels articles or considers topics without an existing summary.
    The merge step records moved article IDs, so the following summary step
    generates a delta update while preserving the retained topic's original
    base synthesis.
    """
    merged_article_ids_by_topic: dict[str, list[str]] = {}
    merge_stats = merge_active_topics(
        db_path,
        run_id,
        client,
        model=model,
        existing_summaries_only=True,
        max_topics=max_topics,
        merged_article_ids_by_topic=merged_article_ids_by_topic,
    )
    summary_stats = retry_incomplete_summaries(
        db_path,
        run_id,
        client,
        model=model,
        forced_new_article_ids_by_topic=merged_article_ids_by_topic,
        only_topic_ids=set(merged_article_ids_by_topic),
    )
    merge_stats["summaries"] = summary_stats["summaries"]
    merge_stats["failed_summaries"] = summary_stats["failed_summaries"]
    log(
        "AI-REPAIR",
        f"Istniejące syntezy: scalono tematów: {merge_stats['topics_merged']}; "
        f"zaktualizowano syntez: {summary_stats['summaries']}; "
        f"nieudane aktualizacje: {summary_stats['failed_summaries']}.",
    )
    return merge_stats


def normalize_topic_titles(
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
) -> int:
    topics = client.select_all(
        "topics",
        columns="topic_id,headline_pl,status",
        filters=[("status", "neq.MERGED")],
    )
    summaries = {
        str(row["topic_id"]): stored_base_summary(row.get("summary"))
        for row in client.select_all("topic_summaries", columns="topic_id,summary")
    }
    links_by_topic: dict[str, list[str]] = {}
    for row in client.select_all("topic_articles", columns="topic_id,article_id"):
        links_by_topic.setdefault(str(row["topic_id"]), []).append(str(row["article_id"]))
    article_rows = client.select_all(
        "articles",
        columns="article_id,title,opening_text",
    )
    article_titles = {
        str(row["article_id"]): str(row.get("title") or "").strip()
        for row in article_rows
    }
    article_openings = {
        str(row["article_id"]): str(row.get("opening_text") or "").strip()
        for row in article_rows
    }
    titles_by_topic = {
        topic_id: [article_titles[article_id] for article_id in article_ids if article_titles.get(article_id)]
        for topic_id, article_ids in links_by_topic.items()
    }
    openings_by_topic = {
        topic_id: [
            article_openings[article_id][:800]
            for article_id in article_ids
            if article_openings.get(article_id)
        ]
        for topic_id, article_ids in links_by_topic.items()
    }
    missing = [
        row for row in topics
        if not is_usable_topic_title(row.get("headline_pl"))
        or has_composite_geo_prefix(row.get("headline_pl"))
        or is_article_title_copy(
            row.get("headline_pl"),
            titles_by_topic.get(str(row["topic_id"]), []),
        )
    ]
    changed = 0
    if not missing:
        log("AI", "Tytuły: wszystkie są już w poprawnym formacie.")
        return 0
    total_batches = (
        len(missing) + TITLE_NORMALIZATION_BATCH_SIZE - 1
    ) // TITLE_NORMALIZATION_BATCH_SIZE
    log("AI", f"Tytuły: poprawiam {len(missing)} tematów w {total_batches} paczkach.")
    for offset in range(0, len(missing), TITLE_NORMALIZATION_BATCH_SIZE):
        batch_number = offset // TITLE_NORMALIZATION_BATCH_SIZE + 1
        batch = missing[offset:offset + TITLE_NORMALIZATION_BATCH_SIZE]
        log(
            "AI",
            f"Tytuły {batch_number}/{total_batches}: analizuję {len(batch)} tematów "
            f"(model: {TITLE_MODEL}, timeout: {TITLE_NORMALIZATION_REQUEST_TIMEOUT_SECONDS:.0f} s).",
        )
        payload = {"topics": [{
            "topic_id": row["topic_id"],
            "current_title_pl": row.get("headline_pl") or "",
            "one_sentence_pl": (
                (summaries.get(str(row["topic_id"]), {}).get("topic") or {})
                .get("what_happened_one_sentence_pl", "")
            ),
            "summary_pl": str(
                summaries.get(str(row["topic_id"]), {}).get("summary_pl") or ""
            )[:800],
            "article_titles": titles_by_topic.get(str(row["topic_id"]), [])[:5],
            "article_openings": openings_by_topic.get(str(row["topic_id"]), [])[:2],
        } for row in batch]}
        try:
            result = call_openai(
                TITLE_NORMALIZATION_INSTRUCTIONS,
                payload,
                TITLE_MODEL,
                max_output_tokens=TITLE_NORMALIZATION_MAX_OUTPUT_TOKENS,
                timeout_seconds=TITLE_NORMALIZATION_REQUEST_TIMEOUT_SECONDS,
                retry_limit=TITLE_NORMALIZATION_MAX_RETRIES,
                response_schema=TITLE_RESPONSE_SCHEMA,
                response_schema_name="topic_titles",
            )
        except Exception as exc:
            result = {}
            log(
                "AI",
                f"Tytuły {batch_number}/{total_batches}: AI nie odpowiedziało; "
                f"stosuję fallback dla tej paczki ({short_text(exc, 180)}).",
                level="WARN",
            )
        allowed = {str(row["topic_id"]) for row in batch}
        by_id = {str(row["topic_id"]): row for row in batch}
        candidate_titles: dict[str, str] = {}
        for item in result.get("titles") or []:
            if not isinstance(item, dict):
                continue
            topic_id = str(item.get("topic_id") or "")
            if topic_id not in allowed:
                continue
            row = by_id[topic_id]
            title = format_topic_title_candidate(item.get("title_pl"), row.get("headline_pl"))
            if (
                not is_usable_topic_title(title)
                or has_composite_geo_prefix(title)
                or is_article_title_copy(
                    title,
                    titles_by_topic.get(topic_id, []),
                )
            ):
                continue
            candidate_titles[topic_id] = title

        for row in batch:
            topic_id = str(row["topic_id"])
            title = candidate_titles.get(topic_id)
            if not title:
                summary = summaries.get(topic_id, {})
                topic_summary = summary.get("topic") if isinstance(summary.get("topic"), dict) else {}
                title = fallback_topic_title(
                    "",
                    topic_summary.get("what_happened_one_sentence_pl", "")
                    or (openings_by_topic.get(topic_id) or [""])[0],
                    titles_by_topic.get(topic_id, []),
                )
            client.update(
                "topics",
                {"headline_pl": title, "updated_at": now()},
                filters=[("topic_id", f"eq.{topic_id}")],
            )
            changed += 1
        log("AI", f"Tytuły {batch_number}/{total_batches} zakończone.")

    remaining = [
        row for row in client.select_all(
            "topics",
            columns="topic_id,headline_pl,status",
            filters=[("status", "neq.MERGED")],
        )
        if not is_usable_topic_title(row.get("headline_pl"))
    ]
    if remaining:
        bad_ids = ", ".join(str(row.get("topic_id")) for row in remaining[:10])
        raise RuntimeError(
            "Quality gate tytułów nie przepuścił tematów bez konkretnego tytułu: "
            f"{bad_ids}"
        )
    log("AI", f"Tytuły zakończone: poprawiono {changed} tematów.")
    return changed


def classify_topic_categories(
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
    batch_size: int = CATEGORY_BATCH_SIZE,
) -> int:
    """Fill missing topic categories without overwriting reviewed categories."""
    topics = client.select_all(
        "topics",
        columns="topic_id,headline_pl,status,source_count",
        filters=[("status", "neq.MERGED")],
    )
    existing_rows = client.select_all("topic_categories", columns="topic_id,category")
    existing_categories: dict[str, list[str]] = {}
    for row in existing_rows:
        category = normalize_topic_category(row.get("category"))
        if category:
            existing_categories.setdefault(str(row["topic_id"]), []).append(category)

    # Categories are presentation metadata for synthesized, multi-source
    # topics. Do not retain stale categories on singleton/single-source
    # topics, and never send those topics to the classifier.
    def has_multiple_sources(row: dict[str, Any]) -> bool:
        try:
            return int(row.get("source_count") or 0) >= 2
        except (TypeError, ValueError):
            return False

    links = client.select_all("topic_articles", columns="topic_id,article_id")
    article_rows = client.select_all(
        "articles",
        columns="article_id,source_profile,source_type,title",
    )
    article_by_id = {str(row["article_id"]): row for row in article_rows}
    independent_topic_ids = {
        str(row["topic_id"])
        for row in links
        if not is_state_source(article_by_id.get(str(row["article_id"]), {}))
    }
    eligible_topic_ids = {
        str(row["topic_id"])
        for row in topics
        if has_multiple_sources(row) and str(row["topic_id"]) in independent_topic_ids
    }
    for topic_id in existing_categories:
        if topic_id not in eligible_topic_ids:
            client.delete("topic_categories", filters=[("topic_id", f"eq.{topic_id}")])
    missing = [
        row for row in topics
        if str(row["topic_id"]) in eligible_topic_ids
        and not existing_categories.get(str(row["topic_id"]))
    ]
    if not missing:
        log("AI", "Kategorie: wszystkie kwalifikujące się tematy mają już kategorię.")
        return 0

    summaries = {
        str(row["topic_id"]): stored_base_summary(row.get("summary"))
        for row in client.select_all("topic_summaries", columns="topic_id,summary")
    }
    article_ids_by_topic: dict[str, list[str]] = {}
    for row in links:
        article_ids_by_topic.setdefault(str(row["topic_id"]), []).append(str(row["article_id"]))
    article_titles = {
        str(row["article_id"]): str(row.get("title") or "")
        for row in article_rows
    }

    classified = 0
    batch_size = min(max(1, batch_size), CATEGORY_BATCH_SIZE)
    batches = [
        missing[offset:offset + batch_size]
        for offset in range(0, len(missing), batch_size)
    ]

    def process_batch(batch: list[dict[str, Any]], label: str) -> None:
        nonlocal classified
        payload_topics = []
        for row in batch:
            topic_id = str(row["topic_id"])
            summary = summaries.get(topic_id) or {}
            summary_topic = summary.get("topic") if isinstance(summary.get("topic"), dict) else {}
            titles = [
                article_titles[article_id][:220]
                for article_id in article_ids_by_topic.get(topic_id, [])
                if article_titles.get(article_id)
            ]
            payload_topics.append({
                "topic_id": topic_id,
                "headline_pl": str(row.get("headline_pl") or ""),
                "what_happened_one_sentence_pl": str(
                    summary_topic.get("what_happened_one_sentence_pl") or ""
                )[:300],
                "recent_article_titles": titles[:2],
            })

        log(
            "AI",
            f"Kategorie {label}/{len(batches)}: tematów w paczce: {len(batch)}.",
        )
        try:
            result = call_openai(
                CATEGORY_INSTRUCTIONS,
                {"topics": payload_topics},
                model,
                max_output_tokens=CATEGORY_MAX_OUTPUT_TOKENS,
                timeout_seconds=CATEGORY_REQUEST_TIMEOUT_SECONDS,
                retry_limit=CATEGORY_MAX_RETRIES,
                response_schema=CATEGORY_RESPONSE_SCHEMA,
                response_schema_name="topic_categories",
            )
        except Exception as exc:
            retryable = isinstance(exc, AIResponseParseError) or is_retryable_openai_error(exc)
            if retryable and len(batch) > CATEGORY_MIN_RETRY_BATCH_SIZE:
                midpoint = len(batch) // 2
                log(
                    "AI",
                    f"Kategorie {label}: dzielę paczkę po błędzie na "
                    f"{midpoint} + {len(batch) - midpoint} tematów "
                    f"({short_text(openai_error_details(exc), 180)}).",
                    level="WARN",
                )
                process_batch(batch[:midpoint], f"{label}a")
                process_batch(batch[midpoint:], f"{label}b")
                return
            if retryable:
                log(
                    "AI",
                    f"Kategorie {label}: pomijam paczkę po błędzie "
                    f"({short_text(openai_error_details(exc), 180)}); "
                    "spróbuję ponownie przy kolejnym uruchomieniu.",
                    level="ERROR",
                )
                return
            raise

        allowed = {str(row["topic_id"]) for row in batch}
        for item in result.get("categories") or []:
            if not isinstance(item, dict):
                continue
            topic_id = str(item.get("topic_id") or "")
            categories = normalize_topic_categories(item.get("categories") or item.get("category"))
            if topic_id not in allowed or not categories:
                continue
            client.delete("topic_categories", filters=[("topic_id", f"eq.{topic_id}")])
            client.upsert(
                "topic_categories",
                [{"topic_id": topic_id, "category": category} for category in categories],
                on_conflict="topic_id,category",
            )
            client.update(
                "topics",
                {"updated_at": now()},
                filters=[("topic_id", f"eq.{topic_id}")],
            )
            classified += 1
        log(
            "AI",
            f"Kategorie {label}/{len(batches)} zakończone: "
            f"łącznie przypisano kategorię: {quantity(classified, 'tematowi', 'tematom', 'tematom')}.",
        )

    for offset, batch in enumerate(batches, start=1):
        process_batch(batch, str(offset))
    log("AI", f"Kategorie zakończone: przypisano kategorię: {quantity(classified, 'tematowi', 'tematom', 'tematom')}.")
    return classified


def pending_articles(conn: sqlite3.Connection, client: SupabaseRestClient, limit: int) -> list[dict[str, Any]]:
    assigned_rows = client.select_all("article_topic_assignments", columns="article_id")
    assigned = {str(row["article_id"]) for row in assigned_rows}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=UNASSIGNED_ARTICLE_LOOKBACK_HOURS)

    def still_fresh(row: dict[str, Any]) -> bool:
        raw = str(row.get("fetched_at") or row.get("first_seen_at") or "").strip()
        if not raw:
            return False
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed >= cutoff
        except ValueError:
            return False

    articles = [
        row for row in local_articles(conn)
        if row["article_id"] not in assigned
        and not str(row.get("topic_hint") or "").startswith("AI_EXCLUDED:")
        and still_fresh(row)
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


def persist_topic_categories(
    client: SupabaseRestClient,
    topic_id: str,
    categories: Any,
) -> list[str]:
    """Persist initial categories without overwriting an existing assignment.

    Existing rows may be the result of a manual review, so a later summary
    refresh must not silently replace them with the model's new suggestion.
    """
    normalized = normalize_topic_categories(categories)
    if not normalized:
        return []
    existing_rows = client.select_all(
        "topic_categories",
        columns="category",
        filters=[("topic_id", f"eq.{topic_id}")],
    )
    existing = normalize_topic_categories([row.get("category") for row in existing_rows])
    if existing:
        return existing
    client.upsert(
        "topic_categories",
        [{"topic_id": topic_id, "category": category} for category in normalized],
        on_conflict="topic_id,category",
    )
    return normalized


def persist_summary(
    client: SupabaseRestClient,
    *,
    topic_id: str,
    run_id: str,
    model: str,
    summary: dict[str, Any],
    summary_hash: str,
    previous_row: dict[str, Any] | None,
    new_article_ids: list[str],
) -> int:
    """Save an immutable base and append one cumulative update per full run."""
    persist_topic_categories(
        client,
        topic_id,
        (summary.get("topic") or {}).get("categories")
        if isinstance(summary.get("topic"), dict)
        else [],
    )
    version = int((previous_row or {}).get("version", 0)) + 1
    timestamp = now()
    previous_stored = previous_row.get("summary") if previous_row else None
    if previous_stored:
        base_summary = stored_base_summary(previous_stored)
        updates = stored_updates(previous_stored)
        latest_update = dict(summary.get("update") or empty_update())
        latest_update["is_update"] = True
    else:
        base_summary = dict(summary)
        base_summary["update"] = empty_update()
        updates = []
        latest_update = empty_update()

    latest_update["new_article_ids"] = list(dict.fromkeys(str(article_id) for article_id in new_article_ids))
    update_text = str(
        latest_update.get("new_information_pl")
        or latest_update.get("what_changed_pl")
        or ""
    ).strip()
    if previous_stored and not update_text:
        # A blank AI update is safer than a reader-facing verdict about the
        # material or the grouping. Normal generation retries before reaching
        # this branch; this is only a defensive fallback for legacy callers.
        latest_update["new_information_pl"] = ""
    if previous_stored:
        latest_update["run_id"] = run_id
        latest_update["generated_at"] = timestamp
        updates = [item for item in updates if str(item.get("run_id") or "") != run_id]
        updates.append(latest_update)
    stored_summary = {
        "base_summary": base_summary,
        "updates": updates,
        "latest_update": latest_update,
    }
    client.upsert("topic_summaries", [{
        "topic_id": topic_id,
        "version": version,
        "input_hash": summary_hash,
        "model": model,
        "summary": stored_summary,
        "generated_at": timestamp,
        "updated_at": timestamp,
    }], on_conflict="topic_id")
    try:
        client.upsert("topic_summary_versions", [{
            "topic_id": topic_id,
            "version": version,
            "run_id": run_id,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "summary": stored_summary,
            "new_article_ids": latest_update["new_article_ids"],
            "generated_at": timestamp,
        }], on_conflict="topic_id,version")
    except Exception as exc:
        # Backwards compatibility: current summaries remain usable even if the
        # optional history migration has not been run yet.
        log(
            "AI",
            "Nie zapisano historii wersji tematu; uruchom "
            f"supabase_migration_topic_updates.sql. Szczegóły: {short_text(exc, 180)}.",
            level="WARN",
        )
    return version


def retry_incomplete_summaries(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
    forced_new_article_ids_by_topic: dict[str, list[str]] | None = None,
    only_topic_ids: set[str] | None = None,
) -> dict[str, int]:
    """Finalize one summary/update per topic after all batches and merges."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = {"summaries": 0, "failed_summaries": 0}
    try:
        topics = client.select_all("topics", filters=[("status", "eq.ACTIVE")])
        links = client.select_all("topic_articles", columns="topic_id,article_id")
        summaries = client.select_all(
            "topic_summaries", columns="topic_id,summary,input_hash,version,updated_at"
        )
        assignments = client.select_all(
            "article_topic_assignments", columns="topic_id,article_id,created_at"
        )
        ids_by_topic: dict[str, list[str]] = {}
        for row in links:
            ids_by_topic.setdefault(str(row["topic_id"]), []).append(str(row["article_id"]))
        latest_assignment_by_topic: dict[str, str] = {}
        assignment_time_by_article: dict[tuple[str, str], str] = {}
        for row in assignments:
            topic_id = str(row["topic_id"])
            article_id = str(row["article_id"])
            created_at = str(row.get("created_at") or "")
            if created_at > latest_assignment_by_topic.get(topic_id, ""):
                latest_assignment_by_topic[topic_id] = created_at
            assignment_time_by_article[(topic_id, article_id)] = created_at
        summary_by_topic = {str(row["topic_id"]): row for row in summaries}
        forced_new_article_ids_by_topic = forced_new_article_ids_by_topic or {}
        summary_jobs: list[dict[str, Any]] = []

        for topic in topics:
            topic_id = str(topic.get("topic_id") or "")
            if only_topic_ids is not None and topic_id not in only_topic_ids:
                continue
            all_ids = list(dict.fromkeys(ids_by_topic.get(topic_id, [])))
            if not topic_id or len(all_ids) < 2:
                continue
            previous_row = summary_by_topic.get(topic_id)
            forced_new_ids = list(dict.fromkeys(
                str(article_id)
                for article_id in forced_new_article_ids_by_topic.get(topic_id, [])
                if str(article_id) in all_ids
            ))
            previous_updated_at = str((previous_row or {}).get("updated_at") or "")
            latest_assignment = latest_assignment_by_topic.get(topic_id, "")
            if previous_row and latest_assignment <= previous_updated_at and not forced_new_ids:
                continue
            new_ids = forced_new_ids or [
                article_id for article_id in all_ids
                if not previous_row
                or assignment_time_by_article.get((topic_id, article_id), "") > previous_updated_at
            ]
            if not new_ids:
                continue
            new_rows = local_articles(conn, new_ids)
            all_rows = local_articles(conn, all_ids)
            if len(new_rows) == 0 or len(all_rows) < 2:
                continue
            if (
                len(distinct_source_keys(all_rows)) < 2
                or not has_independent_source(all_rows)
            ):
                continue
            previous_aggregation = previous_aggregation_context(previous_row.get("summary")) if previous_row else None
            summary_input_base = {
                "topic": {
                    "topic_id": topic_id,
                    "working_title_pl": str(topic.get("headline_pl") or ""),
                    "topic_action": "DEVELOPMENT" if previous_aggregation else "NEW_TOPIC",
                },
                "previous_aggregation": previous_aggregation,
                "all_article_ids_in_topic": all_ids,
            }
            summary_jobs.append({
                "topic_id": topic_id,
                "title": str(topic.get("headline_pl") or topic_id),
                "new_ids": new_ids,
                "new_rows": new_rows,
                "all_rows": all_rows,
                "previous_row": previous_row,
                "previous_aggregation": previous_aggregation,
                "summary_input_base": summary_input_base,
            })

        if not summary_jobs:
            log("AI", "Syntezy: nie ma tematów oczekujących na nową syntezę.")
            return stats

        total_jobs = len(summary_jobs)
        log("AI", f"Syntezy: przygotowano {total_jobs} tematów do wygenerowania.")
        for index, job in enumerate(summary_jobs, start=1):
            topic_id = job["topic_id"]
            new_ids = job["new_ids"]
            new_rows = job["new_rows"]
            all_rows = job["all_rows"]
            previous_row = job["previous_row"]
            previous_aggregation = job["previous_aggregation"]
            summary_input, payload_chars, payload_mode = build_bounded_summary_input(
                job["summary_input_base"],
                new_rows,
                all_rows if previous_aggregation is None else None,
            )
            summary_hash = digest(summary_input)
            summary_topic_run_id = "topicrun_" + digest({
                "topic": topic_id, "stage": "SUMMARY", "input": summary_hash,
            })[:24]
            log(
                "AI",
                f"Synteza {index}/{total_jobs}: {short_text(job['title'])} "
                f"(nowych: {len(new_rows)}, łącznie: {len(all_rows)}; "
                f"pozostało: {total_jobs - index + 1}; dane: {payload_mode}, "
                f"{payload_chars / 1024:.1f} KiB).",
            )
            try:
                summary = normalize_summary_response(call_openai(
                    SUMMARY_INSTRUCTIONS,
                    summary_input,
                    model,
                    timeout_seconds=SUMMARY_REQUEST_TIMEOUT_SECONDS,
                    response_schema=SUMMARY_RESPONSE_SCHEMA,
                    response_schema_name="topic_summary",
                ))
                if previous_aggregation and update_needs_repair(summary):
                    log(
                        "AI",
                        f"Synteza {index}/{total_jobs}: odpowiedź wymaga poprawy, "
                        "bo zawierała komentarz techniczny zamiast faktów.",
                        level="WARN",
                    )
                    summary = normalize_summary_response(
                        call_openai(
                            SUMMARY_UPDATE_REPAIR_INSTRUCTIONS,
                            summary_input,
                            model,
                            timeout_seconds=SUMMARY_REQUEST_TIMEOUT_SECONDS,
                            response_schema=SUMMARY_RESPONSE_SCHEMA,
                            response_schema_name="topic_summary_repair",
                        )
                    )
                    if update_needs_repair(summary):
                        raise ValueError(
                            "AI nie wygenerowało faktograficznej aktualizacji "
                            "bez metakomentarza o grupowaniu materiałów."
                        )
                persist_summary(
                    client,
                    topic_id=topic_id,
                    run_id=run_id,
                    model=model,
                    summary=summary,
                    summary_hash=summary_hash,
                    previous_row=previous_row,
                    new_article_ids=new_ids,
                )
                client.upsert("topic_runs", [{
                    "topic_run_id": summary_topic_run_id, "run_id": run_id,
                    "stage": "SUMMARY", "prompt_version": PROMPT_VERSION,
                    "model": model, "input_hash": summary_hash, "status": "COMPLETED",
                    "raw_output": response_for_storage(summary), "error": None,
                }], on_conflict="topic_run_id")
                stats["summaries"] += 1
                log(
                    "AI",
                    f"Synteza {index}/{total_jobs} gotowa; pozostało {total_jobs - index}.",
                )
            except Exception as exc:
                log_parse_failure("SUMMARY", exc)
                if not isinstance(exc, AIResponseParseError):
                    log(
                        "AI",
                        f"Synteza {index}/{total_jobs} nieudana: {short_text(exc, 220)}.",
                        level="ERROR",
                    )
                client.upsert("topic_runs", [{
                    "topic_run_id": summary_topic_run_id, "run_id": run_id,
                    "stage": "SUMMARY", "prompt_version": PROMPT_VERSION,
                    "model": model, "input_hash": summary_hash, "status": "FAILED",
                    "raw_output": parse_failure_for_storage(exc), "error": str(exc)[:2000],
                }], on_conflict="topic_run_id")
                stats["failed_summaries"] += 1
        return stats
    finally:
        conn.close()


def stable_topic_id(article_ids: list[str], title: str) -> str:
    return "topic_" + digest({"article_ids": sorted(article_ids), "title": title})[:24]


def _label_pending_batch(
    run_id: str,
    client: SupabaseRestClient,
    articles: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    batch_index: str | int = 1,
) -> dict[str, int]:
    """Give every new article its own merge candidate and a general label.

    Stage 1 deliberately does not see active topics. This keeps naming cheap
    and deterministic at the article level; the cross-article decision belongs
    exclusively to ``merge_active_topics`` in Stage 2.
    """
    openai_api_key()
    stats = {
        "pending_articles": len(articles),
        "labeled_articles": 0,
        "candidate_topics": 0,
        "label_needs_review": 0,
    }
    if not articles:
        return stats

    labeling_input = {
        "articles": [
            article_for_topic_label(row, excerpt_words_limit=LABEL_EXCERPT_WORDS)
            for row in articles
        ],
    }
    labeling_hash = digest(labeling_input)
    labeling_topic_run_id = "topicrun_" + digest({
        "run": run_id,
        "stage": "LABELING",
        "batch": batch_index,
        "input": labeling_hash,
    })[:24]
    try:
        labeling = call_openai(
            TOPIC_LABELING_INSTRUCTIONS,
            labeling_input,
            model,
            max_output_tokens=LABEL_MAX_OUTPUT_TOKENS,
            timeout_seconds=LABEL_REQUEST_TIMEOUT_SECONDS,
            retry_limit=LABEL_MAX_RETRIES,
            response_schema=TOPIC_LABEL_RESPONSE_SCHEMA,
            response_schema_name="topic_labels",
        )
        client.upsert("topic_runs", [{
            "topic_run_id": labeling_topic_run_id,
            "run_id": run_id,
            "stage": "LABELING",
            "prompt_version": PROMPT_VERSION,
            "model": model,
            "input_hash": labeling_hash,
            "status": "COMPLETED",
            "raw_output": response_for_storage(labeling),
            "error": None,
        }], on_conflict="topic_run_id")
    except Exception as exc:
        log_parse_failure("LABELING", exc)
        client.upsert("topic_runs", [{
            "topic_run_id": labeling_topic_run_id,
            "run_id": run_id,
            "stage": "LABELING",
            "prompt_version": PROMPT_VERSION,
            "model": model,
            "input_hash": labeling_hash,
            "status": "FAILED",
            "raw_output": parse_failure_for_storage(exc),
            "error": str(exc)[:2000],
        }], on_conflict="topic_run_id")
        raise

    labels_by_article_id: dict[str, dict[str, Any]] = {}
    for item in labeling.get("labels") or []:
        if not isinstance(item, dict):
            continue
        article_id = str(item.get("article_id") or "")
        if article_id in {str(row["article_id"]) for row in articles}:
            labels_by_article_id.setdefault(article_id, item)

    timestamp = now()
    topic_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []
    assignment_rows: list[dict[str, Any]] = []
    for row in articles:
        article_id = str(row["article_id"])
        label = labels_by_article_id.get(article_id, {})
        article_title = str(row.get("title") or "")
        title = format_topic_title_candidate(label.get("working_title_pl"), "")
        needs_review = False
        if (
            not is_usable_topic_title(title)
            or is_article_title_copy(title, [article_title])
        ):
            title = "[Świat] Wymaga doprecyzowania tematu"
            needs_review = True
        if article_id not in labels_by_article_id:
            needs_review = True
        topic_id = stable_topic_id([article_id], title)
        topic_rows.append({
            "topic_id": topic_id,
            "headline_pl": title[:300],
            "status": "ACTIVE",
            "first_seen_at": timestamp,
            "last_seen_at": timestamp,
            "article_count": 1,
            "source_count": 1,
            "coverage_status": "SINGLE_ARTICLE",
            "needs_review": needs_review,
            "updated_at": timestamp,
        })
        link_rows.append({
            "topic_id": topic_id,
            "article_id": article_id,
            "confidence": 1.0,
        })
        assignment_rows.append({
            "run_id": run_id,
            "article_id": article_id,
            "topic_id": topic_id,
            "confidence": 1.0,
            "needs_review": needs_review,
            "grouping_reason": (
                "Etap 1: osobny kandydat nazwany na podstawie tytułu i początku artykułu; "
                "scalanie nastąpi w etapie 2."
            ),
            "prompt_version": PROMPT_VERSION,
        })
        stats["candidate_topics"] += 1
        if needs_review:
            stats["label_needs_review"] += 1

    client.upsert("topics", topic_rows, on_conflict="topic_id")
    client.upsert("topic_articles", link_rows, on_conflict="topic_id,article_id")
    client.upsert(
        "article_topic_assignments",
        assignment_rows,
        on_conflict="run_id,article_id",
    )
    stats["labeled_articles"] = len(articles)
    return stats


def _analyze_pending_batch(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    articles: list[dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    batch_index: str | int = 1,
    summarize: bool = True,
    excluded_topic_ids: set[str] | None = None,
) -> dict[str, int]:
    openai_api_key()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = {
        "pending_articles": 0, "groups": 0, "summaries": 0,
        "skipped_summaries": 0, "skipped_single_source": 0,
        "failed_summaries": 0, "excluded": 0,
    }
    try:
        stats["pending_articles"] = len(articles)
        if not articles:
            return stats
        active_topics, topic_links, topic_context = active_topic_payload(
            client,
            excluded_topic_ids=excluded_topic_ids,
        )
        grouping_input = {
            "new_articles": [
                article_for_ai(row, excerpt_words_limit=GROUPING_EXCERPT_WORDS)
                for row in articles
            ],
            "active_topics": active_topics,
            "topic_memory_window_hours": TOPIC_MATCH_LOOKBACK_HOURS,
        }
        grouping_hash = digest(grouping_input)
        grouping_topic_run_id = "topicrun_" + digest({
            "run": run_id, "stage": "GROUPING", "batch": batch_index, "input": grouping_hash,
        })[:24]
        try:
            grouping = call_openai(
                GROUPING_INSTRUCTIONS,
                grouping_input,
                model,
                response_schema=GROUPING_RESPONSE_SCHEMA,
                response_schema_name="article_grouping",
            )
            client.upsert("topic_runs", [{
                "topic_run_id": grouping_topic_run_id, "run_id": run_id,
                "stage": "GROUPING", "prompt_version": PROMPT_VERSION,
                "model": model, "input_hash": grouping_hash, "status": "COMPLETED",
                "raw_output": response_for_storage(grouping), "error": None,
            }], on_conflict="topic_run_id")
        except Exception as exc:
            log_parse_failure("GROUPING", exc)
            client.upsert("topic_runs", [{
                "topic_run_id": grouping_topic_run_id, "run_id": run_id,
                "stage": "GROUPING", "prompt_version": PROMPT_VERSION,
                "model": model, "input_hash": grouping_hash, "status": "FAILED",
                "raw_output": parse_failure_for_storage(exc), "error": str(exc)[:2000],
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
        link_rows: list[dict[str, Any]] = []
        assignment_rows: list[dict[str, Any]] = []
        group_data_by_topic: dict[str, dict[str, Any]] = {}
        duplicate_topic_ids: set[str] = set()
        quality_gate_singletons: set[str] = set()
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_seen_ids: set[str] = set()
            ids = []
            for value in group.get("article_ids", []):
                article_id = str(value)
                if (
                    article_id in input_by_id
                    and article_id not in excluded_ids
                    and article_id not in assigned_ids
                    and article_id not in group_seen_ids
                ):
                    ids.append(article_id)
                    group_seen_ids.add(article_id)
            if not ids:
                continue
            try:
                confidence = float(group.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            needs_review = bool(group.get("needs_review", False))
            relevance_ids = {
                str(item.get("article_id") or "")
                for item in (group.get("article_relevance") or [])
                if isinstance(item, dict)
                and len(str(item.get("why_same_event") or "").strip()) >= 12
            }
            topic_anchor = str(group.get("topic_anchor_pl") or "").strip()
            existing_topic_id = str(group.get("existing_topic_id") or "").strip()
            if existing_topic_id and existing_topic_id in (excluded_topic_ids or set()):
                # Repair context deliberately hides the old fallback topic;
                # never let a hallucinated ID reattach the article to it.
                existing_topic_id = ""
            requires_cohesion_gate = len(ids) > 1 or bool(existing_topic_id)
            if requires_cohesion_gate and confidence < GROUPING_MIN_CONFIDENCE:
                quality_gate_singletons.update(ids)
                continue

            # needs_review and incomplete article_relevance are audit signals,
            # not reasons to turn an otherwise credible group into singletons.
            if requires_cohesion_gate and (
                not topic_anchor or not set(ids).issubset(relevance_ids)
            ):
                needs_review = True

            assigned_ids.update(ids)
            title = str(group.get("working_title_pl") or "").strip()[:300]
            article_titles = [
                str(input_by_id[article_id].get("title") or "")
                for article_id in ids
            ]
            title_is_article_copy = is_article_title_copy(title, article_titles)
            if not is_usable_topic_title(title) or title_is_article_copy:
                anchor_title = format_topic_title_candidate(
                    str(group.get("topic_anchor_pl") or ""),
                    title,
                )
                title = fallback_topic_title(
                    "",
                    anchor_title,
                    article_titles,
                )
            topic_id = existing_topic_id or stable_topic_id(ids, title)
            topic_action = str(group.get("topic_action") or ("DEVELOPMENT" if group.get("existing_topic_id") else "NEW_TOPIC")).strip()
            if topic_action not in {"NEW_TOPIC", "DEVELOPMENT", "BACKGROUND_OR_CONTEXT"}:
                topic_action = "DEVELOPMENT" if group.get("existing_topic_id") else "NEW_TOPIC"
            existing_ids = topic_links.get(topic_id, [])
            all_ids = list(dict.fromkeys(existing_ids + ids))
            link_rows.extend({"topic_id": topic_id, "article_id": article_id, "confidence": confidence} for article_id in ids)
            assignment_rows.extend({
                "run_id": run_id, "article_id": article_id, "topic_id": topic_id,
                "confidence": confidence, "needs_review": needs_review,
                "grouping_reason": str(group.get("grouping_reason") or "")[:1000],
                "prompt_version": PROMPT_VERSION,
            } for article_id in ids)

            existing_group = group_data_by_topic.get(topic_id)
            if existing_group is None:
                group_data_by_topic[topic_id] = {
                    "topic_id": topic_id,
                    "title": title,
                    "categories": normalize_topic_categories(
                        group.get("categories") or group.get("category")
                    ),
                    "all_ids": all_ids,
                    "new_ids": ids,
                    "needs_review": needs_review,
                    "topic_action": topic_action,
                }
            else:
                # The model can occasionally return two groups pointing to the
                # same existing topic. PostgreSQL rejects duplicate constrained
                # values in one upsert command, so coalesce them before writing.
                duplicate_topic_ids.add(topic_id)
                existing_group["all_ids"] = list(dict.fromkeys(existing_group["all_ids"] + ids))
                existing_group["new_ids"] = list(dict.fromkeys(existing_group["new_ids"] + ids))
                incoming_categories = normalize_topic_categories(
                    group.get("categories") or group.get("category")
                )
                if incoming_categories:
                    existing_group["categories"] = incoming_categories
                existing_group["needs_review"] = existing_group["needs_review"] or needs_review
                if topic_action == "DEVELOPMENT" or existing_group["topic_action"] == "DEVELOPMENT":
                    existing_group["topic_action"] = "DEVELOPMENT"
                elif topic_action == "BACKGROUND_OR_CONTEXT":
                    existing_group["topic_action"] = "BACKGROUND_OR_CONTEXT"

        # Never discard a core article merely because the model was uncertain
        # or returned an incoherent group. Keep it as a hidden singleton topic;
        # a later article from another source can still attach to it.
        remaining_ids = [
            article_id for article_id in input_by_id
            if article_id not in excluded_ids and article_id not in assigned_ids
        ]
        for article_id in remaining_ids:
            row = input_by_id[article_id]
            title = fallback_topic_title("", "", [str(row.get("title") or "")])
            topic_id = stable_topic_id([article_id], title)
            assigned_ids.add(article_id)
            link_rows.append({"topic_id": topic_id, "article_id": article_id, "confidence": 1.0})
            assignment_rows.append({
                "run_id": run_id,
                "article_id": article_id,
                "topic_id": topic_id,
                "confidence": 0.0,
                "needs_review": True,
                "grouping_reason": (
                    "Artykuł zachowany osobno: grupa nie przeszła kontroli spójności."
                    if article_id in quality_gate_singletons
                    else "Artykuł zachowany osobno: AI nie przypisało go pewnie do wspólnego wydarzenia."
                ),
                "prompt_version": PROMPT_VERSION,
            })
            group_data_by_topic[topic_id] = {
                "topic_id": topic_id,
                "title": title,
                "categories": [],
                "all_ids": [article_id],
                "new_ids": [article_id],
                "needs_review": True,
                "topic_action": "NEW_TOPIC",
            }

        group_data = list(group_data_by_topic.values())
        if duplicate_topic_ids:
            log(
                "AI",
                f"Grupowanie: połączono powtarzające się wskazania do "
                f"{len(duplicate_topic_ids)} tematów przed zapisem.",
            )

        topic_rows: list[dict[str, Any]] = []
        for group in group_data:
            topic_id = group["topic_id"]
            all_ids = group["all_ids"]
            all_rows = local_articles(conn, all_ids)
            source_ids = distinct_source_keys(all_rows)
            if len(all_ids) == 1:
                coverage_status = "SINGLE_ARTICLE"
            elif len(source_ids) == 1:
                coverage_status = "SINGLE_SOURCE"
            else:
                coverage_status = "MULTI_SOURCE"
            existing_context = topic_context.get(topic_id, {})
            topic_rows.append({
                "topic_id": topic_id, "headline_pl": group["title"], "status": "ACTIVE",
                "first_seen_at": existing_context.get("first_seen_at") or now(),
                "last_seen_at": now(), "article_count": len(all_ids),
                "source_count": len(source_ids), "coverage_status": coverage_status,
                "needs_review": group["needs_review"], "updated_at": now(),
            })

        client.upsert("topics", topic_rows, on_conflict="topic_id")
        for group in group_data:
            categories = normalize_topic_categories(group.get("categories"))
            if categories:
                persist_topic_categories(client, group["topic_id"], categories)
        unique_link_rows = list({
            (row["topic_id"], row["article_id"]): row for row in link_rows
        }.values())
        unique_assignment_rows = list({
            (row["run_id"], row["article_id"]): row for row in assignment_rows
        }.values())
        removed_links = len(link_rows) - len(unique_link_rows)
        removed_assignments = len(assignment_rows) - len(unique_assignment_rows)
        if removed_links or removed_assignments:
            log(
                "AI",
                f"Grupowanie: usunięto powtórne przypisania przed zapisem "
                f"(linki {removed_links}, przypisania {removed_assignments}).",
                level="WARN",
            )
        client.upsert("topic_articles", unique_link_rows, on_conflict="topic_id,article_id")
        client.upsert("article_topic_assignments", unique_assignment_rows, on_conflict="run_id,article_id")
        stats["groups"] = len(group_data)

        if not summarize:
            return stats

        for group in group_data:
            topic_id = group["topic_id"]
            title = group["title"]
            all_ids = group["all_ids"]
            new_rows = local_articles(conn, group["new_ids"])
            all_rows = local_articles(conn, all_ids)
            if not new_rows or not all_rows:
                continue
            if (
                len(distinct_source_keys(all_rows)) < 2
                or not has_independent_source(all_rows)
            ):
                stats["skipped_single_source"] += 1
                continue
            old = client.select("topic_summaries", filters=[("topic_id", f"eq.{topic_id}")], limit=1)
            previous_aggregation = previous_aggregation_context(old[0].get("summary")) if old else None
            summary_input_base = {
                "topic": {
                    "topic_id": topic_id,
                    "working_title_pl": title,
                    "topic_action": group["topic_action"],
                    "categories": group.get("categories", []),
                },
                "previous_aggregation": previous_aggregation,
                "all_article_ids_in_topic": all_ids,
            }
            summary_input, payload_chars, payload_mode = build_bounded_summary_input(
                summary_input_base,
                new_rows,
                all_rows if previous_aggregation is None else None,
            )
            log(
                "AI",
                f"Synteza: {short_text(title)} "
                f"({len(new_rows)} nowych, {len(all_rows)} łącznie; {payload_mode}).",
            )
            summary_hash = digest(summary_input)
            if old and old[0].get("input_hash") == summary_hash:
                stats["skipped_summaries"] += 1
                continue
            summary_topic_run_id = "topicrun_" + digest({"topic": topic_id, "stage": "SUMMARY", "input": summary_hash})[:24]
            try:
                summary = normalize_summary_response(call_openai(
                    SUMMARY_INSTRUCTIONS,
                    summary_input,
                    model,
                    timeout_seconds=SUMMARY_REQUEST_TIMEOUT_SECONDS,
                    response_schema=SUMMARY_RESPONSE_SCHEMA,
                    response_schema_name="topic_summary",
                ))
                persist_summary(
                    client,
                    topic_id=topic_id,
                    run_id=run_id,
                    model=model,
                    summary=summary,
                    summary_hash=summary_hash,
                    previous_row=old[0] if old else None,
                    new_article_ids=group["new_ids"],
                )
                client.upsert("topic_runs", [{
                    "topic_run_id": summary_topic_run_id, "run_id": run_id,
                    "stage": "SUMMARY", "prompt_version": PROMPT_VERSION,
                    "model": model, "input_hash": summary_hash, "status": "COMPLETED",
                    "raw_output": response_for_storage(summary), "error": None,
                }], on_conflict="topic_run_id")
                stats["summaries"] += 1
            except Exception as exc:
                log_parse_failure("SUMMARY", exc)
                client.upsert("topic_runs", [{
                    "topic_run_id": summary_topic_run_id, "run_id": run_id,
                    "stage": "SUMMARY", "prompt_version": PROMPT_VERSION,
                    "model": model, "input_hash": summary_hash, "status": "FAILED",
                    "raw_output": parse_failure_for_storage(exc), "error": str(exc)[:2000],
                }], on_conflict="topic_run_id")
                stats["failed_summaries"] += 1
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
    merge_existing_summaries_mode: bool = False,
    merge_existing_max_topics: int = 0,
) -> dict[str, int]:
    """Run the three-stage pipeline: label, merge, then synthesize.

    ``max_articles=0`` means all pending articles. Stage 1 creates one
    independently named candidate per article. Stage 2 is the only stage that
    decides whether candidates describe the same story.
    """
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        raise RuntimeError("Brakuje OPENAI_API_KEY; AI nie może zostać uruchomiona.")
    if merge_existing_summaries_mode:
        log(
            "AI-REPAIR",
            "Tryb naprawczy istniejących syntez: analizuję wyłącznie aktywne "
            f"wątki z ostatnich {TOPIC_MATCH_LOOKBACK_HOURS} godzin, które mają już syntezę.",
        )
        stats = merge_existing_summaries(
            db_path,
            run_id,
            client,
            model=model,
            max_topics=merge_existing_max_topics,
        )
        log("AI-REPAIR", "Tryb naprawczy istniejących syntez zakończony.")
        return stats
    requested_batch_size = max(1, batch_size)
    batch_size = min(requested_batch_size, MAX_LABEL_BATCH_SIZE)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        articles = pending_articles(conn, client, max_articles)
    finally:
        conn.close()

    stats = {
        "pending_articles": len(articles), "groups": 0,
        "labeled_articles": 0, "candidate_topics": 0, "label_needs_review": 0,
        "summaries": 0, "skipped_summaries": 0,
        "skipped_single_source": 0, "failed_summaries": 0, "excluded": 0,
        "merge_candidates": 0, "topics_merged": 0, "merge_failed": 0,
        "local_candidate_groups": 0, "local_candidate_topics": 0,
        "largest_candidate_group": 0, "merge_requests": 0,
        "titles_normalized": 0, "categories_classified": 0,
    }
    if articles:
        total_batches = (len(articles) + batch_size - 1) // batch_size
        log(
            "AI",
            f"Etap 1/3 — nadaję nazwy kandydatom: artykułów: {len(articles)}, "
            f"paczek: {total_batches}, maks. w paczce: {batch_size}, "
            f"wyciąg: {LABEL_EXCERPT_WORDS} słów, model: {LABEL_MODEL}, "
            f"timeout: {LABEL_REQUEST_TIMEOUT_SECONDS:.0f} s, "
            f"próby: {LABEL_MAX_RETRIES}. "
            "Grupowanie nastąpi w etapie 2.",
        )

        def merge_batch_stats(batch_stats: dict[str, int]) -> None:
            for key in (
                "labeled_articles", "candidate_topics", "label_needs_review",
            ):
                stats[key] += batch_stats[key]

        def process_batch(batch: list[dict[str, Any]], label: str) -> None:
            log(
                "AI",
                f"Nazwy {label}/{total_batches}: artykułów w paczce: {len(batch)}.",
            )
            try:
                batch_stats = _label_pending_batch(
                    run_id, client, batch, model=LABEL_MODEL, batch_index=label,
                )
                merge_batch_stats(batch_stats)
                log(
                    "AI",
                    f"Nazwy {label}/{total_batches} zakończone: "
                    f"nadano {batch_stats['labeled_articles']} nazw, "
                    f"utworzono {batch_stats['candidate_topics']} kandydatów, "
                    f"do kontroli: {batch_stats['label_needs_review']}.",
                )
            except ValueError as exc:
                if len(batch) <= MIN_LABEL_RETRY_BATCH_SIZE:
                    raise
                midpoint = len(batch) // 2
                log(
                    "AI",
                    f"Nazwy {label}: dzielę paczkę po niepoprawnym JSON na "
                    f"{midpoint} + {len(batch) - midpoint} artykułów.",
                    level="WARN",
                )
                process_batch(batch[:midpoint], f"{label}a")
                process_batch(batch[midpoint:], f"{label}b")
            except Exception as exc:
                if not is_retryable_openai_error(exc) or len(batch) <= MIN_LABEL_RETRY_BATCH_SIZE:
                    raise
                midpoint = len(batch) // 2
                log(
                    "AI",
                    f"Nazwy {label}: dzielę paczkę po błędzie OpenAI na "
                    f"{midpoint} + {len(batch) - midpoint} artykułów "
                    f"({short_text(openai_error_details(exc), 180)}).",
                    level="WARN",
                )
                process_batch(batch[:midpoint], f"{label}a")
                process_batch(batch[midpoint:], f"{label}b")

        for offset in range(0, len(articles), batch_size):
            batch_index = offset // batch_size + 1
            process_batch(articles[offset:offset + batch_size], str(batch_index))
        log(
            "AI",
            f"Etap 1/3 zakończony: nazwano {stats['labeled_articles']} artykułów, "
            f"utworzono {stats['candidate_topics']} kandydatów; "
            f"do kontroli: {stats['label_needs_review']}.",
        )
    else:
        log("AI", "Etap 1/3 pominięty: brak nowych artykułów do nazwania.")

    log("AI", "Etap 2/3 — porządkowanie tematów: scalanie, tytuły i kategorie.")
    merge_stats = merge_active_topics(db_path, run_id, client, model=model)
    stats["merge_candidates"] = merge_stats["merge_candidates"]
    stats["topics_merged"] = merge_stats["topics_merged"]
    stats["merge_failed"] = merge_stats["merge_failed"]
    stats["local_candidate_groups"] = merge_stats["local_candidate_groups"]
    stats["local_candidate_topics"] = merge_stats["local_candidate_topics"]
    stats["largest_candidate_group"] = merge_stats["largest_candidate_group"]
    stats["merge_requests"] = merge_stats["merge_requests"]
    log("AI", "Porządkowanie tematów: sprawdzam tytuły.")
    stats["titles_normalized"] = normalize_topic_titles(client, model=model)
    log("AI", "Porządkowanie tematów: uzupełniam kategorie.")
    stats["categories_classified"] = classify_topic_categories(client, model=model)
    log(
        "AI",
        "Etap 3/3 — syntezy: generuję jedną końcową syntezę lub aktualizację na temat.",
    )
    recovery_stats = retry_incomplete_summaries(db_path, run_id, client, model=model)
    stats["summaries"] += recovery_stats["summaries"]
    stats["failed_summaries"] += recovery_stats["failed_summaries"]
    log(
        "AI",
        f"Etap 3/3 zakończony: gotowe syntezy {stats['summaries']}, "
        f"nieudane {stats['failed_summaries']}.",
    )
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
    result = analyze_run(
        args.db, args.run_id, client, model=args.model,
        max_articles=args.max_articles, batch_size=args.batch_size,
    )
    log("AI", f"Wynik: {', '.join(f'{key}={value}' for key, value in result.items())}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
