"""Cheap, conservative publication checks. These do not establish truth.

Uncertain material is omitted, never repaired by inventing evidence or buying
another model response. Original publications remain available in history.
"""
import copy
import hashlib
import json
import re
import unicodedata

EXTRACTOR_VERSION = 'article-facts-v2'
FACT_EXTRACTION_VERSION = 2
INLINE_CONTEXT_VERSION = 2


def text_key(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip().casefold().rstrip('. ')


def without_publisher_prefixes(text, source_names):
    """Remove publisher labels, preserving the author of a statement/claim."""
    names = sorted({str(name).strip() for name in source_names if str(name or '').strip()}, key=len, reverse=True)
    if not names:
        return text
    alternatives = '|'.join(re.escape(name) for name in names)
    return re.sub(r'^[ \t]*Według[ \t]+(?:(?:agencji|portalu|dziennika|redakcji)[ \t]+)?(?:'
                  + alternatives + r')[ \t]*[:,][ \t]*', '', text, flags=re.I | re.M)


def tokens(text):
    text = unicodedata.normalize('NFKD', text_key(text).replace('ł', 'l'))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    stop = {'przez', 'ktory', 'ktora', 'ktore', 'tego', 'jest', 'oraz', 'jako', 'bylo',
            'jego', 'przed', 'takze', 'wedlug', 'zostal', 'zostala', 'powiedzial'}
    return {w[:6] for w in re.findall(r'[^\W\d_]{4,}', text) if w not in stop}


def usable_claim(text):
    text = str(text or '').strip()
    if not text or len(text.split()) < 2:
        return False
    if re.search(r'\?\?|\b\d{2,4}\?|\b\d+:\?|\w+/\w+\?|\b(?:brak|bez) (?:dodatkowych |nowych |istotnych )?(?:faktów|ustaleń|informacji)\b', text, re.I):
        return False
    # A detached continuation or pronoun without its subject is not a claim.
    if re.match(r'^(?:i |oraz |ale |(?:stwierdził|twierdzi|dodał|dodaje|powiedział|podkreśla|podkreślił|uważa|ocenił|zaznaczył|zapewnił)\b|on |ona |oni |to (?:oznacza|potwierdza))', text, re.I):
        return False
    return True


def related_claims(left, right):
    """Reject plainly unrelated references; semantic equivalence still needs AI."""
    a, b = tokens(left), tokens(right)
    return bool(a and b and len(a & b) >= min(2, len(a), len(b))
                and len(a & b) / min(len(a), len(b)) >= .35)


def compatible_duplicate(left, right):
    if text_key(left) == text_key(right):
        return True
    numbers = lambda s: set(re.findall(r'\d+(?:[.,:]\d+)*', s))
    # Different quantities/dates or polarity must remain separate versions.
    if numbers(left) != numbers(right):
        return False
    if bool(re.search(r'\b(?:nie|bez|zaprzeczył|zaprzecza)\b', left, re.I)) != bool(re.search(r'\b(?:nie|bez|zaprzeczył|zaprzecza)\b', right, re.I)):
        return False
    return related_claims(left, right)


def story_terms(text):
    """Short stems for headline coverage, never for merging factual claims."""
    return {word[:4] for word in tokens(re.sub(r'^\s*\[[^]]+\]\s*', '', str(text or '')))}


def primary_fact(facts, headline):
    """Find the admitted main claim most closely tied to the working title."""
    candidates = [f for f in facts if f.get('lane', 'COMMON') == 'COMMON'
                  and f.get('kind', 'FACT') in ('FACT', 'STATEMENT')
                  and usable_claim(f.get('text_pl'))]
    if not candidates:
        return None
    title = story_terms(headline)
    return max(candidates, key=lambda f: len(title & story_terms(f['text_pl'])))


def narrative_missing_core(headline, narrative, facts):
    """Detect only an obvious omission of several central headline anchors.

    This is a cheap queue/coverage guard, not proof that all details are covered.
    Two missing anchors avoid treating one inflected name or a short headline
    as evidence that another writing request is needed.
    """
    primary = primary_fact(facts, headline)
    if not primary:
        return False
    anchors = story_terms(headline) & story_terms(primary['text_pl'])
    missing = anchors - story_terms(narrative)
    return len(anchors) >= 2 and len(missing) >= 2 and len(missing) / len(anchors) >= .5


def needs_inline_context(current, facts=()):
    """One writing attempt for opaque acronyms or a contextless fact fallback.

    The v1 writer marked even its bare-fact fallback as context-complete. Only
    its recognizable output is eligible again, not every older publication.
    """
    if (current.get('publication_version') != 2
            or (current.get('inline_context_version') or 0) >= INLINE_CONTEXT_VERSION):
        return False
    if (current.get('inline_context_version') or 0) >= 1:
        if current.get('narrative_context') or not facts:
            return False
        paragraphs = [p.strip() for p in current.get('summary_pl', '').split('\n\n') if p.strip()]
        claims = {text_key(f.get('text_pl')) for f in facts}
        return (len(paragraphs) >= 2 and any(p.startswith('Według ') for p in paragraphs)
                and all(text_key(re.sub(r'^Według [^:\n]{1,100}:\s*', '', p)) in claims
                        for p in paragraphs))
    common = {'USA', 'US', 'UE', 'EU', 'UK', 'RP', 'ONZ', 'NATO', 'MSZ', 'MSW',
              'BBC', 'CBS', 'CNN', 'NBC', 'ABC', 'PAP', 'AFP', 'EFE', 'FAZ', 'WSJ', 'TVN', 'RT'}
    acronyms = set(re.findall(r'\b[A-Z][A-Z0-9]{2,}\b', current.get('summary_pl', ''))) - common
    text = current.get('summary_pl', '')
    acronyms = {name for name in acronyms if not re.search(
        rf'\b{re.escape(name)}\s*(?:\(|[—–:])|\([^()]*\b{re.escape(name)}\b[^()]*\)', text)}
    return len(acronyms) >= 2


def needs_fact_rebuild(stored):
    """One new-protocol attempt for a wholly empty, quote-rejected publication."""
    current = stored.get('current_summary') or stored.get('base_summary') or {}
    state = stored.get('perspective_state') or current
    if (current.get('publication_version') != 2 or current.get('summary_pl')
            or (current.get('coverage_mode') or state.get('coverage_mode')) == 'STATE_ONLY'
            or state.get('perspective_facts') or state.get('facts')
            or (current.get('fact_extraction_version') or 0) >= FACT_EXTRACTION_VERSION):
        return False
    quality = current.get('quality_report') or state.get('quality_report') or {}
    return any(row.get('discarded_fact_count', 0) and any(
        'dosłownego fragmentu' in reason for reason in row.get('discard_reasons', []))
        for row in quality.get('omissions', []) if isinstance(row, dict))


def cache_key(article, model, topic_id=''):
    body = {k: article.get(k) for k in ('article_id', 'title_original', 'body_original', 'source_id', 'source_profile', 'source_type')}
    # Selection is event-specific: an omission for one topic must not suppress
    # useful information when the same article is assigned to another topic.
    return hashlib.sha256(json.dumps([EXTRACTOR_VERSION, model, topic_id, body], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def merge_publications(canonical, others):
    """Union publication ledgers without turning a technical merge into news.

    Keep originals and update IDs. Repeating an interrupted merge is idempotent.
    The next summary pass refreshes the narrative once from the merged ledger.
    """
    result = copy.deepcopy(canonical)
    base = result.get('base_summary') or result
    if base.get('perspective_version') != 1:
        return result
    facts, updates, processed, archives, hashes = {}, {}, set(), {}, {}
    sources = [('', canonical), *others]
    by_text = {}
    for tid, stored in sources:
        old_base = stored.get('base_summary') or stored
        state = stored.get('perspective_state') or old_base
        for raw in state.get('perspective_facts') or []:
            if not usable_claim(raw.get('text_pl')):
                continue
            key = (text_key(raw['text_pl']), raw.get('kind'))
            fid = by_text.setdefault(key, raw['fact_id'])
            existing = facts.setdefault(fid, {**copy.deepcopy(raw), 'fact_id': fid})
            existing['article_ids'] = list(dict.fromkeys([*existing.get('article_ids', []), *raw.get('article_ids', [])]))
            existing['evidence'] = {**existing.get('evidence', {}), **raw.get('evidence', {})}
        for update in stored.get('updates') or []:
            uid = update.get('update_id') or hashlib.sha256(json.dumps(update, sort_keys=True).encode()).hexdigest()
            updates.setdefault(uid, copy.deepcopy(update))
        processed.update(stored.get('processed_article_ids') or [])
        hashes.update(stored.get('article_content_hashes') or {})
        for archive in stored.get('merged_publications') or []:
            archives[archive['topic_id']] = copy.deepcopy(archive)
        if tid:
            archives[tid] = {'topic_id': tid, 'base_summary': copy.deepcopy(old_base),
                             'first_published_at': stored.get('first_published_at')}
    result['perspective_state'] = {**(result.get('perspective_state') or base), 'perspective_facts': list(facts.values())}
    result['updates'] = sorted(updates.values(), key=lambda u: (u.get('generated_at', ''), u.get('update_id', '')))
    result['latest_update'] = result['updates'][-1] if result['updates'] else result.get('latest_update', {})
    result['processed_article_ids'] = sorted(processed)
    result['article_content_hashes'] = hashes
    result['merged_publications'] = list(archives.values())
    result['needs_narrative_refresh'] = True
    return result
