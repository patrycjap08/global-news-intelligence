"""Opt-in-by-format editorial perspectives; legacy summaries stay untouched.

No database migration or classification changes. Fact routing is deterministic
from cited article profiles; prose can cite only facts admitted to the main lane.
"""
from __future__ import annotations
import hashlib
import json
import re
from typing import Any

LANES = ('COMMON', 'LEFT', 'RIGHT', 'STATE')
FORMAT_VERSION = 1


def article_group(row: dict) -> str:
    profile = str(row.get('source_profile') or '').upper()
    kind = str(row.get('source_type') or '').upper()
    if profile in {'STATE_ALIGNED', 'STATE_MEDIA'} or kind == 'STATE_MEDIA':
        return 'STATE'
    if profile in {'LEFT', 'CENTER_LEFT'}:
        return 'LEFT'
    if profile in {'RIGHT', 'CENTER_RIGHT'}:
        return 'RIGHT'
    if profile == 'CENTER':
        return 'CENTER'
    raise ValueError(f"Źródło {row.get('source_name') or row.get('source_id')} nie ma zatwierdzonego profilu.")


def coverage_mode(groups: set[str]) -> str:
    independent = groups - {'STATE'}
    if not independent:
        return 'STATE_ONLY'
    if len(independent) == 1:
        return 'SINGLE_' + next(iter(independent))
    return 'MIXED'


def fact_lane(groups: set[str], mode: str) -> str:
    independent = groups - {'STATE'}
    if not independent:
        return 'STATE'
    if 'CENTER' in independent or {'LEFT', 'RIGHT'} <= independent:
        return 'COMMON'
    if mode.startswith('SINGLE_'):
        return 'COMMON'
    return 'LEFT' if 'LEFT' in independent else 'RIGHT'


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


STRING = {'type': 'string'}
STRINGS = {'type': 'array', 'items': STRING}
FACT_SCHEMA = obj({'known_fact_id': STRING, 'text_pl': STRING, 'article_ids': STRINGS, 'why_new_pl': STRING})
EXTRACTION_SCHEMA = obj({'headline_pl': STRING, 'categories': STRINGS, 'facts': {'type': 'array', 'items': FACT_SCHEMA}})
WRITING_SCHEMA = obj({
    'paragraphs': {'type': 'array', 'items': obj({'text_pl': STRING, 'fact_ids': STRINGS})},
    'general_context': obj({'text_pl': STRING, 'article_ids': STRINGS, 'needs_verification': {'type': 'boolean'}}),
    'background_context': {'type': 'array', 'items': obj({
        'entity_type': {'type': 'string', 'enum': ['PERSON', 'ORGANIZATION', 'BACKGROUND']},
        'text_pl': STRING, 'article_ids': STRINGS, 'needs_verification': {'type': 'boolean'},
    })},
})

EXTRACTION_INSTRUCTIONS = '''
Przygotuj atomowe ustalenia o jednym wydarzeniu, wyłącznie z all_articles.
Wszystko pisz poprawną polszczyzną, bez angielskich wtrąceń i bez cyrylicy
(w nazwach używaj polskich nazw lub transkrypcji). Tytuł krótki: [Kraj] wydarzenie.
Dostajesz source_group każdego artykułu: LEFT, RIGHT, CENTER, STATE.
Dla każdego konkretnego ustalenia wypisz WSZYSTKIE article_ids, które naprawdę
podają to samo ustalenie. Wspólny temat artykułów nie oznacza wspólnych szczegółów.
Nie dopowiadaj liczb, przyczyn, motywów ani potwierdzeń. Sprzeczne liczby lub
wersje to różne ustalenia, opisane z przypisaniem do źródła. Nie twórz metazdań
„nie ma nowych faktów”, „inne źródła milczą”, „śledztwo nadal trwa” bez nowości.
Materiały STATE przedstawiaj jako doniesienia, np. „Według agencji TASS…”.
previous_facts zawiera WSZYSTKIE wcześniej zapisane ustalenia, również ustalenia
z poprzednich paczek tego samego przetwarzania. all_articles zawiera bieżącą
paczkę pełnych artykułów. Nie powołuj się na niewysłane artykuły jako nowe potwierdzenie. Gdy artykuł
potwierdza znany fakt, zwróć jego known_fact_id oraz DOKŁADNIE dotychczasowy
text_pl i uzupełnione article_ids. Rozpoznawaj parafrazy i tłumaczenia — to nie
nowy fakt. Nie zamieniaj znanego ustalenia w nowy fakt o pustym known_fact_id.
Dla nowego faktu known_fact_id=""; przy poprzedniej syntezie why_new_pl musi
konkretnie wyjaśniać, jakiej informacji nie było w previous_facts. Dla znanego
why_new_pl="". Pusta lista facts jest poprawna, jeżeli nie ma nowych ustaleń
ani nowych materiałów potwierdzających znane. Nie usuwaj ani nie zmieniaj
wcześniejszych ustaleń. Kategorie: POLSKA, POLITYKA, SWIAT, GOSPODARKA,
SPOLECZENSTWO, TECHNOLOGIA, ZDROWIE, KULTURA_SPORT.
'''.strip()

WRITING_INSTRUCTIONS = '''
Napisz po polsku zwięzłą, spójną syntezę WYŁĄCZNIE na podstawie main_facts.
Każdy akapit musi mieć fact_ids wszystkich ustaleń, które opisuje. Nie dodawaj
żadnych faktów, liczb ani ocen spoza main_facts. Nie używaj angielskich słów
pospolitych ani cyrylicy. Zachowaj polskie nazwy i poprawne polskie transkrypcje.
Gdy main_facts jest puste, paragraphs=[] — NIE pisz „brak syntezy” ani nie
zastępuj syntezy ustaleniami z innych perspektyw. Nie komentuj traktowania centrum.
Kontekst jest osobnym, obowiązkowym uzupełnieniem: general_context wyjaśnia
ogólne tło wydarzenia, gdzie się dzieje i dlaczego ma znaczenie. Dla inwestycji
wyjaśnij m.in. położenie, co z czym łączy i czemu służy. Korzystaj z main_facts
oraz ostrożnie z wiedzy ogólnej; nie przenoś tam doniesień innych perspektyw.
Gdy main_facts jest puste, wykorzystaj tylko tytuł do neutralnego objaśnienia
geografii/pojęć; nie dodawaj twierdzeń o bieżącym wydarzeniu. Nie wymyślaj tła.
background_context: wypunktuj osoby i organizacje występujące w main_facts lub
syntezie, z krótkim objaśnieniem ich roli, chyba że zostało to już wyjaśnione.
PERSON oznacza człowieka, ORGANIZATION firmę/agencję/instytucję; Donald Trump
jest PERSON. Nie powtarzaj informacji między syntezą, faktami a kontekstem.
Wiedza ogólna bez źródła: article_ids=[], needs_verification=true.
'''.strip()


def _text_key(text):
    return re.sub(r'\s+', ' ', str(text)).strip().casefold().rstrip('. ')


def route_facts(response, articles, previous_facts, normalize):
    by_id = {str(a['article_id']): a for a in articles}
    groups = {key: article_group(a) for key, a in by_id.items()}
    mode = coverage_mode(set(groups.values()))
    known = {f['fact_id']: dict(f) for f in previous_facts}
    facts = {}
    for fid, fact in known.items():
        ids = list(dict.fromkeys(str(i) for i in fact['article_ids'] if str(i) in by_id))
        if not ids:
            raise ValueError('Brak materiałów dla wcześniej zapisanego faktu perspektyw.')
        facts[fid] = {**fact, 'article_ids': ids}
    key_to_id = {_text_key(f['text_pl']): fid for fid, f in facts.items()}
    raw_facts = response.get('facts')
    if not isinstance(raw_facts, list):
        raise ValueError('Brak listy ustaleń perspektyw.')
    for raw in raw_facts:
        text = normalize(raw.get('text_pl')).strip()
        ids = raw.get('article_ids')
        if not text or not isinstance(ids, list) or not ids or any(str(i) not in by_id for i in ids):
            raise ValueError('Fakt perspektyw nie ma treści lub poprawnych materiałów źródłowych.')
        fid = str(raw.get('known_fact_id') or '')
        if fid and (fid not in known or _text_key(text) != _text_key(known[fid]['text_pl'])):
            raise ValueError('Nieznany identyfikator lub zmieniona treść znanego faktu.')
        if not fid:
            fid = key_to_id.get(_text_key(text), '')
        if not fid:
            if known and not str(raw.get('why_new_pl') or '').strip():
                raise ValueError('Nowe ustalenie nie ma uzasadnienia nowości.')
            fid = 'fact_' + hashlib.sha256(_text_key(text).encode()).hexdigest()[:24]
        ids = list(dict.fromkeys([*facts.get(fid, {}).get('article_ids', []), *map(str, ids)]))
        facts[fid] = {'fact_id': fid, 'text_pl': known.get(fid, {}).get('text_pl', text), 'article_ids': ids}
        key_to_id[_text_key(text)] = fid
    for fact in facts.values():
        fact['lane'] = fact_lane({groups[i] for i in fact['article_ids']}, mode)
    return mode, list(facts.values())


def make_update(facts, previous_facts, is_update, new_ids):
    previous = {f['fact_id']: f for f in previous_facts}
    sections = {lane: [] for lane in LANES}
    promotions = []
    if is_update:
        for fact in facts:
            old = previous.get(fact['fact_id'])
            if old is None:
                sections[fact['lane']].append(fact)
            elif old['lane'] != 'COMMON' and fact['lane'] == 'COMMON':
                promotions.append(fact)
    texts = [f['text_pl'] for items in sections.values() for f in items]
    if promotions:
        texts.append('Szersze potwierdzenie: ' + ' '.join(f['text_pl'] for f in promotions))
    return {'status': ('NEW_INFORMATION' if texts else 'NO_NEW_INFORMATION') if is_update else 'BASE_SUMMARY',
            'is_update': bool(texts), 'new_information_pl': ' '.join(texts), 'what_changed_pl': '',
            'new_article_ids': new_ids, 'perspective_sections': sections, 'promoted_facts': promotions}



def take_full_article_batch(articles, start, base_payload, field, max_chars):
    """Pack whole articles, never fragments. The target is not a content cap.

    If one article/context exceeds the target, send that article intact. A
    model hard-context error fails the topic; no incomplete result is saved.
    """
    batch = []
    offset = start
    while offset < len(articles):
        candidate = [*batch, articles[offset]]
        size = len(json.dumps({**base_payload, field: candidate}, ensure_ascii=False, separators=(',', ':')))
        if batch and size > max_chars:
            break
        batch = candidate
        offset += 1
        if size > max_chars:
            break
    return batch, offset


def validate_batch_citations(response, batch, known, normalize):
    """A batch can add support only from full articles actually sent in it."""
    batch_ids = {str(a['article_id']) for a in batch}
    known_by_id = {f['fact_id']: f for f in known}
    known_by_text = {_text_key(f['text_pl']): f for f in known}
    for raw in response.get('facts') or []:
        previous = known_by_id.get(raw.get('known_fact_id')) or known_by_text.get(_text_key(normalize(raw.get('text_pl'))))
        allowed = batch_ids | set((previous or {}).get('article_ids') or [])
        if not set(raw.get('article_ids') or []) <= allowed:
            raise ValueError('Fakt cytuje artykuł spoza bieżącej paczki i znanych potwierdzeń.')

def generate(payload, call, normalize, *, max_payload_chars=300000):
    articles = payload.get('all_articles') or []
    previous = payload.get('previous_aggregation')
    previous_base = (previous or {}).get('base_summary') or {}
    known = previous_base.get('perspective_facts') or []
    if not articles:
        raise ValueError('Brak materiałów do opracowania perspektyw.')
    prepared = [{**a, 'source_group': article_group(a)} for a in articles]
    facts, offset, extracted, headline, categories = known, 0, None, None, []
    while offset < len(prepared):
        base = {'topic': payload['topic'], 'previous_facts': facts}
        batch, offset = take_full_article_batch(prepared, offset, base, 'all_articles', max_payload_chars)
        extracted = call(EXTRACTION_INSTRUCTIONS, {**base, 'all_articles': batch}, EXTRACTION_SCHEMA, 'perspective_facts')
        validate_batch_citations(extracted, batch, facts, normalize)
        mode, facts = route_facts(extracted, articles, facts, normalize)
        headline = headline or extracted['headline_pl']
        categories = list(dict.fromkeys([*categories, *(extracted.get('categories') or [])]))
    main = [f for f in facts if f['lane'] == 'COMMON']
    written = call(WRITING_INSTRUCTIONS, {'headline_pl': headline, 'main_facts': main},
                   WRITING_SCHEMA, 'perspective_summary')
    allowed = {f['fact_id'] for f in main}
    paragraphs = written.get('paragraphs')
    if not isinstance(paragraphs, list) or bool(paragraphs) != bool(main):
        raise ValueError('Synteza musi odpowiadać dostępności wspólnych ustaleń.')
    for p in paragraphs:
        if not str(p.get('text_pl') or '').strip() or not p.get('fact_ids') or not set(p['fact_ids']) <= allowed:
            raise ValueError('Akapit syntezy odwołuje się do faktów spoza wspólnej części.')
    main_article_ids = {i for f in main for i in f['article_ids']}
    contexts = [written.get('general_context') or {}, *(written.get('background_context') or [])]
    if not str(contexts[0].get('text_pl') or '').strip():
        raise ValueError('Brak ogólnego kontekstu tematu.')
    for item in contexts:
        if not set(item.get('article_ids') or []) <= main_article_ids:
            raise ValueError('Kontekst odwołuje się do materiałów spoza wspólnej części.')
    headline = normalize(headline)
    if re.search(r'[\u0400-\u052f\u2de0-\u2dff\ua640-\ua69f]', headline):
        raise ValueError('Tytuł perspektyw zawiera cyrylicę.')
    sections = {lane: [f for f in facts if f['lane'] == lane] for lane in ('LEFT', 'RIGHT', 'STATE')}
    update = make_update(facts, known, previous is not None, payload.get('new_article_ids') or [])
    return {'topic': {'headline_pl': headline, 'what_happened_one_sentence_pl': main[0]['text_pl'] if main else '',
                     'categories': categories},
            'summary_pl': '\n\n'.join(normalize(p['text_pl']) for p in paragraphs), 'facts': main,
            'general_context': written.get('general_context'), 'background_context': written.get('background_context') or [],
            'perspective_version': FORMAT_VERSION, 'coverage_mode': mode, 'shared_available': bool(main),
            'perspective_sections': sections, 'perspective_facts': facts, 'update': update}
