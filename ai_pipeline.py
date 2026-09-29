#!/usr/bin/env python3
"""Two-stage OpenAI processing for the harvested articles.

The worker deliberately stores model output as JSON and keeps article_ids next
to claims. This makes the UI able to show the evidence instead of presenting a
citation-free model narrative.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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

from supabase_client import SupabaseRestClient


PROMPT_VERSION = "ai-prompts-v27-collapsed-topic-components"
TOPIC_LOOKBACK_HOURS = 55
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
    10, int(os.environ.get("AI_TOPIC_MERGE_MAX_TOPICS_PER_REQUEST", "60"))
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
TOPIC_MERGE_MAX_OUTPUT_TOKENS = max(
    1000, int(os.environ.get("AI_TOPIC_MERGE_MAX_OUTPUT_TOKENS", "12000"))
)
TOPIC_MERGE_MAX_REQUESTS = max(
    1, int(os.environ.get("AI_TOPIC_MERGE_MAX_REQUESTS", "80"))
)
DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
GROUPING_EXCERPT_WORDS = max(20, int(os.environ.get("AI_GROUPING_EXCERPT_WORDS", "130")))
MIN_ARTICLE_WORDS = 100
MAX_GROUPING_BATCH_SIZE = 50
MIN_GROUPING_RETRY_BATCH_SIZE = 25
GROUPING_MIN_CONFIDENCE = float(os.environ.get("AI_GROUPING_MIN_CONFIDENCE", "0.70"))
OPENAI_MAX_RETRIES = max(2, int(os.environ.get("OPENAI_MAX_RETRIES", "4")))
OPENAI_RETRY_BASE_SECONDS = max(
    0.5, float(os.environ.get("OPENAI_RETRY_BASE_SECONDS", "2"))
)
OPENAI_REQUEST_TIMEOUT_SECONDS = max(
    15.0, float(os.environ.get("OPENAI_REQUEST_TIMEOUT_SECONDS", "90"))
)
AI_BREAK_TAG_RE = re.compile(r"<\s*/?\s*br\s*/?\s*>", re.IGNORECASE)

TITLE_PREFIX_RE = re.compile(r"^\[([^\]\r\n]{2,80})\]\s+(\S.*)$")
PLACEHOLDER_TOPIC_TITLES = {
    "neutralna nazwa wydarzenia",
    "neutralny wspólny tytuł",
    "temat bez tytułu",
    "połączony temat",
    "konkretny tytuł",
    "konkretny tytuł wydarzenia",
}

TOPIC_CATEGORY_VALUES = (
    "POLITYKA",
    "SWIAT",
    "GOSPODARKA",
    "SPOLECZENSTWO",
    "TECHNOLOGIA",
    "ZDROWIE",
    "KULTURA_SPORT",
)

TOPIC_CATEGORY_ALIASES = {
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


def _merge_token_forms(value: str) -> set[str]:
    base = _merge_token_base(value)
    if len(base) < 4 or base in MERGE_NON_DISTINCTIVE_TOKENS:
        return set()
    forms = {base}
    # Catch simple Polish inflections of names/objects, e.g. Trump/Trumpa,
    # without stemming every common word in the headline.
    if len(base) >= 6:
        forms.add(base[:5])
    return forms


def _topic_merge_features(topic: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return informative tokens and likely named-entity tokens for a topic."""
    fields = [
        str(topic.get("headline_pl") or ""),
        str(topic.get("what_happened_one_sentence_pl") or ""),
        *(str(title) for title in (topic.get("recent_article_titles") or [])),
    ]
    text = " ".join(fields)
    tokens: set[str] = set()
    entities: set[str] = set()
    for match in MERGE_WORD_RE.finditer(text):
        raw = match.group(0)
        forms = _merge_token_forms(raw)
        tokens.update(forms)
        if raw[0].isupper():
            entities.update(forms)
    return tokens, entities


def _topic_merge_candidate_edges(
    topics: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str], float], dict[str, set[str]]]:
    """Find local topic pairs with enough rare lexical/entity overlap."""
    features = {
        str(topic["topic_id"]): _topic_merge_features(topic)
        for topic in topics
    }
    token_postings: dict[str, list[str]] = defaultdict(list)
    entity_postings: dict[str, list[str]] = defaultdict(list)
    for topic_id, (tokens, entities) in features.items():
        for token in tokens:
            token_postings[token].append(topic_id)
        for token in entities:
            entity_postings[token].append(topic_id)

    topic_count = len(topics)
    max_common_token_frequency = max(8, min(25, topic_count // 5 or 1))
    max_entity_frequency = max(6, min(20, topic_count // 10 or 1))
    shared_tokens: dict[tuple[str, str], set[str]] = defaultdict(set)
    for token, topic_ids in token_postings.items():
        unique_ids = sorted(set(topic_ids))
        if len(unique_ids) > max_common_token_frequency:
            continue
        for left, right in combinations(unique_ids, 2):
            shared_tokens[(left, right)].add(token)

    entity_tokens = set(entity_postings)
    edges: dict[tuple[str, str], float] = {}
    neighbors: dict[str, set[str]] = defaultdict(set)
    for pair, overlap in shared_tokens.items():
        rare_entities = {
            token for token in overlap
            if token in entity_tokens
            and len(set(entity_postings[token])) <= max_entity_frequency
        }
        if len(overlap) < 2 and not rare_entities:
            continue
        score = float(len(overlap)) + 0.5 * len(rare_entities)
        edges[pair] = score
        left, right = pair
        neighbors[left].add(right)
        neighbors[right].add(left)
    return edges, neighbors


def build_topic_merge_candidate_groups(
    topics: list[dict[str, Any]],
    *,
    max_topics_per_group: int = TOPIC_MERGE_MAX_TOPICS_PER_REQUEST,
) -> list[list[str]]:
    """Build candidate topic groups before asking the model to merge them."""
    if len(topics) < 2:
        return []
    edges, _neighbors = _topic_merge_candidate_edges(topics)
    if not edges:
        return []

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
        if len(component) <= max_topics_per_group:
            groups.append(sorted(component))
            continue

        # A connected component is one logical candidate group. Do not turn a
        # large component into one neighborhood per topic: that creates many
        # overlapping groups and repeats the same topic in many AI requests.
        # The request builder keeps this component together and only packs
        # separate components into one request.
        groups.append(sorted(component))
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
    if candidate_group_id:
        record["candidate_group_id"] = candidate_group_id
    return record


def build_topic_merge_requests(
    topics: list[dict[str, Any]],
    *,
    max_topics_per_request: int = TOPIC_MERGE_MAX_TOPICS_PER_REQUEST,
    candidate_groups: list[list[str]] | None = None,
) -> list[list[dict[str, Any]]]:
    """Pack logical candidate components into AI requests without overlap."""
    topic_by_id = {str(topic["topic_id"]): topic for topic in topics}
    groups = merge_overlapping_candidate_groups(
        candidate_groups
        if candidate_groups is not None
        else build_topic_merge_candidate_groups(
            topics,
            max_topics_per_group=max_topics_per_request,
        )
    )
    requests: list[list[dict[str, Any]]] = []
    current_records: dict[str, dict[str, Any]] = {}
    for group_index, group in enumerate(groups, start=1):
        group_ids = list(dict.fromkeys(group))
        if len(group_ids) > max_topics_per_request:
            if current_records:
                requests.append(list(current_records.values()))
                current_records = {}
            candidate_group_id = f"local_{group_index}"
            requests.append([
                compact_topic_merge_record(
                    topic_by_id[topic_id],
                    candidate_group_id=candidate_group_id,
                )
                for topic_id in group_ids
            ])
            continue
        merged_ids = list(dict.fromkeys([*current_records, *group_ids]))
        if current_records and len(merged_ids) > max_topics_per_request:
            requests.append(list(current_records.values()))
            current_records = {}
        candidate_group_id = f"local_{group_index}"
        for topic_id in group_ids:
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
sport, celebryci, rozrywka, lifestyle, przepisy, zwykłe treści konsumenckie i
inne materiały bez znaczenia dla polityki, gospodarki, bezpieczeństwa,
dyplomacji, konfliktów, prawa publicznego lub istotnych wydarzeń społecznych.
Jeżeli związek jest niepewny, nie odrzucaj materiału — zostaw go w grupie lub
unassigned_article_ids i ustaw needs_review.

Treść artykułu w tym etapie jest tylko krótkim wyciągiem pierwszych około 130
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
"category":"SPORT|CELEBRITY|ENTERTAINMENT|LIFESTYLE|OTHER_NON_CORE",
"reason":"krótkie uzasadnienie"}],"possible_merges":[]}

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
Każdy working_title_pl musi zaczynać się od jednego spójnego prefiksu
geograficznego w nawiasach kwadratowych: `[Polska]`, `[Niemcy]`,
`[USA i Iran]` albo `[Świat]`. Używaj polskich nazw państw. Dla jednego kraju
podaj jeden kraj; dla dwóch lub trzech bezpośrednio zaangażowanych państw
połącz nazwy przez „i” (przy trzech: przecinek oraz „i”); dla spraw naprawdę
globalnych albo obejmujących wiele państw użyj `[Świat]`. Używaj
`[Wielka Brytania]`, chyba że wydarzenie dotyczy konkretnie tylko Anglii.
Nie wpisuj w prefiksie miasta, kontynentu ani ogólnika typu `[Zagranica]`.
grouping_reason ma być krótkie i nie przekraczać około 160 znaków.
Nigdy nie wpisuj tekstu przykładowego „neutralna nazwa wydarzenia”, „Temat bez
tytułu” ani żadnego innego placeholdera. Każda grupa musi mieć konkretny tytuł
wynikający z przekazanych artykułów.

categories wybierz jako jedną lub maksymalnie trzy wartości z listy: POLITYKA,
SWIAT, GOSPODARKA, SPOLECZENSTWO, TECHNOLOGIA, ZDROWIE albo KULTURA_SPORT.
To główna tematyka wydarzenia, a nie ocena źródeł ani prefiks geograficzny
tytułu. SWIAT oznacza przede wszystkim międzynarodowe relacje, geopolitykę lub
wydarzenia globalne; nie przypisuj do niej automatycznie każdej historii spoza
Polski. Dodaj więcej niż jedną kategorię tylko wtedy, gdy każda z nich wnosi
istotny wymiar tematu, a nie jako luźne skojarzenie.
""".strip()

TOPIC_MERGE_INSTRUCTIONS = """
Jesteś modułem porządkowania tematów w aplikacji Global News Intelligence.
Otrzymujesz grupy kandydatów wyłonione wcześniej lokalnie na podstawie
wspólnych charakterystycznych słów, aktorów lub obiektów. Twoim celem jest
potwierdzić, które z tych tematów opisują tę samą konkretną historię, nawet
jeśli wcześniejsze grupowanie rozdzieliło je na różne tematy. Porównuj tylko
tematy przekazane w bieżącym żądaniu; brak tematu w żądaniu nie oznacza, że
jest on niepowiązany. Jeśli rekordy mają `candidate_group_id`, porównuj i
scalaj tematy tylko w obrębie tego samego identyfikatora. Nakładające się
kandydatury zostały już wcześniej połączone w jeden komponent.
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
relacje w `recent_article_titles`, a dopiero potem ogólne słowa. Krótkie
podsumowanie może być nieaktualne lub niedoskonałe; nie pozwól, aby samo
rozbieżne sformułowanie podsumowania zablokowało połączenie, gdy tytuły i
faktyczny punkt zaczepienia są zgodne.

merged_title_pl zachowuje te same zasady co working_title_pl: ma być konkretnym,
informacyjnym i ciekawym tytułem w jednolitym stylu prasowym, bez clickbaitu,
krzykliwych ocen i ogólników.
Musi także zaczynać się od prefiksu geograficznego według zasad:
`[Polska]`, `[Niemcy]`, `[USA i Iran]` albo `[Świat]`; używaj polskich nazw
państw i `[Świat]` dla wydarzeń obejmujących wiele krajów.

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
 jako scalone. categories wybierz z dokładnie tej samej listy siedmiu kategorii
co w module grupowania. Zwróć jedną lub maksymalnie trzy kategorie, ale dodaj
więcej niż jedną wyłącznie wtedy, gdy każda opisuje istotny wymiar wspólnej
historii.
Nie opisuj tematów, których nie łączysz. Jeśli w tej paczce nie ma pewnego
połączenia, zwróć dokładnie `{"merge_groups":[]}`.
""".strip()

TITLE_NORMALIZATION_INSTRUCTIONS = """
Ujednolić tytuły tematów wiadomości. Nie zmieniaj znaczenia ani nie dodawaj
faktów. Każdy title_pl musi zaczynać się od prefiksu geograficznego:
`[Polska]`, `[Niemcy]`, `[USA i Iran]` albo `[Świat]`. Używaj polskich nazw
państw. Dla jednego kraju podaj jeden kraj; dla dwóch lub trzech bezpośrednio
zaangażowanych państw połącz nazwy przez „i” (przy trzech użyj przecinka i
„i”); dla spraw globalnych lub obejmujących wiele państw użyj `[Świat]`.
Używaj `[Wielka Brytania]`, chyba że sprawa dotyczy wyłącznie Anglii.
Po prefiksie zachowaj konkretny, prasowy tytuł bez clickbaitu.
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
samym krajem opisanym w tytule.

Dozwolone kategorie:
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
""".strip()

SUMMARY_INSTRUCTIONS = """
Jesteś redaktorem analitycznym aplikacji Global News Intelligence. Przygotuj
neutralne polskie opracowanie jednego tematu wyłącznie na podstawie
dostarczonych artykułów. Każde istotne twierdzenie musi mieć article_ids.
Identyfikatory są techniczne: aplikacja ma prezentować czytelnikowi
odpowiadające im nazwy źródeł, a nie surowe numery lub identyfikatory.
Pokaż osobno fakty zgodne, informacje jednostkowe, różnice i sprzeczności.
Nie rozstrzygaj, które źródło ma rację. Profil lewicowe/prawicowe/centralne
służy wyłącznie do pokazania sposobu przedstawienia tematu.

Nie nazywaj artykułu kłamliwym. Możesz wskazać konkretny sygnał wymagający
sprawdzenia: wartościujący język, brak kontekstu, nagłówek mocniejszy niż
treść, niezweryfikowane twierdzenie albo konflikt z innym materiałem. Nie
wymyślaj cytatów ani informacji spoza artykułów. Kontekst ogólny wpisz tylko
do background_context i oznacz needs_verification=true.

summary_pl ma być właściwą, rzeczową syntezą faktów, a nie opisem tego, o czym
piszą artykuły. Nie zaczynaj od sformułowań typu „artykuły opisują”, „źródła
przedstawiają” ani „materiały dotyczą”. Zacznij od tego, co się wydarzyło.
Stosuj krótkie akapity: każdy powinien rozwijać jeden etap wydarzenia albo
jedną grupę faktów. Akapity oddzielaj pustą linią (`\\n\\n`). Możesz używać
wyłącznie ograniczonego Markdown: `**pogrubienie**` dla nazwisk, instytucji,
liczb lub najważniejszych decyzji. Nie używaj HTML, nagłówków Markdown,
list, tabel, emotikonów ani innych znaczników formatowania.
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

Nie powtarzaj tej samej informacji w kilku zdaniach ani w kilku sekcjach.
summary_pl ma być pełnym głównym opisem wydarzenia, natomiast facts, agreement,
differences, framing_and_tone, potential_manipulation_signals,
background_context i unknowns mogą zawierać wyłącznie informacje dodatkowe,
które nie zostały już jasno przedstawione w summary_pl. Nie przepisuj do
agreement oczywistych faktów z syntezy i nie twórz sekcji tylko po to, żeby ją
wypełnić. Każda sekcja może pozostać pusta.

differences ma wskazywać konkretną różnicę, a nie ogólnik typu „źródła różnie
przedstawiają temat”. W każdym wpisie nazwij wymiar różnicy, na przykład
liczbę, kolejność wydarzeń, zakres skutków, przypisywaną odpowiedzialność albo
ocenę znaczenia. Jeśli różnica nie ma znaczenia dla zrozumienia sprawy, pomiń
ją.

framing_and_tone ma pokazywać konkretny wybór redakcyjny: inny dobór faktów,
akcent, określenie wartościujące, sposób opisania aktora albo różnicę między
nagłówkiem a treścią. Nie opisuj tonu słowami „neutralny”, „emocjonalny” lub
„stronniczy” bez wskazania, co dokładnie w tekście na to wskazuje.

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
summary_pl, facts, agreement, differences, framing_and_tone,
potential_manipulation_signals ani background_context — program
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
Nie powtarzaj jednak faktów już zawartych w previous_aggregation.
Nie powtarzaj także informacji obecnych w żadnym elemencie prior_updates.

Jeżeli nowe materiały potwierdzają wcześniejszy fakt, napisz konkretnie, jaki
fakt został ponownie potwierdzony i jakie nowe szczegóły dodano. Nie zastępuj
tego zdaniem, że materiały „tylko powtarzają wcześniejsze informacje”.
Jeśli materiał nie zawiera nowych danych możliwych do rzetelnego wykorzystania,
nie twórz pustej oceny jego przydatności: wybierz z niego konkretne fakty, a
gdy rzeczywiście nie ma żadnego faktu do dodania, pozostaw krótką aktualizację
opartą na tym, co można potwierdzić, bez komentowania dopasowania materiału.
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

Każdy element tablic facts, agreement, differences, framing_and_tone,
potential_manipulation_signals, contradictions i unknowns powinien zawierać
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
contradictions zwykłych różnic akcentów.

framing_and_tone opisuje sposób przedstawienia tematu, a nie prawdziwość
artykułu. Każdy wpis powinien wskazywać konkretny element tekstu, na przykład
język wartościujący, selekcję faktów, mocniejszy nagłówek albo odmienny
akcent.

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
- każdy nowy article_id musi zostać wykorzystany przez konkretny fakt w
  update.new_information_pl albo w dodatkowym elemencie update, jeśli taki
  element istnieje w schemacie;
- nie pisz metakomentarza o tym, czy materiał pasuje do grupy;
- nie dodawaj do update faktów obecnych już w previous_aggregation lub
  prior_updates.

Każdy artykuł z wejścia musi pojawić się w sources. Jeżeli nie wnosi nowej
informacji, nie opisuj tego jako wady grupowania ani nie pokazuj takiej oceny
czytelnikowi. W `sources.description_pl` napisz krótko, jaki fakt lub aspekt
artykuł potwierdza, rozwija albo dokumentuje. Nie wpisuj tam technicznych
identyfikatorów.

topic.categories musi zawierać jedną, dwie albo maksymalnie trzy kategorie z
listy POLITYKA, SWIAT, GOSPODARKA, SPOLECZENSTWO, TECHNOLOGIA, ZDROWIE,
KULTURA_SPORT. Zwracaj pełny aktualny zestaw kategorii także w trybie
aktualizacji. Nie dodawaj kategorii tylko na podstawie kraju lub profilu
źródła; każda kategoria musi wynikać z głównego tematu albo jego istotnego
wymiaru. Jeśli wątek łączy np. politykę i zdrowie publiczne, zwróć obie.

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
"framing_and_tone":[{"text_pl":"","article_ids":[]}],
"potential_manipulation_signals":[{"text_pl":"","article_ids":[]}],
"contradictions":[{"text_pl":"","article_ids":[]}],
"background_context":[{"text_pl":"","article_ids":[],"needs_verification":true}],
"unknowns":[{"text_pl":"","article_ids":[]}],
"sources":[{"source_name":"","description_pl":"","article_ids":[]}],
"quality":{"article_count":0,"source_count":0,
"has_multiple_perspectives":false,"overall_confidence":"MEDIUM",
"limitations_pl":""}}

topic.headline_pl musi zaczynać się od identycznego, spójnego prefiksu
geograficznego jak tytuł roboczy: np. `[Polska]`, `[Niemcy]`,
`[Wielka Brytania i USA]`, `[USA i Iran]` lub `[Świat]`. Po prefiksie umieść
konkretny tytuł wydarzenia. Stosuj polskie nazwy państw; `[Świat]` tylko dla
spraw globalnych lub obejmujących wiele krajów.

W elementach tablic używaj dokładnie nazw pól pokazanych powyżej. Nie używaj
zamienników typu agreement_pl, point_pl, difference_pl, tone, signal, reason,
context, notes ani event. Nie dodawaj innych pól. article_ids to techniczna
lista identyfikatorów dowodowych i nie należy wstawiać jej do tekstu
text_pl. Jeśli element nie ma oparcia w konkretnym artykule, zostaw
article_ids jako [] i ustaw needs_verification=true tam, gdzie to pole istnieje.
""".strip()

REBUILD_SUMMARY_INSTRUCTIONS = SUMMARY_INSTRUCTIONS + """

TRYB PEŁNEJ PRZEBUDOWY: previous_aggregation będzie zawsze null. Opracuj
pełną, nową syntezę bazową na podstawie wszystkich artykułów w all_articles.
Nie traktuj tego jako aktualizacji i nie pisz delta-update. Ustaw
update.is_update=false, pozostaw update.new_information_pl i
update.what_changed_pl puste oraz update.new_article_ids jako pustą listę.
Nie pomijaj ważnych faktów tylko dlatego, że występują w wielu artykułach —
połącz je w jeden klarowny opis, a powtórzenia wykorzystaj do oceny zgodności.
""".strip()

SUMMARY_UPDATE_REPAIR_INSTRUCTIONS = SUMMARY_INSTRUCTIONS + """

TRYB NAPRAWY AKTUALIZACJI: poprzednia odpowiedź nie spełniła wymogu
faktograficznej aktualizacji. Wygeneruj ponownie pełny JSON z tym samym
wejściem. W `update.new_information_pl` nie opisuj artykułu, procesu
grupowania ani tego, czy materiał pasuje do tematu. Nie używaj zdań o tym, że
artykuł jest „nie na temat”, „nic nie wnosi”, „nie zmienia narracji” albo nie
zawiera informacji o głównym wątku. Zamiast tego wybierz z każdego nowego
materiału konkretne, sprawdzalne fakty: osoby, liczby, daty, wyniki, działania,
stanowiska i skutki. Zaczynaj od faktu, np. „Dwa badania wykazały…”, a nazwę
źródła dodaj tylko wtedy, gdy pomaga rozróżnić relacje. Nie umieszczaj
technicznych article_id w żadnym tekście.
""".strip()

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
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
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
    "framing_and_tone",
    "potential_manipulation_signals",
    "contradictions",
    "background_context",
    "reader_context",
    "unknowns",
    "sources",
)

SUMMARY_TEXT_ALIASES = {
    "facts": ("text_pl", "fact_pl", "fact", "claim", "description_pl", "description"),
    "agreement": ("text_pl", "agreement_pl", "agreement", "point_pl", "point", "claim"),
    "differences": ("text_pl", "differences_pl", "difference_pl", "difference", "point_pl", "point"),
    "framing_and_tone": ("text_pl", "framing_pl", "frame", "tone_pl", "tone", "description_pl", "description"),
    "potential_manipulation_signals": ("text_pl", "signal_pl", "signal", "reason", "description_pl", "description"),
    "contradictions": ("text_pl", "contradiction_pl", "contradiction", "difference_pl", "difference", "reason"),
    "background_context": ("text_pl", "context_pl", "context", "reason", "description_pl", "description", "notes_pl", "notes"),
    "unknowns": ("text_pl", "unknown_pl", "unknown", "reason", "description_pl", "description", "notes_pl", "notes"),
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
    notes = _first_text(item, ("notes_pl", "notes"))
    if field == "framing_and_tone" and text and notes and notes != text:
        text = f"{text} {notes}"
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
    preview = exc.raw_output[:5000]
    suffix = "\n...[ucięto w logu; pełna odpowiedź jest w topic_runs.raw_output]" if len(exc.raw_output) > 5000 else ""
    print(f"[AI] Niepoprawny JSON na etapie {stage}: {exc}\n[AI] Surowa odpowiedź AI:\n{preview}{suffix}", flush=True)


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


def wait_before_openai_retry(attempt: int, exc: Exception) -> None:
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
    print(
        f"[AI] Chwilowy błąd OpenAI ({openai_error_details(exc)}); "
        f"ponawiam za {delay:.1f}s ({attempt + 1}/{OPENAI_MAX_RETRIES}).",
        flush=True,
    )
    time.sleep(delay)


def call_openai(
    instructions: str,
    payload: dict[str, Any],
    model: str,
    *,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(
        api_key=openai_api_key(),
        timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
    last_error: Exception | None = None
    parse_failures = 0
    for attempt in range(OPENAI_MAX_RETRIES):
        input_text = (
            json.dumps(payload, ensure_ascii=False)
            + "\n\nReturn only valid JSON. Do not add any commentary outside the JSON object."
        )
        if parse_failures:
            input_text += (
                "\nThe previous attempt was empty or invalid. Return the requested "
                "JSON object now, even when there are no matches."
            )
        try:
            request = {
                "model": model,
                "instructions": instructions,
                "input": input_text,
                "text": {"format": {"type": "json_object"}},
            }
            if max_output_tokens is not None:
                request["max_output_tokens"] = max_output_tokens
            response = client.responses.create(**request)
        except Exception as exc:
            if not is_retryable_openai_error(exc):
                raise
            last_error = exc
            if attempt + 1 >= OPENAI_MAX_RETRIES:
                raise
            wait_before_openai_retry(attempt, exc)
            continue
        try:
            return ParsedAIResponse(extract_json(response.output_text), response.output_text)
        except ValueError as exc:
            last_error = exc
            parse_failures += 1
            if parse_failures >= 2:
                raise
            print(
                f"[AI] Niepoprawny JSON z OpenAI; ponawiam próbę ({parse_failures}/2): {exc}",
                flush=True,
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


def active_topic_payload(
    client: SupabaseRestClient,
    *,
    excluded_topic_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, dict[str, Any]]]:
    excluded = excluded_topic_ids or set()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=TOPIC_LOOKBACK_HOURS)).isoformat()
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


def merge_active_topics(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
) -> dict[str, int]:
    """Merge duplicate active topics before any final summary is generated."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=TOPIC_LOOKBACK_HOURS)).isoformat()
    topics = client.select_all(
        "topics",
        columns=(
            "topic_id,headline_pl,status,first_seen_at,last_seen_at,"
            "article_count,source_count,coverage_status,needs_review"
        ),
        filters=[("status", "eq.ACTIVE"), ("last_seen_at", f"gte.{cutoff}")],
    )
    stats = {
        "merge_candidates": 0,
        "topics_merged": 0,
        "merge_failed": 0,
        "local_candidate_groups": 0,
        "merge_requests": 0,
    }
    if len(topics) < 2:
        return stats

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        links = client.select_all("topic_articles", columns="topic_id,article_id")
        summaries = client.select_all("topic_summaries", columns="topic_id,summary")
        summary_by_topic = {
            str(row["topic_id"]): stored_base_summary(row.get("summary"))
            for row in summaries
        }
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
            payload_topics.append({
                "topic_id": topic_id,
                "headline_pl": str(topic.get("headline_pl") or ""),
                "categories": categories_by_topic.get(topic_id, []),
                "what_happened_one_sentence_pl": str(
                    previous_topic.get("what_happened_one_sentence_pl") or ""
                ),
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

        candidate_groups = merge_overlapping_candidate_groups(
            build_topic_merge_candidate_groups(payload_topics)
        )
        merge_requests = build_topic_merge_requests(
            payload_topics,
            candidate_groups=candidate_groups,
        )
        stats["local_candidate_groups"] = len(candidate_groups)
        total_merge_requests = len(merge_requests)
        if total_merge_requests > TOPIC_MERGE_MAX_REQUESTS:
            print(
                f"[AI] Ograniczam scalanie z {total_merge_requests} do "
                f"{TOPIC_MERGE_MAX_REQUESTS} żądań; reszta zostaje do kolejnego uruchomienia.",
                flush=True,
            )
            merge_requests = merge_requests[:TOPIC_MERGE_MAX_REQUESTS]
        stats["merge_requests"] = len(merge_requests)
        print(
            f"[AI] Lokalna selekcja scalania: {len(payload_topics)} tematów -> "
            f"{stats['local_candidate_groups']} grup kandydackich -> "
            f"{len(merge_requests)} małych żądań do AI "
            f"(limit {TOPIC_MERGE_MAX_REQUESTS}).",
            flush=True,
        )
        if not merge_requests:
            return stats

        raw_groups: list[dict[str, Any]] = []
        for request_index, request_topics in enumerate(merge_requests, start=1):
            started_at = time.monotonic()
            print(
                f"[AI] Scalanie: żądanie {request_index}/{len(merge_requests)} "
                f"({len(request_topics)} tematów)...",
                flush=True,
            )
            merge_input = {
                "active_topics": request_topics,
                "topic_memory_window_hours": TOPIC_LOOKBACK_HOURS,
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
                    raw_groups.extend(
                        group for group in batch_groups if isinstance(group, dict)
                    )
                print(
                    f"[AI] Scalanie: żądanie {request_index}/{len(merge_requests)} "
                    f"zakończone ({len(batch_groups or [])} grup, "
                    f"{time.monotonic() - started_at:.1f}s).",
                    flush=True,
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
                print(
                    f"[AI] Scalanie: żądanie {request_index}/{len(merge_requests)} "
                    f"nieudane po {time.monotonic() - started_at:.1f}s; "
                    "przechodzę dalej.",
                    flush=True,
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
            if not is_usable_topic_title(title):
                title = fallback_topic_title(
                    title,
                    "",
                    [
                        str(row.get("title") or "")
                        for row in article_rows
                    ] + [
                        str(topic_by_id[topic_id].get("headline_pl") or "")
                        for topic_id in group_ids
                    ],
                )
            canonical_id = stable_merged_topic_id(group_ids)
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
            if merged_categories:
                persist_topic_categories(client, canonical_id, merged_categories)
            client.upsert("topic_articles", [
                {"topic_id": canonical_id, "article_id": article_id, "confidence": confidence}
                for article_id in article_ids
            ], on_conflict="topic_id,article_id")

            for old_topic_id in group_ids:
                client.update(
                    "article_topic_assignments",
                    {"topic_id": canonical_id},
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
                    print(
                        f"[AI] Nie zapisano merged_into_topic_id dla {old_topic_id}; "
                        f"uruchom supabase_migration_topic_merges.sql. ({exc})",
                        flush=True,
                    )
                    client.update(
                        "topics",
                        {"status": "MERGED", "updated_at": now()},
                        filters=[("topic_id", f"eq.{old_topic_id}")],
                    )
            stats["topics_merged"] += len(group_ids)
            print(
                f"[AI] Scalono tematy {', '.join(group_ids)} → {canonical_id} "
                f"(confidence={confidence:.2f}).",
                flush=True,
            )
        return stats
    finally:
        conn.close()


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
    article_titles = {
        str(row["article_id"]): str(row.get("title") or "").strip()
        for row in client.select_all("articles", columns="article_id,title")
    }
    titles_by_topic = {
        topic_id: [article_titles[article_id] for article_id in article_ids if article_titles.get(article_id)]
        for topic_id, article_ids in links_by_topic.items()
    }
    missing = [row for row in topics if not is_usable_topic_title(row.get("headline_pl"))]
    changed = 0
    for offset in range(0, len(missing), 100):
        batch = missing[offset:offset + 100]
        payload = {"topics": [{
            "topic_id": row["topic_id"],
            "current_title_pl": row.get("headline_pl") or "",
            "one_sentence_pl": (
                (summaries.get(str(row["topic_id"]), {}).get("topic") or {})
                .get("what_happened_one_sentence_pl", "")
            ),
            "article_titles": titles_by_topic.get(str(row["topic_id"]), [])[:5],
        } for row in batch]}
        result = call_openai(TITLE_NORMALIZATION_INSTRUCTIONS, payload, model)
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
            if not is_usable_topic_title(title):
                continue
            candidate_titles[topic_id] = title

        for row in batch:
            topic_id = str(row["topic_id"])
            title = candidate_titles.get(topic_id)
            if not title:
                summary = summaries.get(topic_id, {})
                topic_summary = summary.get("topic") if isinstance(summary.get("topic"), dict) else {}
                title = fallback_topic_title(
                    row.get("headline_pl"),
                    topic_summary.get("what_happened_one_sentence_pl", ""),
                    titles_by_topic.get(topic_id, []),
                )
            client.update(
                "topics",
                {"headline_pl": title, "updated_at": now()},
                filters=[("topic_id", f"eq.{topic_id}")],
            )
            changed += 1

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
    return changed


def classify_topic_categories(
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
    batch_size: int = 80,
) -> int:
    """Fill missing topic categories without overwriting reviewed categories."""
    topics = client.select_all(
        "topics",
        columns="topic_id,headline_pl,status",
        filters=[("status", "neq.MERGED")],
    )
    existing_rows = client.select_all("topic_categories", columns="topic_id,category")
    existing_categories: dict[str, list[str]] = {}
    for row in existing_rows:
        category = normalize_topic_category(row.get("category"))
        if category:
            existing_categories.setdefault(str(row["topic_id"]), []).append(category)
    missing = [
        row for row in topics
        if not existing_categories.get(str(row["topic_id"]))
    ]
    if not missing:
        return 0

    summaries = {
        str(row["topic_id"]): stored_base_summary(row.get("summary"))
        for row in client.select_all("topic_summaries", columns="topic_id,summary")
    }
    links = client.select_all("topic_articles", columns="topic_id,article_id")
    article_ids_by_topic: dict[str, list[str]] = {}
    for row in links:
        article_ids_by_topic.setdefault(str(row["topic_id"]), []).append(str(row["article_id"]))
    article_titles = {
        str(row["article_id"]): str(row.get("title") or "")
        for row in client.select_all("articles", columns="article_id,title")
    }

    classified = 0
    for offset in range(0, len(missing), max(1, batch_size)):
        batch = missing[offset:offset + max(1, batch_size)]
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
                ),
                "recent_article_titles": titles[:5],
            })

        result = call_openai(CATEGORY_INSTRUCTIONS, {"topics": payload_topics}, model)
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
        print(
            f"[AI] Nie zapisano historii wersji tematu {topic_id}; "
            f"uruchom supabase_migration_topic_updates.sql. ({exc})",
            flush=True,
        )
    return version


def persist_rebuilt_summary(
    client: SupabaseRestClient,
    *,
    topic_id: str,
    run_id: str,
    model: str,
    summary: dict[str, Any],
    summary_hash: str,
    previous_row: dict[str, Any] | None,
) -> int:
    """Replace the current base summary while retaining the previous version."""
    persist_topic_categories(
        client,
        topic_id,
        (summary.get("topic") or {}).get("categories")
        if isinstance(summary.get("topic"), dict)
        else [],
    )
    version = int((previous_row or {}).get("version", 0)) + 1
    timestamp = now()
    base_summary = dict(summary)
    base_summary["update"] = empty_update()
    stored_summary = {
        "base_summary": base_summary,
        "updates": [],
        "latest_update": empty_update(),
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
        # If the history migration was not run before the rebuild, preserve the
        # summary that was live immediately before the replacement.
        if previous_row:
            client.upsert("topic_summary_versions", [{
                "topic_id": topic_id,
                "version": int(previous_row.get("version", 0)),
                "run_id": None,
                "model": previous_row.get("model") or model,
                "prompt_version": "BEFORE_REBUILD",
                "summary": previous_row.get("summary") or {},
                "new_article_ids": [],
                "generated_at": previous_row.get("generated_at") or timestamp,
            }], on_conflict="topic_id,version")
        client.upsert("topic_summary_versions", [{
            "topic_id": topic_id,
            "version": version,
            "run_id": run_id,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "summary": stored_summary,
            "new_article_ids": [],
            "generated_at": timestamp,
        }], on_conflict="topic_id,version")
    except Exception as exc:
        print(
            f"[AI] Nie zapisano historii przebudowy tematu {topic_id}; "
            f"uruchom supabase_migration_topic_updates.sql. ({exc})",
            flush=True,
        )
    return version


def retry_incomplete_summaries(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
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

        for topic in topics:
            topic_id = str(topic.get("topic_id") or "")
            all_ids = list(dict.fromkeys(ids_by_topic.get(topic_id, [])))
            if not topic_id or len(all_ids) < 2:
                continue
            previous_row = summary_by_topic.get(topic_id)
            previous_updated_at = str((previous_row or {}).get("updated_at") or "")
            latest_assignment = latest_assignment_by_topic.get(topic_id, "")
            if previous_row and latest_assignment <= previous_updated_at:
                continue
            new_ids = [
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
            if len(distinct_source_keys(all_rows)) < 2:
                continue
            previous_aggregation = previous_aggregation_context(previous_row.get("summary")) if previous_row else None
            summary_input = {
                "topic": {
                    "topic_id": topic_id,
                    "working_title_pl": str(topic.get("headline_pl") or ""),
                    "topic_action": "DEVELOPMENT" if previous_aggregation else "NEW_TOPIC",
                },
                "previous_aggregation": previous_aggregation,
                "new_articles": [article_for_ai(row) for row in new_rows],
                "all_article_ids_in_topic": all_ids,
            }
            if previous_aggregation is None:
                summary_input["all_articles"] = [article_for_ai(row) for row in all_rows]
            summary_hash = digest(summary_input)
            summary_topic_run_id = "topicrun_" + digest({
                "topic": topic_id, "stage": "SUMMARY", "input": summary_hash,
            })[:24]
            try:
                summary = normalize_summary_response(call_openai(SUMMARY_INSTRUCTIONS, summary_input, model))
                if previous_aggregation and update_needs_repair(summary):
                    print(
                        f"[AI] Ponawiam aktualizację tematu {topic_id}: "
                        "odpowiedź zawierała metakomentarz zamiast faktów.",
                        flush=True,
                    )
                    summary = normalize_summary_response(
                        call_openai(SUMMARY_UPDATE_REPAIR_INSTRUCTIONS, summary_input, model)
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


def rebuild_summaries(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
    max_topics: int = 0,
) -> dict[str, int]:
    """Regenerate every multi-article topic without harvesting or regrouping."""
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        raise RuntimeError("Brakuje OPENAI_API_KEY; AI nie może zostać uruchomiona.")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        topics = client.select_all(
            "topics",
            columns="topic_id,headline_pl,status,article_count,source_count,last_seen_at",
        )
        links = client.select_all("topic_articles", columns="topic_id,article_id")
        summaries = client.select_all(
            "topic_summaries",
            columns="topic_id,summary,input_hash,version,model,generated_at,updated_at",
        )
        summary_by_topic = {str(row["topic_id"]): row for row in summaries}
        ids_by_topic: dict[str, list[str]] = {}
        for row in links:
            ids_by_topic.setdefault(str(row["topic_id"]), []).append(str(row["article_id"]))

        eligible: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for topic in topics:
            topic_id = str(topic.get("topic_id") or "")
            if not topic_id:
                continue
            article_ids = list(dict.fromkeys(ids_by_topic.get(topic_id, [])))
            rows = [
                row for row in local_articles(conn, article_ids)
                if row.get("content_status") in {"COMPLETE", "EXCERPT"}
                and int(row.get("word_count") or 0) >= MIN_ARTICLE_WORDS
            ]
            if len(distinct_source_keys(rows)) >= 2:
                rows.sort(key=lambda row: (str(row.get("published_at") or ""), str(row["article_id"])))
                eligible.append((topic, rows))

        eligible.sort(
            key=lambda item: (
                str(item[0].get("last_seen_at") or ""),
                str(item[0].get("topic_id") or ""),
            ),
            reverse=True,
        )
        eligible_count = len(eligible)
        if max_topics > 0:
            eligible = eligible[:max_topics]

        stats = {
            "topics_considered": len(topics),
            "topics_eligible": eligible_count,
            "topics_selected": len(eligible),
            "topics_rebuilt": 0,
            "topics_not_selected": len(topics) - len(eligible),
            "failed_summaries": 0,
        }
        total = len(eligible)
        for index, (topic, rows) in enumerate(eligible, start=1):
            topic_id = str(topic["topic_id"])
            article_ids = [str(row["article_id"]) for row in rows]
            print(
                f"[AI-REBUILD] Temat {index}/{total}: "
                f"{str(topic.get('headline_pl') or topic_id)[:120]} "
                f"({len(rows)} artykułów)...",
                flush=True,
            )
            summary_input = {
                "mode": "FULL_REBUILD",
                "topic": {
                    "topic_id": topic_id,
                    "working_title_pl": str(topic.get("headline_pl") or ""),
                    "topic_action": "REBUILD",
                },
                "previous_aggregation": None,
                "new_articles": [],
                "all_articles": [article_for_ai(row) for row in rows],
                "all_article_ids_in_topic": article_ids,
            }
            summary_hash = digest({
                "mode": "FULL_REBUILD",
                "prompt_version": PROMPT_VERSION,
                "input": summary_input,
            })
            previous_row = summary_by_topic.get(topic_id)
            summary_topic_run_id = "topicrun_" + digest({
                "topic": topic_id,
                "stage": "REBUILD_SUMMARY",
                "input": summary_hash,
            })[:24]
            try:
                summary = normalize_summary_response(
                    call_openai(REBUILD_SUMMARY_INSTRUCTIONS, summary_input, model)
                )
                persist_rebuilt_summary(
                    client,
                    topic_id=topic_id,
                    run_id=run_id,
                    model=model,
                    summary=summary,
                    summary_hash=summary_hash,
                    previous_row=previous_row,
                )
                client.upsert("topic_runs", [{
                    "topic_run_id": summary_topic_run_id,
                    "run_id": run_id,
                    "stage": "REBUILD_SUMMARY",
                    "prompt_version": PROMPT_VERSION,
                    "model": model,
                    "input_hash": summary_hash,
                    "status": "COMPLETED",
                    "raw_output": response_for_storage(summary),
                    "error": None,
                }], on_conflict="topic_run_id")
                stats["topics_rebuilt"] += 1
            except Exception as exc:
                log_parse_failure("REBUILD_SUMMARY", exc)
                client.upsert("topic_runs", [{
                    "topic_run_id": summary_topic_run_id,
                    "run_id": run_id,
                    "stage": "REBUILD_SUMMARY",
                    "prompt_version": PROMPT_VERSION,
                    "model": model,
                    "input_hash": summary_hash,
                    "status": "FAILED",
                    "raw_output": parse_failure_for_storage(exc),
                    "error": str(exc)[:2000],
                }], on_conflict="topic_run_id")
                stats["failed_summaries"] += 1
        return stats
    finally:
        conn.close()


def stable_topic_id(article_ids: list[str], title: str) -> str:
    return "topic_" + digest({"article_ids": sorted(article_ids), "title": title})[:24]


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
            "topic_memory_window_hours": TOPIC_LOOKBACK_HOURS,
        }
        grouping_hash = digest(grouping_input)
        grouping_topic_run_id = "topicrun_" + digest({
            "run": run_id, "stage": "GROUPING", "batch": batch_index, "input": grouping_hash,
        })[:24]
        try:
            grouping = call_openai(GROUPING_INSTRUCTIONS, grouping_input, model)
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
            print(
                "[AI] Scalono grupy wskazujące ten sam topic_id: "
                + ", ".join(sorted(duplicate_topic_ids)),
                flush=True,
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
            print(
                f"[AI] Usunięto duplikaty przed zapisem: topic_articles={removed_links}, "
                f"article_topic_assignments={removed_assignments}.",
                flush=True,
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
            if len(distinct_source_keys(all_rows)) < 2:
                stats["skipped_single_source"] += 1
                continue
            old = client.select("topic_summaries", filters=[("topic_id", f"eq.{topic_id}")], limit=1)
            previous_aggregation = previous_aggregation_context(old[0].get("summary")) if old else None
            summary_input = {
                "topic": {
                    "topic_id": topic_id,
                    "working_title_pl": title,
                    "topic_action": group["topic_action"],
                    "categories": group.get("categories", []),
                },
                "previous_aggregation": previous_aggregation,
                "new_articles": [article_for_ai(row) for row in new_rows],
                "all_article_ids_in_topic": all_ids,
            }
            if previous_aggregation is None:
                summary_input["all_articles"] = [article_for_ai(row) for row in all_rows]
            summary_hash = digest(summary_input)
            if old and old[0].get("input_hash") == summary_hash:
                stats["skipped_summaries"] += 1
                continue
            summary_topic_run_id = "topicrun_" + digest({"topic": topic_id, "stage": "SUMMARY", "input": summary_hash})[:24]
            try:
                summary = normalize_summary_response(call_openai(SUMMARY_INSTRUCTIONS, summary_input, model))
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


SINGLETON_REPAIR_REASON_PREFIX = "Artykuł zachowany osobno:"


def singleton_repair_candidates(
    db_path: Path,
    client: SupabaseRestClient,
    max_articles: int,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Find only singleton topics created by the failed cohesion fallback."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        links = client.select_all("topic_articles", columns="topic_id,article_id")
        article_by_topic: dict[str, list[str]] = {}
        for row in links:
            article_by_topic.setdefault(str(row["topic_id"]), []).append(str(row["article_id"]))
        topics = {
            str(row["topic_id"]): row
            for row in client.select_all("topics", columns="topic_id,status")
        }
        assignments = client.select_all(
            "article_topic_assignments",
            columns="article_id,topic_id,grouping_reason",
        )
        old_topic_by_article: dict[str, str] = {}
        for row in assignments:
            topic_id = str(row.get("topic_id") or "")
            article_id = str(row.get("article_id") or "")
            reason = str(row.get("grouping_reason") or "")
            if (
                article_id
                and topic_id
                and reason.startswith(SINGLETON_REPAIR_REASON_PREFIX)
                and topics.get(topic_id, {}).get("status") == "ACTIVE"
                and article_by_topic.get(topic_id) == [article_id]
            ):
                old_topic_by_article[article_id] = topic_id
        if max_articles > 0:
            old_topic_by_article = dict(list(old_topic_by_article.items())[:max_articles])
        rows = local_articles(conn, list(old_topic_by_article))
        rows_by_id = {str(row["article_id"]): row for row in rows}
        old_topic_by_article = {
            article_id: topic_id
            for article_id, topic_id in old_topic_by_article.items()
            if article_id in rows_by_id
        }
        return old_topic_by_article, [rows_by_id[article_id] for article_id in old_topic_by_article]
    finally:
        conn.close()


def cleanup_repaired_singletons(
    run_id: str,
    client: SupabaseRestClient,
    old_topic_by_article: dict[str, str],
) -> int:
    """Hide old singleton topics only after their article has a new assignment."""
    if not old_topic_by_article:
        return 0
    assignments = client.select_all(
        "article_topic_assignments",
        columns="article_id,topic_id",
        filters=[("run_id", f"eq.{run_id}")],
    )
    topic_status = {
        str(row.get("topic_id") or ""): str(row.get("status") or "")
        for row in client.select_all("topics", columns="topic_id,status")
    }
    new_topic_by_article = {
        str(row.get("article_id") or ""): str(row.get("topic_id") or "")
        for row in assignments
        if str(row.get("article_id") or "") in old_topic_by_article
    }
    merged = 0
    for article_id, old_topic_id in old_topic_by_article.items():
        if topic_status.get(old_topic_id) != "ACTIVE":
            continue
        new_topic_id = new_topic_by_article.get(article_id, "")
        if not new_topic_id or new_topic_id == old_topic_id:
            continue
        client.delete("topic_articles", filters=[("topic_id", f"eq.{old_topic_id}")])
        try:
            client.update(
                "topics",
                {
                    "status": "MERGED",
                    "merged_into_topic_id": new_topic_id,
                    "merged_at": now(),
                    "updated_at": now(),
                },
                filters=[("topic_id", f"eq.{old_topic_id}")],
            )
        except Exception:
            # Keep the repair compatible with databases created before the
            # optional merge redirect columns were installed.
            client.update(
                "topics",
                {"status": "MERGED", "updated_at": now()},
                filters=[("topic_id", f"eq.{old_topic_id}")],
            )
        merged += 1
    return merged


def regroup_singletons(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
    max_articles: int = 0,
    batch_size: int = 50,
) -> dict[str, int]:
    """Safely regroup singleton fallback topics without deleting source data."""
    old_topic_by_article, articles = singleton_repair_candidates(
        db_path, client, max_articles
    )
    stats = {
        "repair_candidates": len(articles),
        "repair_batches": 0,
        "groups": 0,
        "singleton_topics_merged": 0,
        "summaries": 0,
        "failed_summaries": 0,
        "merge_candidates": 0,
        "topics_merged": 0,
        "merge_failed": 0,
        "titles_normalized": 0,
    }
    if not articles:
        print("[AI-REPAIR] Nie znaleziono singletonów z fallbacku do przegrupowania.", flush=True)
        return stats

    batch_size = min(max(1, batch_size), MAX_GROUPING_BATCH_SIZE)
    excluded_topic_ids = set(old_topic_by_article.values())
    total_batches = (len(articles) + batch_size - 1) // batch_size
    print(
        f"[AI-REPAIR] Przegrupowuję {len(articles)} singletonów w {total_batches} paczkach...",
        flush=True,
    )

    def merge_batch_stats(batch_stats: dict[str, int]) -> None:
        stats["groups"] += batch_stats["groups"]

    def process_batch(batch: list[dict[str, Any]], label: str) -> None:
        print(
            f"[AI-REPAIR] Paczka {label}/{total_batches}: "
            f"{len(batch)} singletonów...",
            flush=True,
        )
        try:
            batch_stats = _analyze_pending_batch(
                db_path,
                run_id,
                client,
                batch,
                model=model,
                batch_index=f"REPAIR-{label}",
                summarize=False,
                excluded_topic_ids=excluded_topic_ids,
            )
            merge_batch_stats(batch_stats)
            merged_singletons = cleanup_repaired_singletons(
                run_id, client, old_topic_by_article
            )
            stats["singleton_topics_merged"] += merged_singletons
            print(
                f"[AI-REPAIR] Paczka {label}/{total_batches} zakończona: "
                f"grupy={batch_stats['groups']}, "
                f"singletony przeniesione={merged_singletons}.",
                flush=True,
            )
        except ValueError as exc:
            if len(batch) <= MIN_GROUPING_RETRY_BATCH_SIZE:
                raise
            midpoint = len(batch) // 2
            process_batch(batch[:midpoint], f"{label}a")
            process_batch(batch[midpoint:], f"{label}b")
        except Exception as exc:
            if not is_retryable_openai_error(exc) or len(batch) <= MIN_GROUPING_RETRY_BATCH_SIZE:
                raise
            midpoint = len(batch) // 2
            print(
                f"[AI-REPAIR] Dzielę paczkę {label} po błędzie OpenAI: "
                f"{openai_error_details(exc)}",
                flush=True,
            )
            process_batch(batch[:midpoint], f"{label}a")
            process_batch(batch[midpoint:], f"{label}b")

    for offset in range(0, len(articles), batch_size):
        stats["repair_batches"] += 1
        process_batch(articles[offset:offset + batch_size], str(stats["repair_batches"]))

    stats["singleton_topics_merged"] += cleanup_repaired_singletons(
        run_id, client, old_topic_by_article
    )
    merge_stats = merge_active_topics(db_path, run_id, client, model=model)
    stats["merge_candidates"] = merge_stats["merge_candidates"]
    stats["topics_merged"] = merge_stats["topics_merged"]
    stats["merge_failed"] = merge_stats["merge_failed"]
    stats["titles_normalized"] = normalize_topic_titles(client, model=model)
    recovery_stats = retry_incomplete_summaries(db_path, run_id, client, model=model)
    stats["summaries"] = recovery_stats["summaries"]
    stats["failed_summaries"] = recovery_stats["failed_summaries"]
    return stats


def analyze_run(
    db_path: Path,
    run_id: str,
    client: SupabaseRestClient,
    *,
    model: str = DEFAULT_MODEL,
    max_articles: int = 0,
    batch_size: int = 100,
    rebuild_summaries_mode: bool = False,
    rebuild_max_topics: int = 0,
    regroup_singletons_mode: bool = False,
) -> dict[str, int]:
    """Process the whole pending queue in context-safe AI batches.

    ``max_articles=0`` means all pending articles. Batches are deliberately
    processed in one workflow, and each next batch reloads active topics so it
    can attach follow-up articles to topics created by the previous batch.
    rebuild_summaries_mode bypasses that queue and regenerates existing
    multi-article topic summaries from their linked articles.
    """
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        raise RuntimeError("Brakuje OPENAI_API_KEY; AI nie może zostać uruchomiona.")
    if rebuild_summaries_mode:
        stats = rebuild_summaries(
            db_path,
            run_id,
            client,
            model=model,
            max_topics=rebuild_max_topics,
        )
        stats["categories_classified"] = classify_topic_categories(client, model=model)
        return stats
    if regroup_singletons_mode:
        stats = regroup_singletons(
            db_path,
            run_id,
            client,
            model=model,
            max_articles=max_articles,
            batch_size=batch_size,
        )
        stats["categories_classified"] = classify_topic_categories(client, model=model)
        return stats
    requested_batch_size = max(1, batch_size)
    batch_size = min(requested_batch_size, MAX_GROUPING_BATCH_SIZE)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        articles = pending_articles(conn, client, max_articles)
    finally:
        conn.close()

    stats = {
        "pending_articles": len(articles), "groups": 0,
        "summaries": 0, "skipped_summaries": 0,
        "skipped_single_source": 0, "failed_summaries": 0, "excluded": 0,
        "merge_candidates": 0, "topics_merged": 0, "merge_failed": 0,
        "titles_normalized": 0, "categories_classified": 0,
    }
    if articles:
        total_batches = (len(articles) + batch_size - 1) // batch_size
        print(
            f"[AI] Etap 1/3: grupowanie {len(articles)} artykułów w {total_batches} paczkach. "
            "Syntezy powstaną dopiero po przetworzeniu wszystkich paczek.",
            flush=True,
        )

        def merge_batch_stats(batch_stats: dict[str, int]) -> None:
            for key in (
                "groups", "summaries", "skipped_summaries", "skipped_single_source",
                "failed_summaries", "excluded",
            ):
                stats[key] += batch_stats[key]

        def process_batch(batch: list[dict[str, Any]], label: str) -> None:
            print(
                f"[AI] Paczka {label}/{total_batches}: {len(batch)} artykułów...",
                flush=True,
            )
            try:
                batch_stats = _analyze_pending_batch(
                    db_path, run_id, client, batch, model=model,
                    batch_index=label, summarize=False,
                )
                merge_batch_stats(batch_stats)
                print(
                    f"[AI] Paczka {label}/{total_batches} zakończona: "
                    f"grupy={batch_stats['groups']}.",
                    flush=True,
                )
            except ValueError as exc:
                if len(batch) <= MIN_GROUPING_RETRY_BATCH_SIZE:
                    raise
                midpoint = len(batch) // 2
                print(
                    f"[AI] Niepoprawny JSON dla paczki {label}; dzielę ją na "
                    f"{midpoint} + {len(batch) - midpoint} artykułów. ({exc})",
                    flush=True,
                )
                process_batch(batch[:midpoint], f"{label}a")
                process_batch(batch[midpoint:], f"{label}b")
            except Exception as exc:
                if not is_retryable_openai_error(exc) or len(batch) <= MIN_GROUPING_RETRY_BATCH_SIZE:
                    raise
                midpoint = len(batch) // 2
                print(
                    f"[AI] OpenAI nie przetworzyło paczki {label}; dzielę ją na "
                    f"{midpoint} + {len(batch) - midpoint} artykułów. "
                    f"({openai_error_details(exc)})",
                    flush=True,
                )
                process_batch(batch[:midpoint], f"{label}a")
                process_batch(batch[midpoint:], f"{label}b")

    for offset in range(0, len(articles), batch_size):
            batch_index = offset // batch_size + 1
            process_batch(articles[offset:offset + batch_size], str(batch_index))

    print("[AI] Etap 2/3: scalanie podobnych tematów z całego przebiegu...", flush=True)
    merge_stats = merge_active_topics(db_path, run_id, client, model=model)
    stats["merge_candidates"] = merge_stats["merge_candidates"]
    stats["topics_merged"] = merge_stats["topics_merged"]
    stats["merge_failed"] = merge_stats["merge_failed"]
    print("[AI] Ujednolicam prefiksy geograficzne tytułów...", flush=True)
    stats["titles_normalized"] = normalize_topic_titles(client, model=model)
    print("[AI] Uzupełniam kategorie tematów...", flush=True)
    stats["categories_classified"] = classify_topic_categories(client, model=model)
    print(
        "[AI] Etap 3/3: jedna końcowa synteza lub aktualizacja na temat za cały przebieg...",
        flush=True,
    )
    recovery_stats = retry_incomplete_summaries(db_path, run_id, client, model=model)
    stats["summaries"] += recovery_stats["summaries"]
    stats["failed_summaries"] += recovery_stats["failed_summaries"]
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the two OpenAI analysis stages for pending articles.")
    parser.add_argument("--db", type=Path, default=Path("article_harvest/articles.sqlite3"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-articles", type=int, default=int(os.environ.get("AI_MAX_ARTICLES_PER_RUN", "0")))
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("AI_BATCH_SIZE", "100")))
    parser.add_argument(
        "--rebuild-summaries",
        action="store_true",
        help="Przepisz syntezy istniejących tematów z przypiętych artykułów; nie grupuj nowych artykułów.",
    )
    parser.add_argument(
        "--rebuild-max-topics",
        type=int,
        default=int(os.environ.get("AI_REBUILD_MAX_TOPICS", "0")),
        help="Maksymalna liczba tematów w przebudowie; 0 oznacza wszystkie.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    client = SupabaseRestClient()
    print(json.dumps(analyze_run(
        args.db, args.run_id, client, model=args.model,
        max_articles=args.max_articles, batch_size=args.batch_size,
        rebuild_summaries_mode=args.rebuild_summaries,
        rebuild_max_topics=args.rebuild_max_topics,
    ), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
