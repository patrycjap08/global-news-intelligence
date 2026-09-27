# GLOBAL NEWS INTELLIGENCE
## Specyfikacja produktu i implementacji v3.0

**Status:** wersja implementacyjna po symulacji pobierania źródeł
**Data:** 27 września 2026
**Strefa czasowa:** `Europe/Warsaw`
**Zakres:** prywatny agregator wiadomości, grupowanie wydarzeń, porównywanie relacji i generowanie briefingu po polsku.

---

## 1. Wnioski z testu 75 aktywnych źródeł

W katalogu znajduje się 78 źródeł, z czego trzy są celowo wyłączone: Gazeta Wyborcza, wPolityce i Telegraph. Aktywny raport obejmuje 75 źródeł.

| Wynik techniczny | Liczba | Znaczenie |
|---|---:|---|
| `FULL` | 61 | Co najmniej pięć próbek z prawidłowym body artykułu po walidacji |
| `PARTIAL` | 4 | Działa tylko część próbek albo część treści jest niepełna |
| `CAPTCHA` | 9 | Serwis pokazuje challenge lub ochronę antybotową |
| `METADATA_ONLY` | 1 | Dostępne są metadane, ale nie body |

Najczęstsze metody discovery:

- RSS: 28 źródeł;
- news sitemap: 16;
- zwykły sitemap: 14;
- skan HTML sekcji: 11;
- discovery przez przeglądarkę: 3;
- brak użytecznego discovery: 3.

Najczęstsze metody pobrania treści:

- HTTP HTML: 54 źródła;
- przeglądarka: 11;
- brak treści: 10.

### 1.1. Co wynika z realnego HTML

Źródła nie mają jednego wspólnego formatu. Występują:

- klasyczne `article` i `main`;
- JSON-LD z artykułem, ale body w HTML;
- strony renderowane JavaScriptem;
- osobne zgody cookies;
- popupy, które trzeba zamknąć;
- strony sekcji mieszające artykuły, wideo, sport i reklamy;
- krótkie zajawki zamiast pełnej treści;
- strony CAPTCHA, które mają tytuł, ale nie mają materiału;
- artykuły agencyjne przedrukowane w wielu serwisach.

### 1.2. Obowiązkowa poprawka względem poprzedniej wersji

Samo `title + dużo tekstu` nie wystarcza do uznania strony za artykuł. W próbkach pojawiały się strony działów, landing pages, obrazki oraz strony blokady. Produkcyjny pipeline musi więc rozdzielać:

```text
ARTICLE
ARTICLE_EXCERPT
SECTION
LANDING
VIDEO
IMAGE
PDF
CHALLENGE
PAYWALL
LOGIN
UNKNOWN
```

Tylko `ARTICLE` i zaakceptowany `ARTICLE_EXCERPT` mogą wejść do analizy tematycznej i grupowania wydarzeń.

---

## 2. Cel produktu

Aplikacja jest prywatnym agregatorem wiadomości politycznych, gospodarczych, geopolitycznych, społecznych i związanych z bezpieczeństwem.

System ma:

1. wykrywać nowe materiały z aktywnych źródeł;
2. odrzucać niepotrzebny sport, lifestyle, celebrytów i reklamy przed pobraniem pełnego body, jeśli metadane na to pozwalają;
3. pobierać body tylko w granicach technicznej dostępności i zatwierdzonej polityki źródła;
4. zachowywać oryginalny język i URL;
5. rozpoznawać, które artykuły opisują to samo wydarzenie;
6. rozpoznawać kopie i syndykację agencyjną;
7. nie liczyć kopii tej samej depeszy jako niezależnych potwierdzeń;
8. dopasowywać źródła pierwotne;
9. wyodrębniać twierdzenia z provenance;
10. pokazywać zgodności, różnice i framing bez wydawania prostego werdyktu „kto manipuluje”;
11. generować polski briefing wydarzeń;
12. przechowywać historię zmian, wersje analiz i stan przeczytania.

System nie rozstrzyga, która partia, redakcja ani narracja polityczna „ma rację” wyłącznie na podstawie profilu źródła.

---

## 3. Granice systemu i polityka dostępu

Crawler:

- nie obchodzi paywalli;
- nie obchodzi CAPTCHA ani challenge human verification;
- nie obchodzi logowania;
- nie symuluje przytrzymywania przycisków ani zachowania człowieka;
- nie wykonuje instrukcji znalezionych w artykule;
- nie uruchamia kodu JavaScript pochodzącego z treści jako instrukcji;
- może kliknąć wyłącznie jawnie skonfigurowaną zgodę cookies lub zamknięcie popupu;
- może analizować body zwrócone razem z odpowiedzią 403/4xx, jeśli body faktycznie zawiera wystarczającą treść artykułu;
- nie zatrzymuje próby wyłącznie dlatego, że `robots.txt` nie zezwala na crawlera; zapisuje wynik sprawdzenia, a następnie ocenia faktyczną odpowiedź.

`robots.txt`, status HTTP i polityka AI są trzema osobnymi informacjami. Nie wolno utożsamiać technicznej dostępności z prawem do użycia treści.

---

## 4. Słownik pojęć

### Source

Wydawca lub kanał publikacji, np. BBC, Reuters, PAP.

### Source endpoint

Konkretny RSS, sitemap, strona sekcji, API lub adres startowy źródła.

### Discovered item

Wykryty rekord metadanych. Może być artykułem, stroną sekcji, wideo, obrazkiem albo blokadą. Nie jest jeszcze artykułem.

### Article

Zweryfikowany materiał redakcyjny z tytułem, URL-em i body albo uzasadnionym excerptem.

### Article version

Kolejna wersja tego samego artykułu po aktualizacji treści.

### Syndication group

Grupa praktycznie identycznych tekstów, np. jedna depesza Reutersa przedrukowana przez kilka portali.

### Event

Modelowane wydarzenie lub rozwój sytuacji, do którego może należeć wiele różnych artykułów.

### Primary document

Komunikat, ustawa, decyzja, dane statystyczne, orzeczenie, stenogram albo inny dokument instytucjonalny.

### Independent source count

Liczba niezależnych relacji po odjęciu oczywistych kopii i przedruków. Nie jest równa liczbie URL-i.

### Briefing

Snapshot wydarzeń przygotowany w konkretnym przebiegu: rano, w południe albo wieczorem.

---

## 5. Architektura

```text
SCHEDULER
   ↓
CRAWL RUN
   ↓
DISCOVERY: API / RSS / SITEMAP / SECTION HTML / BROWSER
   ↓
ITEM NORMALIZATION
   ↓
ITEM TYPE + QUALITY GATE
   ├── SECTION / ASSET / CHALLENGE → metadata + health, bez analizy
   ├── DROP TOPIC → metadata + hash, bez pełnego body jeśli możliwe
   └── ARTICLE CANDIDATE
          ↓
     CONTENT FETCH
          ↓
     ARTICLE EXTRACTION
          ↓
     CONTENT VALIDATION
          ↓
     URL / HASH DEDUPLICATION
          ↓
     SYNDICATION DETECTION
          ↓
     TOPIC + ENTITY EXTRACTION
          ↓
     EVENT CANDIDATE MATCHING
          ├── PRIMARY SOURCE MATCHING
          └── CLAIM EXTRACTION
                    ↓
             CROSS-SOURCE ANALYSIS
                    ↓
                 BRIEFING
                    ↓
                 API / PWA
```

Discovery, pobieranie, ekstrakcja, deduplikacja i grupowanie wydarzeń są osobnymi modułami. Awaria jednego modułu lub źródła nie może zatrzymać całego runu.

---

## 6. Model źródła

### 6.1. Tożsamość źródła

```text
id
name
publisher
homepage
country
region
languages[]
source_type
ownership_type
parent_company
active
```

`source_type`:

```text
WIRE_SERVICE
PUBLIC_BROADCASTER
PRIVATE_GENERAL_NEWS
BUSINESS_PRESS
OPINION_MAGAZINE
STATE_MEDIA
GOVERNMENT_AGENCY
PRIMARY_SOURCE
OTHER
```

### 6.2. Profil redakcyjny

Profil jest ręcznie utrzymywanym metadanym źródła, a nie predykcją z jednego tekstu.

```text
editorial_profile
profile_country_context
ownership_type
state_affiliation
profile_basis
profile_basis_url
profile_reviewed_at
```

Przykładowe profile:

```text
LEFT / CENTER_LEFT / CENTER / CENTER_RIGHT / RIGHT
LIBERAL / PROGRESSIVE / CONSERVATIVE
WIRE / BUSINESS / PUBLIC / STATE_ALIGNED / OPINION
OTHER / UNKNOWN
```

Dla Chin, Rosji, agencji i nadawców publicznych profil lewo–prawo może być mniej użyteczny. W UI pokazujemy wtedy typ źródła i afiliację, a nie wymuszamy sztucznej osi.

### 6.3. Endpointy i akcje przeglądarkowe

```text
source_endpoints
id
source_id
endpoint_type       # API, RSS, ATOM, NEWS_SITEMAP, SITEMAP, SECTION, HOMEPAGE
url
priority
enabled
last_success_at
last_failure_at
```

Konfiguracja browsera może zawierać tylko jawne akcje:

```text
browser_accept_selectors[]
browser_close_selectors[]
browser_click_texts[]
browser_wait_after_click_seconds
browser_wait_after_load_seconds
browser_article_patterns[]
```

Nie dodajemy automatycznego mechanizmu CAPTCHA ani „human-like” zachowania.

### 6.4. Polityka źródła

```text
policy_status
ai_usage_policy
retention_policy
display_policy
terms_url
policy_evidence_url
policy_reviewed_at
policy_notes
```

Wartości:

```text
policy_status:
  APPROVED_FULL_AI
  APPROVED_EXCERPT_AI
  APPROVED_METADATA_ONLY
  REVIEW_REQUIRED
  DO_NOT_CRAWL
  DO_NOT_USE_AI
  DISABLED

ai_usage_policy:
  FULL_TEXT
  EXCERPT_ONLY
  METADATA_ONLY
  NONE

retention_policy:
  PERSIST_FULL_TEXT
  TEMPORARY_CONTENT
  PERSIST_EXCERPT
  METADATA_ONLY
```

### 6.5. Status techniczny

```text
FULL
PARTIAL
METADATA_ONLY
PAYWALL
CAPTCHA
ACCESS_RESTRICTED
FAILED
DISABLED
```

Definicje:

- `FULL`: minimum pięć zweryfikowanych materiałów typu `ARTICLE` z body spełniającym quality gate;
- `PARTIAL`: działa co najmniej jeden materiał, ale nie osiągnięto pełnego progu albo część treści jest excerptem;
- `METADATA_ONLY`: są prawidłowe rekordy, lecz nie ma body;
- `CAPTCHA`: wykryto challenge lub ochronę antybotową;
- `PAYWALL`: body jest zastąpione przez płatny dostęp;
- `ACCESS_RESTRICTED`: odpowiedź techniczna nie pozwala pobrać materiału, ale nie sklasyfikowano jej jako CAPTCHA/paywall;
- `FAILED`: brak użytecznego discovery i brak prawidłowej treści;
- `DISABLED`: źródło wyłączone konfiguracją lub decyzją użytkownika.

---

## 7. Discovery nowych materiałów

Kolejność preferowana:

```text
API
RSS / ATOM
NEWS_SITEMAP
SITEMAP
SECTION_HTML
SECTION_BROWSER
MANUAL
```

RSS nie jest wymagany. Dla każdego źródła można skonfigurować kilka endpointów i ich priorytety.

### 7.1. Watermark

Każde źródło i endpoint posiadają:

```text
last_successful_discovery_at
last_seen_published_at
last_seen_source_item_id
last_seen_canonical_url
```

Pierwszy run pobiera ograniczony zakres historyczny. Kolejne runy paginują do momentu, gdy:

1. trafią na znany materiał;
2. przekroczą `lookback_hours`;
3. osiągną `safety_cap`.

Domyślne ustawienia:

```text
lookback_hours = 18
lookback_after_outage_hours = 72
safety_cap_per_source_per_run = 200
```

Po osiągnięciu capu źródło otrzymuje alert, a run nie pobiera bez końca starego sitemapa.

### 7.2. Discovery nie zakłada, że każdy link jest artykułem

Każdy rekord przechodzi klasyfikację `item_kind` przed pobraniem pełnego tekstu. Linki do obrazów, assetów, kategorii, tagów, stron autora i landing pages są zapisywane jako metadane diagnostyczne, ale nie są artykułami.

---

## 8. Prefiltr tematyczny przed pełnym pobraniem

System wykonuje trzy poziomy filtrowania.

### Poziom 1 — konfiguracja sekcji

Preferowane działy:

```text
politics
world
international
economy
business
markets
energy
technology
science
security
war
```

Domyślnie pomijane:

```text
sport
entertainment
celebrity
fashion
lifestyle
shopping
games
```

Nie wolno zakładać, że fragment `/news/` oznacza ważny materiał. Decyzja korzysta z wielu sygnałów.

### Poziom 2 — lekki filtr metadanych

Wejście:

```text
title
description
section
tags
author
published_at
url_path
source-specific labels
```

Wyjście:

```text
KEEP
DROP
UNCERTAIN
```

`DROP` nie pobiera body, chyba że materiał został wcześniej zapisany jako referencja użytkownika albo należy do już aktywnego wydarzenia.

### Poziom 3 — klasyfikacja body

`UNCERTAIN` przechodzi do pobrania body. Klasyfikator jest wieloetykietowy i zwraca:

```json
{
  "topics": ["POLITICS", "GEOPOLITICS"],
  "primary_topic": "POLITICS",
  "relevance": 0.91,
  "excluded_topic": false,
  "reason_codes": ["GOVERNMENT", "INTERNATIONAL_EVENT"]
}
```

Kategorie:

```text
POLITICS
ELECTIONS
ECONOMY
BUSINESS
MARKETS
GEOPOLITICS
WAR_SECURITY
ENERGY
TECHNOLOGY
SCIENCE
SOCIETY
ENVIRONMENT
HEALTH
LAW_JUSTICE
LOCAL
SPORT
ENTERTAINMENT
CULTURE
LIFESTYLE
OTHER
```

Domyślnie aktywne są: polityka, wybory, gospodarka, biznes, rynki, geopolityka, bezpieczeństwo, energia, technologia, nauka, społeczeństwo, środowisko, zdrowie, prawo i lokalne wydarzenia. Sport, rozrywka i lifestyle są domyślnie wyłączone.

Użytkownik może zmieniać preferencje bez zmiany danych źródłowych.

---

## 9. Pobieranie treści

### 9.1. Kolejność

```text
HTTP GET
↓
redirect + canonical URL
↓
JSON-LD / schema.org
↓
OpenGraph / meta
↓
configured article roots
↓
semantic article/main fallback
↓
generic parser
↓
browser fallback, tylko gdy potrzebny
```

HTTP jest domyślny. Playwright uruchamiamy tylko wtedy, gdy:

- body HTTP jest puste lub zbyt krótkie;
- strona jest renderowana JS;
- źródło wymaga skonfigurowanej zgody cookies;
- źródło wymaga zamknięcia jawnego popupu;
- discovery działa tylko w przeglądarce.

### 9.2. Dozwolone akcje browsera

1. wejście na URL;
2. kliknięcie skonfigurowanej zgody cookies;
3. kliknięcie skonfigurowanego zamknięcia popupu;
4. odczekanie skonfigurowanego czasu reklam/renderowania;
5. odczyt widocznego DOM.

Nie wykonujemy akcji CAPTCHA, logowania, przytrzymywania challenge ani obchodzenia blokad.

### 9.3. Source-specific extractor registry

Selektory są konfiguracją źródła, a nie instrukcjami zaszytymi w modelu:

```yaml
article_roots:
  - selector: "article#article"
    source_kind: "article"
  - selector: "#article-body"
    source_kind: "article"
```

W aktualnym katalogu potwierdzone przykłady obejmują m.in.:

```text
PAP: article#article
TVP Info: section.article
Polsat News: article.news.news--target .news__content
Onet: article.ods-article-lead
Reuters: .article-body-module__container__oOFyv
AP: .RichTextStoryBody
Washington Post: article.grid-article .meteredContent
ABC News: .FITT_Article_main__body
Financial Times: #article-body
Economist: #new-article-template / #standard-article-template
Independent: #articleContent
```

### 9.4. Pola artykułu

```text
article_id
source_id
source_item_id
canonical_url
original_url
redirect_chain
title_original
subtitle_original
description_original
author_original
published_at
updated_at
retrieved_at
language
section
tags[]
image_url
body_original
body_excerpt
extraction_method
extractor_version
body_word_count
content_hash
```

---

## 10. Quality gate: czy to naprawdę artykuł?

Każdy pobrany dokument dostaje `item_kind` i `content_quality`.

### 10.1. Sygnały typu `ARTICLE`

Materiał powinien spełnić co najmniej jeden sygnał strukturalny i dwa sygnały treściowe.

Sygnały strukturalne:

- skonfigurowany root artykułu;
- JSON-LD `NewsArticle` lub `Article`;
- `article` z unikalnym `h1`;
- canonical URL wskazujący materiał, nie dział;
- typ strony z metadanych wskazujący artykuł.

Sygnały treściowe:

- minimum 40 słów dla zwykłego artykułu;
- minimum 20 słów tylko dla źródeł, które publikują krótkie depesze i mają potwierdzony root;
- co najmniej dwa akapity albo równoważna struktura depeszy;
- tytuł różny od nazwy kategorii i nazwy serwisu;
- obecność daty publikacji lub jednoznacznego `source_item_id`;
- body nie jest komunikatem `Access Denied`, `Security Verification`, `Just a moment`, `404` ani samym opisem paywalla.

### 10.2. Odrzucane fałszywe typy

`SECTION`, `LANDING`, `IMAGE`, `VIDEO`, `AUTHOR_PAGE`, `TAG_PAGE`, `CHALLENGE` i `ERROR_PAGE` nie zwiększają liczby artykułów ani niezależnych źródeł.

### 10.3. Jakość body

```text
COMPLETE
EXCERPT
METADATA_ONLY
PAYWALL
CAPTCHA
LOGIN_REQUIRED
EMPTY
```

Status techniczny źródła jest agregowany z jakości realnych artykułów, a nie z samej liczby HTTP 200.

---

## 11. Normalizacja

Normalizacja nie zmienia oryginału. Tworzy dodatkowe pola techniczne:

```text
title_normalized
body_normalized
normalized_tokens
normalized_entities
normalized_numbers
normalized_dates
language_detected
```

Usuwamy z wersji analizowanej:

- menu i stopki;
- reklamy i sloty reklamowe;
- popupy cookies;
- formularze i newslettery;
- komentarze;
- related stories;
- elementy ukryte;
- skrypty, style i SVG;
- powtarzalne elementy nawigacji.

Przechowujemy oryginalny tytuł, body i język w zakresie dozwolonym polityką źródła.

---

## 12. Deduplikacja URL-i i wersji artykułu

Deduplikacja jest wielowarstwowa.

### Warstwa 1 — URL

Canonicalizacja:

- normalizacja schematu i hosta;
- usunięcie fragmentu;
- usunięcie parametrów trackingowych;
- zachowanie parametrów wpływających na materiał;
- rozpoznanie redirectów;
- mapowanie source-specific canonical.

Klucz:

```text
unique(source_id, canonical_url)
```

### Warstwa 2 — identyczna treść

```text
sha256(body_normalized)
```

Jeżeli tekst ma ten sam hash, tworzymy jedną wersję treści, ale zachowujemy wszystkie źródłowe URL-e.

### Warstwa 3 — near duplicate

Stosujemy:

- MinHash lub SimHash dla n-gramów;
- podobieństwo tytułu;
- zgodność daty i autora;
- overlap encji;
- overlap pierwszych i ostatnich akapitów.

Startowe reguły do kalibracji na benchmarku:

```text
similarity >= 0.92 → prawdopodobna kopia
0.80–0.92 → kandydat syndykacji do weryfikacji
< 0.80 → nie łącz automatycznie
```

Progi nie są traktowane jako prawda uniwersalna; są wersjonowaną konfiguracją.

### Warstwa 4 — aktualizacja tego samego artykułu

Ten sam canonical URL z nowym body nie tworzy nowego wydarzenia automatycznie. Tworzy:

```text
article_version
version_number
previous_version_id
changed_sections
changed_at
```

---

## 13. Syndykacja agencyjna

Syndykacja jest czymś innym niż wspólne wydarzenie.

Przykład:

```text
Reuters depesza
→ portal A kopia
→ portal B kopia
→ portal C skrót
```

System tworzy:

```text
syndication_group_id
probable_origin_source_id
syndication_confidence
syndication_evidence
```

### 13.1. Wybór reprezentanta

Preferowana kolejność:

1. źródło pierwotne lub prawdopodobny oryginał;
2. najwcześniejsza publikacja;
3. najpełniejszy zweryfikowany body;
4. źródło z najlepszymi metadanymi;
5. pozostałe kopie jako dodatkowe linki.

### 13.2. Liczenie niezależności

W briefingu pokazujemy osobno:

```text
all_related_articles
independent_source_families
syndication_groups
primary_documents
```

Pięć portali z tą samą depeszą może oznaczać jedną niezależną relację, nie pięć.

---

## 14. Encje, fakty i tematy

Dla zweryfikowanego artykułu wyciągamy:

```text
people
organizations
political_parties
government_bodies
locations
countries
dates
money_values
percentages
casualty_numbers
laws
elections
markets
```

Każda encja ma span w tekście i confidence. Normalizujemy aliasy, ale nie usuwamy oryginalnej formy.

Temat jest wieloetykietowy. Artykuł może być jednocześnie `POLITICS`, `ECONOMY` i `ENERGY`; posiada jednak jeden `primary_topic` dla sortowania.

Profil polityczny źródła nie wpływa na to, czy artykuł jest ważny ani prawdziwy. Jest tylko filtrem prezentacyjnym i metadanym porównawczym.

---

## 15. Event clustering: grupowanie tego samego wydarzenia

Główną jednostką agregacji jest `event`, nie artykuł.

### 15.1. Reprezentacja wydarzenia

```text
event_id
canonical_title_pl
event_type
first_seen_at
last_updated_at
event_time_start
event_time_end
countries[]
locations[]
entities[]
importance_score
cluster_confidence
status
```

`event_type` może obejmować:

```text
ELECTION
GOVERNMENT_DECISION
LAW_AND_JUSTICE
MILITARY_ACTION
SECURITY_INCIDENT
INTERNATIONAL_DIPLOMACY
ECONOMIC_DATA
MARKET_MOVE
CORPORATE_EVENT
NATURAL_DISASTER
HEALTH_EVENT
SOCIAL_EVENT
OTHER
```

### 15.2. Candidate retrieval

Nowy artykuł porównujemy najpierw z aktywnymi wydarzeniami:

- z tej samej kategorii;
- z ostatnich 72 godzin dla szybkich newsów;
- z ostatnich 30 dni dla wyborów, wojen, procesów i długich spraw;
- mającymi wspólne encje lub lokalizacje.

Nie porównujemy każdego nowego tekstu z całą historią.

### 15.3. Wynik dopasowania

Startowy score jest wielosygnałowy:

```text
0.30 semantic_similarity
0.20 entity_overlap
0.15 title_similarity
0.15 time_compatibility
0.10 location_overlap
0.05 number_overlap
0.05 event_type_compatibility
```

Reguły startowe:

```text
score >= 0.82 → automatyczne dołączenie
0.65–0.82 → dołączenie z niższą pewnością albo kolejka review
< 0.65 → nowe wydarzenie
```

Wymagane są twarde blokady merge, np. sprzeczne daty, różne miasta, różne osoby i różne zdarzenia o podobnych słowach.

Progi muszą zostać skalibrowane na ręcznie opisanym zbiorze. System przechowuje powody dopasowania:

```json
{
  "matched_entities": ["Donald Tusk", "Sejm"],
  "matched_location": "Warszawa",
  "time_delta_hours": 4.2,
  "semantic_score": 0.88,
  "decision": "AUTO_LINK"
}
```

### 15.4. Aktualizacja wydarzenia zamiast duplikatu

Artykuł trafia do istniejącego wydarzenia, jeśli opisuje:

- ten sam incydent;
- tę samą decyzję;
- tę samą konferencję lub głosowanie;
- kolejny etap tej samej sprawy w określonym oknie czasowym.

Tworzymy nowe wydarzenie, jeśli zmienił się główny obiekt, miejsce, data lub rodzaj zdarzenia.

Wydarzenie może mieć status:

```text
NEW
ACTIVE
UPDATED
STABLE
ARCHIVED
MERGE_REVIEW
SPLIT_REVIEW
```

### 15.5. Artykuły wielowątkowe

Jeśli artykuł opisuje kilka niezależnych wydarzeń, nie wolno automatycznie kopiować całego body do każdego klastra. Tworzymy `article_event_segment` z offsetami tekstu i przypisujemy tylko właściwe fragmenty.

---

## 16. Źródła pierwotne

System posiada registry instytucji:

```text
institution_id
name
country
jurisdiction
institution_type
official_domains[]
```

Przykładowe typy:

```text
GOVERNMENT
PARLIAMENT
COURT
CENTRAL_BANK
STATISTICS_OFFICE
REGULATOR
INTERNATIONAL_ORGANIZATION
COMPANY
```

Matcher używa:

```text
entities
jurisdiction
event_type
date_window
keywords
official_domain
```

Dokument pierwotny może potwierdzać, co instytucja ogłosiła, ale nie czyni automatycznie twierdzeń instytucji prawdą.

---

## 17. Evidence, claims i provenance

Każda informacja w systemie należy do jednej z kategorii:

```text
SOURCE_FACT
ATTRIBUTED_CLAIM
CROSS_SOURCE_FINDING
CONTEXT
USER_NOTE
```

Każdy claim posiada:

```text
claim_id
article_id or document_id
claim_type
text_original
text_pl
source_span_start
source_span_end
evidence_quote_or_hash
confidence
extraction_model
extraction_prompt_version
```

Zdanie faktograficzne bez `claim_id` i evidence nie może trafić do finalnego briefingu.

Przykład poprawny:

```text
Minister powiedział, że projekt obniży koszty. [źródło: article_id, span]
```

Nie wolno przekształcać tego w:

```text
Projekt obniży koszty.
```

Jeśli materiał ma tylko metadata, może być użyty do wykazania istnienia publikacji, ale nie do twierdzenia o faktach z body.

---

## 18. Analiza artykułu

Model otrzymuje tylko zweryfikowany materiał, nie surową stronę z instrukcjami.

Wyjście strukturalne:

```json
{
  "factual_claims": [],
  "attributed_claims": [],
  "opinions": [],
  "quotes": [],
  "numbers": [],
  "dates": [],
  "entities": [],
  "causal_claims": [],
  "anonymous_source_claims": [],
  "uncertainties": [],
  "value_loaded_phrases": [],
  "missing_context_signals": []
}
```

Każdy element ma offset i `article_id`.

System nie używa jednej etykiety `MANIPULATIVE`. Raportuje obserwowalne sygnały:

```text
VALUE_LOADED_LANGUAGE
HEADLINE_BODY_MISMATCH
SELECTIVE_CONTEXT
UNSUPPORTED_CERTAINTY
STATISTICAL_FRAMING
CAUSAL_LEAP
ATTRIBUTION_PROBLEM
ANONYMOUS_SOURCE
POSSIBLE_OMISSION
QUOTE_CONTEXT
```

`POSSIBLE_OMISSION` jest dozwolone tylko przy kompletnym body i konkretnej podstawie porównawczej.

---

## 19. Cross-source analysis

Analizator wydarzenia otrzymuje:

- deduplikowane claims;
- fragmenty evidence;
- informacje o syndykacji;
- primary documents;
- metadane źródeł;
- wersję wydarzenia i timeline.

Nie dostaje bez potrzeby 30 pełnych, powtarzających się artykułów.

Wyjście:

```json
{
  "common_points": [],
  "primary_source_findings": [],
  "disputed_points": [],
  "source_specific_claims": [],
  "framing_differences": [],
  "possible_omissions": [],
  "uncertainties": [],
  "unanswered_questions": []
}
```

Profil redakcyjny służy do opisu rozkładu relacji, np. „źródła centroprawicowe eksponują X”, ale nie może być dowodem na prawdziwość ani fałszywość claimu.

---

## 20. Briefing i agregacja dla użytkownika

Użytkownik czyta wydarzenia, nie listę powtarzających się URL-i.

Karta wydarzenia pokazuje:

```text
canonical_title_pl
last_updated_at
primary_topic
importance_score
independent_source_count
all_article_count
syndication_group_count
primary_document_count
source_languages
source_regions
```

Sekcje:

1. **W skrócie** — maksymalnie kilka zdań z provenance;
2. **Co wiadomo** — wspólne, potwierdzone twierdzenia;
3. **Źródła pierwotne** — dokumenty i ich znaczenie;
4. **Co się różni** — sprzeczne liczby, daty, wersje i akcenty;
5. **Framing** — opis języka i doboru informacji;
6. **Oś czasu** — chronologiczne aktualizacje;
7. **Czego nie wiemy** — niepewności i braki;
8. **Źródła** — reprezentanci syndykacji oraz pozostałe linki;
9. **Twoje notatki** — wyraźnie oddzielone od faktów.

Jeśli artykuł jest tylko metadata-only, UI pokazuje tytuł, datę, źródło i link, ale nie udaje, że zna jego treść.

### 20.1. Brak duplikatów w briefingu

Jeden event może pojawić się tylko raz w danym briefingu. Jeśli wydarzenie zostało zaktualizowane, otrzymuje badge `NOWA AKTUALIZACJA`, a nie nową kartę.

Jeśli dwa klastry zostaną połączone, briefing zachowuje wersję i zapisuje `merged_from_event_ids`. Jeśli klaster zostanie rozdzielony, zapisuje `split_from_event_id`.

### 20.2. Zmiana od poprzedniego briefingu

Wieczorny briefing ma opcjonalną sekcję:

```text
CO ZMIENIŁO SIĘ OD POPRZEDNIEGO BRIEFINGU
```

Pokazuje tylko nowe claims, nowe dokumenty, zmiany liczb i nowe źródła niezależne.

---

## 21. Harmonogram i przebiegi

Domyślnie trzy pełne runy dziennie:

```text
morning
midday
evening
```

Godziny są konfigurowalne. Każdy run ma:

```text
run_id
started_at
finished_at
trigger_type
config_version
source_count
status
```

Run jest częściowo udany, jeśli część źródeł zawiodła. Nie wolno oznaczać całego runu jako failed tylko dlatego, że Bloomberg ma CAPTCHA.

---

## 22. Retry, rate limit i health

Konfiguracja źródła:

```text
requests_per_minute
concurrency_limit
min_delay_ms
timeout_seconds
max_retries
browser_timeout_seconds
```

Retry:

```text
HTTP transient 5xx/408/429: maksymalnie 3
browser transient: maksymalnie 2
AI transient: maksymalnie 2
```

Nie retryujemy bez końca:

```text
CAPTCHA
PAYWALL
LOGIN_REQUIRED
POLICY_BLOCK
challenge page
```

Alert po trzech kolejnych nieudanych runach albo po:

- zniknięciu RSS/sitemapa;
- nagłym spadku discovery do zera;
- nagłym spadku body success;
- zmianie DOM powodującej `EMPTY`;
- osiągnięciu safety capu;
- wygaśnięciu przeglądu polityki.

---

## 23. Baza danych

### `sources`

```text
id PK
name
publisher
homepage
country
region
languages_json
source_type
editorial_profile
ownership_type
state_affiliation
active
policy_status
ai_usage_policy
retention_policy
display_policy
policy_reviewed_at
created_at
updated_at
```

### `source_endpoints`

```text
id PK
source_id FK
endpoint_type
url
priority
enabled
last_success_at
last_failure_at
last_error_code
```

### `crawl_runs`

```text
id PK
trigger_type
started_at
finished_at
status
config_version
```

### `source_run_results`

```text
id PK
run_id FK
source_id FK
technical_status
robots_result
robots_http_status
items_discovered
items_kept
items_dropped
articles_fetched
articles_valid
body_success
captcha_count
paywall_count
recommended_discovery_method
recommended_content_method
error_code
notes
```

### `discovered_items`

```text
id PK
source_id FK
run_id FK
source_item_id
original_url
canonical_url
url_hash
title
description
section
tags_json
published_at
updated_at
item_kind
prefilter_decision
prefilter_score
first_seen_at
last_seen_at
```

Unique constraint: `(source_id, canonical_url)`.

### `articles`

```text
id PK
discovered_item_id FK
source_id FK
canonical_url
language
title_original
subtitle_original
body_original nullable
body_excerpt nullable
content_quality
extraction_method
extractor_version
body_word_count
content_hash
retrieved_at
```

### `article_versions`

```text
id PK
article_id FK
version_number
body_original
content_hash
changed_sections_json
created_at
```

### `syndication_groups`

```text
id PK
fingerprint
probable_origin_article_id nullable
confidence
evidence_json
created_at
```

### `events`

```text
id PK
canonical_title_pl
event_type
status
first_seen_at
last_updated_at
event_time_start
event_time_end
importance_score
cluster_confidence
embedding
```

### `event_members`

```text
event_id FK
article_id FK
segment_start nullable
segment_end nullable
membership_score
membership_reason_json
is_representative
```

### `primary_documents`, `claims`, `claim_evidence`

Przechowują dokumenty, span-y, typ claimu, offsety, wersję ekstraktora i relację do wydarzenia.

### `event_analysis_versions`

```text
id PK
event_id FK
version
input_article_ids_json
input_document_ids_json
analysis_json
summary_pl
ai_provider
model_name
prompt_version
created_at
```

Stare wersje nie są nadpisywane.

### `briefings`, `briefing_items`, `user_event_state`, `user_notes`

Przechowują snapshoty briefingów, kolejność kart, przeczytanie, zapisanie i notatki użytkownika. Notatka nie staje się claimem automatycznie.

---

## 24. API minimalne

```text
GET  /api/briefings
GET  /api/briefings/{id}

GET  /api/events
GET  /api/events/{id}
GET  /api/events/{id}/timeline
GET  /api/events/{id}/sources
GET  /api/events/{id}/claims
GET  /api/events/{id}/versions

POST /api/events/{id}/read
POST /api/events/{id}/save

GET  /api/search?q=&topic=&region=&source_id=
GET  /api/history
GET  /api/saved

GET  /api/preferences
PUT  /api/preferences

GET  /api/events/{id}/notes
POST /api/events/{id}/notes
PUT  /api/notes/{id}
DELETE /api/notes/{id}

GET  /api/admin/sources
PUT  /api/admin/sources/{id}
GET  /api/admin/sources/{id}/health

POST /api/admin/crawl
GET  /api/admin/crawl/{id}
POST /api/admin/source-tests
GET  /api/admin/source-tests/{id}
```

Endpointy admin wymagają uwierzytelnienia.

---

## 25. PWA i widoki

Frontend może być zbudowany jako Next.js + React + TypeScript.

Widoki MVP:

```text
Dziś
Briefing
Wydarzenie
Oś czasu
Źródła
Historia
Zapisane
Wyszukiwanie
Ustawienia
Health źródeł
```

Strona wydarzenia musi pokazywać liczbę artykułów oraz liczbę niezależnych relacji osobno. Link do źródła jest zawsze dostępny; fragment body jest pokazywany tylko zgodnie z polityką źródła.

---

## 26. Bezpieczeństwo i prompt injection

Artykuł jest nieufnym inputem, nie instrukcją.

Model nie może:

- wykonywać poleceń z treści;
- uruchamiać URL-i wskazanych w artykule;
- zmieniać konfiguracji;
- uzyskiwać dostępu do sekretów;
- wywoływać narzędzi na podstawie tekstu artykułu.

Każdy wynik AI przechodzi JSON Schema/Pydantic validation. Sekrety są wyłącznie w environment variables lub secret managerze. Nie logujemy cookies, tokenów ani pełnego body bez potrzeby.

---

## 27. Monitoring i raport źródeł

Raport techniczny rozdziela:

```text
discovery status
content status
policy status
item_kind statistics
article quality statistics
```

Raport musi pokazywać osobno:

- ile wykryto URL-i;
- ile było stron sekcji/assetów;
- ile zakwalifikowano jako artykuły;
- ile odrzucono przed pobraniem body;
- ile pobrano pełnych body;
- ile było excerptów;
- ile było CAPTCHA/paywall/login;
- ile grup syndykacji utworzono;
- ile wydarzeń utworzono lub zaktualizowano.

Raport nie może oznaczać `FULL` tylko dlatego, że parser znalazł dużo tekstu na stronie.

---

## 28. Testy i benchmarki

### 28.1. Source benchmark

Dla każdego aktywnego źródła minimum pięć ręcznie zweryfikowanych rekordów:

- prawdziwy artykuł;
- strona sekcji;
- materiał krótki;
- materiał z popupem lub cookies, jeśli występuje;
- materiał z blokadą, jeśli występuje.

### 28.2. Quality gate

Testujemy, czy system nie uznaje za artykuł:

- strony głównej;
- kategorii;
- obrazka;
- strony `Just a moment`;
- strony `Security Verification`;
- samego paywalla;
- strony 404;
- strony autora.

### 28.3. Deduplikacja

Gold set musi obejmować:

- identyczne URL-e;
- URL-e z trackingiem;
- ten sam artykuł po aktualizacji;
- kopię agencyjną;
- skróconą kopię agencyjną;
- dwa podobne, ale różne wydarzenia.

### 28.4. Event clustering

Gold set musi obejmować:

- wiele języków;
- to samo wydarzenie z różnymi tytułami;
- aktualizacje tego samego wydarzenia;
- podobne nazwiska i różne wydarzenia;
- dwa wydarzenia tego samego dnia w tym samym mieście;
- wojnę, wybory, dane gospodarcze i incydent lokalny.

### 28.5. Kryteria jakości

Minimalne warunki przed przejściem do kolejnego etapu:

- 100% zdań faktograficznych w golden dataset ma provenance;
- brak automatycznego zaliczenia stron `SECTION`, `ASSET` i `CHALLENGE` jako artykułów;
- kopie tej samej depeszy nie są liczone jako niezależne źródła;
- błędne połączenie dwóch wydarzeń jest traktowane jako błąd krytyczny;
- każdy merge ma zapisany powód;
- każde źródło może zawieść bez zatrzymania całego runu;
- minimum dziewięć kolejnych planowych runów kończy się z zachowanym watermarkiem;
- stary event nie pojawia się ponownie jako nowy bez nowego materiału lub aktualizacji.

---

## 29. Etapy implementacji

### Etap 0 — poprawa Source Ingestion Testera

Zakres:

- `item_kind`;
- `content_quality`;
- article quality gate;
- odrzucanie assetów i landing pages;
- osobne statystyki `discovered`, `article`, `body`;
- source-specific extractor registry;
- zachowanie obecnych zgód cookies i popupów;
- aktualizacja raportu HTML/JSON/CSV.

Definition of Done: raport nie liczy strony blokady ani sekcji jako pełnego artykułu.

### Etap 1 — produkcyjny ingestion

Zakres:

- PostgreSQL;
- source registry;
- endpointy;
- crawl runs;
- watermarks;
- rate limiting;
- retries;
- discovered items;
- article versions;
- health monitoring.

### Etap 2 — topic filtering i deduplication

Zakres:

- filtr metadanych przed body;
- klasyfikator tematów;
- URL/hash/near-duplicate;
- syndykacja;
- benchmark jakości.

### Etap 3 — event clustering

Zakres:

- NER i encje;
- embeddings;
- pgvector;
- event lifecycle;
- merge/split review;
- timeline.

### Etap 4 — primary sources i AI intelligence

Zakres:

- primary registry;
- claim extraction;
- provenance;
- porównanie cross-source;
- framing;
- kontekst;
- briefing PL;
- versioning promptów i analiz.

### Etap 5 — PWA

Zakres:

- frontend;
- read/save state;
- historia;
- wyszukiwarka;
- ustawienia;
- health panel.

Nie przechodzimy do kolejnego etapu tylko dlatego, że poprzedni kod się uruchamia. Każdy etap wymaga obejrzenia rzeczywistych wyników.

---

## 30. Pierwsze zadanie implementacyjne po tej specyfikacji

```text
Zaimplementuj Etap 0 i Etap 1 specyfikacji Global News Intelligence v3.0.

Nie implementuj jeszcze finalnej PWA ani pełnej analizy framingu.

1. Dodaj item_kind i content_quality.
2. Zablokuj uznawanie section/landing/asset/challenge za artykuł.
3. Zachowaj działające zgody cookies i zamykanie popupów.
4. Dodaj source-specific article roots z konfiguracji.
5. Dodaj quality gate dla title, canonical, daty i body.
6. Zaimplementuj PostgreSQL schema dla sources, endpoints, runs,
   discovered_items, articles i article_versions.
7. Dodaj watermark per source endpoint.
8. Dodaj rate limiting, retry i health status.
9. Nie obchodź CAPTCHA, paywalli, loginów ani zabezpieczeń antybotowych.
10. Wygeneruj report.html, report.json, report.csv oraz source health.

Po ukończeniu zatrzymaj implementację i pokaż wyniki. Nie przechodź do
event clusteringu bez ręcznego benchmarku item_kind i deduplikacji.
```

---

## 31. Główne kryterium jakości

Dla każdego zdania w briefingu system musi odpowiedzieć:

```text
Skąd to się wzięło?
```

Ścieżka:

```text
source item
→ article version
→ source span
→ claim
→ event analysis version
→ sentence in briefing
```

Jeśli tej ścieżki nie można odtworzyć, zdanie nie może być przedstawione jako ustalony fakt.

Priorytet rozwoju:

```text
1. poprawność typu materiału
2. provenance
3. zgodność polityki źródeł
4. stabilne pobieranie
5. deduplikacja i syndykacja
6. poprawne grupowanie wydarzeń
7. jakość analizy
8. pokrycie geograficzne
9. koszt i szybkość
10. wygląd
```
