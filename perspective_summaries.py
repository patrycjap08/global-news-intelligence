"""Opt-in-by-format editorial perspectives; legacy summaries stay untouched.

No database migration or classification changes. Fact routing is deterministic
from cited article profiles; prose can cite only facts admitted to the main lane.
"""
from __future__ import annotations
import hashlib
import copy
import json
import re
from typing import Any

LANES = ('COMMON', 'LEFT', 'RIGHT', 'STATE')
FORMAT_VERSION = 1
STATE_FIELDS = ('perspective_version', 'coverage_mode', 'shared_available', 'perspective_sections', 'perspective_facts', 'facts')


def article_group(row: dict) -> str:
    profile = str(row.get('source_profile') or '').strip().upper()
    kind = str(row.get('source_type') or '').strip().upper()
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
COVERAGE_SCHEMA = obj({
    'no_relevant_facts_reason_pl': STRING,
})
EXTRACTION_SCHEMA = obj({
    'headline_pl': STRING, 'categories': STRINGS,
    'facts': {'type': 'array', 'items': FACT_SCHEMA},
    'article_coverage': obj({}),
})
WRITING_SCHEMA = obj({
    'paragraphs': {'type': 'array', 'items': obj({'text_pl': STRING, 'fact_ids': STRINGS})},
    'general_context': obj({'text_pl': STRING, 'article_ids': STRINGS, 'needs_verification': {'type': 'boolean'}}),
    'background_context': {'type': 'array', 'items': obj({
        'entity_type': {'type': 'string', 'enum': ['PERSON', 'ORGANIZATION', 'BACKGROUND']},
        'text_pl': STRING, 'article_ids': STRINGS, 'needs_verification': {'type': 'boolean'},
    })},
})

def allowed_strings(values):
    values = sorted(set(values))
    return {'type': 'array', 'items': {'type': 'string', 'enum': values}} if values else {
        'type': 'array', 'items': STRING, 'maxItems': 0}


def extraction_schema(known, article_ids=()):
    """First extraction cannot invent known IDs; confirmations never rewrite text."""
    schema = copy.deepcopy(EXTRACTION_SCHEMA)
    new_fact = copy.deepcopy(FACT_SCHEMA)
    new_fact['properties']['known_fact_id'] = {'type': 'string', 'enum': ['']}
    items = new_fact
    if known:
        confirmation = copy.deepcopy(FACT_SCHEMA)
        confirmation['properties']['known_fact_id'] = {'type': 'string', 'enum': sorted({f['fact_id'] for f in known})}
        confirmation['properties']['text_pl'] = {'type': 'string', 'enum': ['']}
        confirmation['properties']['why_new_pl'] = {'type': 'string', 'enum': ['']}
        items = {'anyOf': [new_fact, confirmation]}
    schema['properties']['facts']['items'] = items
    schema['properties']['article_coverage'] = obj({str(aid): copy.deepcopy(COVERAGE_SCHEMA) for aid in article_ids})
    return schema


def writing_schema(main):
    schema = copy.deepcopy(WRITING_SCHEMA)
    article_ids = {i for f in main for i in f['article_ids']}
    schema['properties']['paragraphs']['items']['properties']['fact_ids'] = allowed_strings(f['fact_id'] for f in main)
    if not main:
        schema['properties']['paragraphs']['maxItems'] = 0
    schema['properties']['general_context']['properties']['article_ids'] = allowed_strings(article_ids)
    schema['properties']['background_context']['items']['properties']['article_ids'] = allowed_strings(article_ids)
    return schema


EXTRACTION_INSTRUCTIONS = '''
Zbuduj kompletny rejestr istotnych, atomowych ustaleń o jednym wydarzeniu,
wyłącznie z pełnych tekstów all_articles. To ekstrakcja faktów, NIE streszczenie.
Wszystko pisz poprawną polszczyzną, bez angielskich wtrąceń i bez cyrylicy
(w nazwach używaj polskich nazw lub transkrypcji). Tytuł krótki: [Kraj] wydarzenie.
Dostajesz source_group każdego artykułu: LEFT, RIGHT, CENTER, STATE.

W jednym przebiegu wykonaj kolejno:
1. Przeczytaj KAŻDY artykuł osobno, nie tylko nagłówek i pierwszy akapit.
   Zbierz istotne informacje także z dalszych akapitów: działania i decyzje,
   uczestników, datę i miejsce, skalę i liczby, bezpośrednie okoliczności,
   podane przyczyny, skutki, reakcje i konkretne zapowiedzi dalszych działań.
   Wypowiedź/zarzut to fakt, że dana osoba coś powiedziała, nie dowód jej tezy.
   Pomijaj reklamy, nawigację, obce wydarzenia z relacji na żywo, powtórzenia
   i objaśnienia encyklopedyczne należące do kontekstu. Nie pomijaj szczegółu
   dlatego, że występuje tylko w jednej redakcji albo jednej grupie źródeł.
2. Jeden fakt = jedno samodzielnie sprawdzalne twierdzenie. Rozdziel decyzje,
   działania różnych osób oraz informację główną i dodatkowe szczegóły,
   jeśli mogą mieć inne potwierdzenia. Zachowaj konieczne określenia: kto,
   co, gdzie/kiedy, o jakiej grupie osób/liczbie mowa. Nie rozdrabniaj
   tego samego twierdzenia na parafrazy, urwane frazy i oczywiste wnioski.
   Np. „Minister złożył dymisję po zamieszkach, prezydent jej nie przyjął
   i zażądał nowych metod działania” to osobne ustalenia o złożeniu dymisji,
   odmowie jej przyjęcia i żądaniu prezydenta, każde z własnymi źródłami.
3. Połącz równoważne ustalenia z różnych języków w jeden fakt. Następnie
   sprawdź KAŻDY fakt względem KAŻDEGO artykułu w tej paczce i wypisz WSZYSTKIE
   article_ids, które rzeczywiście podają CAŁE to twierdzenie. Samo inne
   brzmienie nie wyklucza potwierdzenia; wspólny temat nie potwierdza szczegółu.
   Jeśli kilka źródeł podaje wspólny rdzeń, a tylko jedno dodatkowy szczegół,
   zapisz rdzeń osobno z wszystkimi potwierdzeniami, a szczegół osobno.
   Przykład: fakt o złożeniu dymisji nie jest „tylko lewicowy”, jeśli opisują
   go również źródła prawicowe lub centrum. O podziale decyduje później kod.
4. article_coverage to OBIEKT z obowiązkowym kluczem dla KAŻDEGO article_id
   z all_articles. Nie zwracaj listy, nie skracaj ID i nie dodawaj obcych kluczy.
   Każdy wpis ma tylko no_relevant_facts_reason_pl. Nie licz ani nie zwracaj
   indeksów/pozycji faktów — kod wyliczy pokrycie z facts[].article_ids.
   Jeśli brak ustaleń na temat wydarzenia, podaj konkretny powód w
   no_relevant_facts_reason_pl; w pozostałych przypadkach powód="".
   Przed odpowiedzią sprawdź, czy nie pominąłeś istotnych ustaleń ani źródeł.
   Nie ograniczaj liczby faktów do 1–2 ani innego odgórnego limitu. Nie ma
   minimalnej liczby: powtarzające się artykuły nie uzasadniają sztucznych faktów.

Nie dopowiadaj liczb, przyczyn, motywów ani potwierdzeń. Rozbieżne liczby lub
wersje opisuj osobno z przypisaniem do źródła oraz czasem/zakresem, jeśli są
w tekście. Sprawdź, czy np. osiem zatrzymań dotyczy jednego ataku, a dziesięć
łącznie kilku ataków, albo czy liczba wzrosła w czasie. Nie zacieraj różnicy
zakresów i nie wymyślaj chronologii. Gdy nie da się rozstrzygnąć, zaznacz
rozbieżność zamiast przedstawiać obie liczby jako pewny bilans tego samego.
Nie twórz metazdań
„nie ma nowych faktów”, „inne źródła milczą”, „śledztwo nadal trwa” bez nowości.
Materiały STATE przedstawiaj jako doniesienia, np. „Według agencji TASS…”.
previous_facts zawiera WSZYSTKIE wcześniej zapisane ustalenia, również ustalenia
z poprzednich paczek tego samego przetwarzania. all_articles zawiera bieżącą
paczkę pełnych artykułów. Nie powołuj się na niewysłane artykuły jako nowe potwierdzenie. Gdy artykuł
potwierdza znany fakt, wybierz jego known_fact_id WYŁĄCZNIE z previous_facts,
ustaw text_pl="", why_new_pl="" i podaj uzupełnione article_ids. Kod sam zachowa
oryginalną treść faktu. Nie twórz ani nie odgaduj identyfikatorów; gdy
previous_facts=[], każdy known_fact_id musi być pusty. Rozpoznawaj parafrazy i tłumaczenia — to nie
nowy fakt. Nie zamieniaj znanego ustalenia w nowy fakt o pustym known_fact_id.
Znane fakty nie są listą zamykającą ekstrakcję: szukaj także istotnych szczegółów,
których wcześniej nie zapisano. Nie przepisuj jednak starego faktu pod nowym
ID tylko po to, by go inaczej sformułować lub rozbić.
Dla nowego faktu known_fact_id=""; przy poprzedniej syntezie why_new_pl musi
konkretnie wyjaśniać, jakiej informacji nie było w previous_facts. Dla znanego
why_new_pl="". Także wcześniej przetworzony artykuł może ponownie potwierdzać
znany fakt: zwróć ten fakt z known_fact_id, nie nazywaj go nową informacją.
Pusta lista facts jest poprawna tylko gdy żaden artykuł bieżącej paczki nie
zawiera istotnego nowego ANI znanego ustalenia o wydarzeniu. Nie usuwaj ani nie zmieniaj
wcześniejszych ustaleń. Kategorie: POLSKA, POLITYKA, SWIAT, GOSPODARKA,
SPOLECZENSTWO, TECHNOLOGIA, ZDROWIE, KULTURA_SPORT.
'''.strip()

WRITING_INSTRUCTIONS = '''
Napisz po polsku pełną, spójną syntezę w formie ARTYKUŁU INFORMACYJNEGO,
WYŁĄCZNIE na podstawie WSZYSTKICH ustaleń z main_facts. Uwzględnij każde
ustalenie: nie wybieraj tylko 1–2 najważniejszych i nie pomijaj pozostałych
dla zwięzłości. Długość tekstu ma wynikać z ilości informacji. main_facts
zawiera wyłącznie fakty dopuszczone do wspólnej części; pozostałych perspektyw
nie wolno dołączać do głównej syntezy.

Napisz ciągły tekst redakcyjny: zacznij od sedna wydarzenia, potem logicznie
połącz szczegóły, działania, okoliczności, potwierdzone następstwa i reakcje.
Relacje przyczynowe i chronologię opisuj tylko wtedy, gdy wynikają z faktów.
Synteza NIE jest listą ustaleń: bez wypunktowań, numeracji, myślników przed
zdaniami, nagłówka „Fakty” ani mechanicznego przepisywania jednego faktu po
drugim. Grupuj powiązane ustalenia i pisz płynne, naturalne zdania.

AKAPITY SĄ OBOWIĄZKOWĄ STRUKTURĄ ARTYKUŁU. Każdy element paragraphs ma być
jednym logicznym akapitem rozwijającym jedną część opowieści, zwykle kilkoma
powiązanymi zdaniami, jeśli materiał na to pozwala. Przy kilku odrębnych
ustaleniach utwórz co najmniej dwa akapity. Nie zwracaj całego artykułu jako
jednego bloku i nie twórz osobnego akapitu dla każdego pojedynczego faktu.
Przy tylko jednym ustaleniu nie dopisuj treści ani powtórzeń dla sztucznego
wydłużenia. Kod rozdziela elementy paragraphs pustą linią.

Każdy akapit musi mieć fact_ids wszystkich ustaleń, które opisuje. Nie dodawaj
żadnych faktów, liczb ani ocen spoza main_facts. Nie używaj angielskich słów
pospolitych ani cyrylicy. Zachowaj polskie nazwy i poprawne polskie transkrypcje.
main_sources mapuje cytowane article_ids na nazwy redakcji i daty publikacji.
W general_context i background_context article_ids mogą zawierać WYŁĄCZNIE
identyfikatory artykułów z main_sources.article_id. Nie wpisuj tam fact_id,
nazw redakcji ani wymyślonych ID. Jeżeli objaśnienie wynika z wiedzy ogólnej,
zwróć article_ids=[] i needs_verification=true. Gdy main_sources=[], wszystkie
article_ids w kontekście muszą być puste. Nie przypisuj fikcyjnego źródła.
Nie sklejaj niezgodnych liczb lub wersji w jedno twierdzenie. Zachowaj ich
zakres i czas; gdy rzeczywiście są rozbieżne, napisz np. „Część źródeł podaje
osiem zatrzymań, inne dziesięć” ze wskazaniem redakcji. Nie pisz „równocześnie
osiem i dziesięć” o tym samym bilansie. Nie zakładaj wzrostu liczby w czasie,
jeśli main_facts tego nie podają. Kilka odrębnych faktów można opisać jednym
akapitem, ale nie pomijaj istotnych działań, skutków i reakcji wyłącznie dla
skrócenia syntezy do jednego zdania.
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
jest PERSON. Synteza i zakładka Fakty przedstawiają TE SAME ustalenia w różnej
formie: synteza jako artykuł, Fakty jako pojedyncze punkty. Nie pomijaj faktu
w syntezie dlatego, że znajduje się już na liście. Kontekst ma uzupełniać
artykuł o potrzebne tło i definicje, bez powtarzania informacji już w nim
wyjaśnionych. Nie przenoś do kontekstu faktów, które powinien opisać artykuł.
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
        fid = str(raw.get('known_fact_id') or '')
        if fid and (fid not in known or (text and _text_key(text) != _text_key(known[fid]['text_pl']))):
            raise ValueError('Nieznany identyfikator lub zmieniona treść znanego faktu.')
        if fid:
            text = known[fid]['text_pl']
        if not text or not isinstance(ids, list) or not ids or any(str(i) not in by_id for i in ids):
            raise ValueError('Fakt perspektyw nie ma treści lub poprawnych materiałów źródłowych.')
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


def validate_article_coverage(response, batch):
    """Check that the extraction explicitly accounts for every sent article.

    Evidence has one source of truth: facts[].article_ids. Derive reverse
    indexes locally; incorrect optional indexes in older responses must not
    reject otherwise usable facts. Never add or remove evidence citations.
    """
    coverage = response.get('article_coverage')
    facts = response.get('facts')
    if isinstance(coverage, dict):
        if any(not isinstance(value, dict) for value in coverage.values()):
            raise ValueError('Niepoprawny wpis kontroli pokrycia artykułu.')
        rows = [{'article_id': aid, **value} for aid, value in coverage.items()]
    else:
        rows = coverage  # Compatibility with already returned older responses.
    if not isinstance(rows, list) or not isinstance(facts, list):
        raise ValueError('Brak kontroli pokrycia artykułów w ekstrakcji faktów.')
    expected = {str(a['article_id']) for a in batch}
    seen, normalized = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Niepoprawny wpis kontroli pokrycia artykułu.')
        aid = str(row.get('article_id') or '')
        if aid not in expected or aid in seen:
            raise ValueError('Obcy lub powtórzony artykuł w kontroli pokrycia faktów.')
        seen.add(aid)
        cited = [i for i, fact in enumerate(facts) if aid in fact.get('article_ids', [])]
        reason = str(row.get('no_relevant_facts_reason_pl') or '').strip()
        normalized.append({'article_id': aid, 'fact_indexes': cited,
                           'no_relevant_facts_reason_pl': '' if cited else reason,
                           'needs_review': not cited and not reason})
    if seen != expected:
        raise ValueError('Ekstrakcja faktów pominęła artykuły bieżącej paczki.')
    response['article_coverage'] = normalized

def generate(payload, call, normalize, *, max_payload_chars=300000):
    articles = payload.get('all_articles') or []
    previous = payload.get('previous_aggregation')
    previous_base = (previous or {}).get('base_summary') or {}
    previous_state = (previous or {}).get('perspective_state') or previous_base
    known = previous_state.get('perspective_facts') or []
    if not articles:
        raise ValueError('Brak materiałów do opracowania perspektyw.')
    prepared = [{**a, 'source_group': article_group(a)} for a in articles]
    facts, offset, extracted, headline, categories = known, 0, None, None, []
    while offset < len(prepared):
        base = {'topic': payload['topic'], 'previous_facts': facts}
        batch, offset = take_full_article_batch(prepared, offset, base, 'all_articles', max_payload_chars)
        extracted = call(EXTRACTION_INSTRUCTIONS, {**base, 'all_articles': batch},
                         extraction_schema(facts, [a['article_id'] for a in batch]), 'perspective_facts')
        validate_batch_citations(extracted, batch, facts, normalize)
        validate_article_coverage(extracted, batch)
        mode, facts = route_facts(extracted, articles, facts, normalize)
        headline = headline or extracted['headline_pl']
        categories = list(dict.fromkeys([*categories, *(extracted.get('categories') or [])]))
    main = [f for f in facts if f['lane'] == 'COMMON']
    if previous is not None:
        # All later calls are fact extraction only. Keep the published text,
        # lead and context, even when new facts or confirmations arrive.
        result = dict(previous_base)
        result.pop('perspective_state', None)
        result.setdefault('synthesis_coverage_mode', previous_base.get('coverage_mode', mode))
    elif mode == 'STATE_ONLY':
        # Preserve separately attributed state reports, without commissioning
        # a main synthesis or context from an empty independent fact set.
        headline = normalize(headline)
        if re.search(r'[\u0400-\u052f\u2de0-\u2dff\ua640-\ua69f]', headline):
            raise ValueError('Tytuł perspektyw zawiera cyrylicę.')
        result = {'topic': {'headline_pl': normalize(headline),
                            'what_happened_one_sentence_pl': '', 'categories': categories},
                  'summary_pl': '', 'background_context': [],
                  'synthesis_coverage_mode': mode}
    else:
        main_article_ids = {i for f in main for i in f['article_ids']}
        sources = [{key: a.get(key) for key in ('article_id', 'source_name', 'published_at')}
                   for a in articles if str(a['article_id']) in main_article_ids]
        written = call(WRITING_INSTRUCTIONS, {'headline_pl': headline, 'main_facts': main, 'main_sources': sources},
                       writing_schema(main), 'perspective_summary')
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
        result = {'topic': {'headline_pl': headline,
                            'what_happened_one_sentence_pl': main[0]['text_pl'] if main else '',
                            'categories': categories},
                  'summary_pl': '\n\n'.join(normalize(p['text_pl']) for p in paragraphs),
                  'general_context': written.get('general_context'),
                  'background_context': written.get('background_context') or [],
                  'synthesis_coverage_mode': mode}
    sections = {lane: [f for f in facts if f['lane'] == lane] for lane in ('LEFT', 'RIGHT', 'STATE')}
    update = make_update(facts, known, previous is not None, payload.get('new_article_ids') or [])
    state = {'perspective_version': FORMAT_VERSION, 'coverage_mode': mode, 'shared_available': bool(main),
             'perspective_sections': sections, 'perspective_facts': facts, 'facts': main}
    result.update(state)
    result['perspective_state'] = state
    result['update'] = update
    return result
