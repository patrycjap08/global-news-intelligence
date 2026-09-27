# Global News Intelligence

Repozytorium zawiera harvester artykułów, trwałą deduplikację oraz produkcyjny
worker uruchamiany przez GitHub Actions. Docelowa baza danych to Supabase, a
GitHub przechowuje kod i workflow — nie pełne archiwum artykułów.

## Szybki start produkcyjny

1. Uruchom `supabase_schema.sql` w SQL Editorze projektu Supabase.
2. Dodaj cztery sekrety GitHuba opisane w `DEPLOYMENT.md`.
3. Uruchom ręcznie workflow `Global News Intelligence — harvest and analysis`.

Szczegółowa instrukcja znajduje się w [DEPLOYMENT.md](DEPLOYMENT.md).

Pipeline wykonuje kolejno: pobranie stanu deduplikacji z Supabase, odwiedzenie
stron głównych, zapis tylko nowych artykułów, synchronizację z Supabase,
grupowanie AI 1 i opracowania AI 2. Klucze nie są wpisane do kodu.

## Uruchomienie

```bash
python3 source_tester.py --config sources.yaml --output-dir .
```

Opcjonalny test pojedynczego źródła:

```bash
python3 source_tester.py --source bbc --max-article-probes 2
```

Pełny test z fallbackiem przeglądarkowym (potrzebny m.in. dla PAP i TVP):

```bash
python3 source_tester.py --browser --max-article-probes 5 --output-dir .
```

Wyniki:

- `report.html` — raport do ręcznego przeglądu;
- `report.json` — pełne wyniki maszynowe, w tym endpointy i próbki metadata;
- `report.csv` — wiersze per źródło i metoda.
- `source_runtime.yaml` — gotowy katalog operacyjny: pełny content, metadata-only albo wyłączone.

Tester sprawdza autodiscovery RSS/Atom, sitemap/news sitemap, skan linków HTML,
pobranie HTML artykułów, linki PDF oraz opcjonalny fallback Playwright. Wpis w
`sources.yaml` może dodatkowo zawierać `section_urls`, `rss_urls`, `atom_urls`,
`sitemap_urls` i `api_url`, gdy automatyczne wykrywanie nie wystarcza.
Źródła JS mogą mieć także `browser_close_selectors` (widoczne przyciski zamknięcia
popupu) oraz `browser_wait_after_load_seconds` (oczekiwanie na zakończenie
ładowania/reklamy). PAP korzysta z selektorów struktury `article#article`, a TVP
z `section.article`; popup TVP jest zamykany przez `.snrs-popup .snrs-close-btn`.
Zgody cookies można skonfigurować przez `browser_accept_selectors`, a przejścia
typu Onet przez `browser_click_texts`. Wpis z `enabled: false` pozostaje w
katalogu, ale jest pomijany podczas testu. W katalogu są skonfigurowane zgody
dla FT, Times i Economist oraz zgoda i zamknięcie modala Independent. Telegraph
jest wyłączony, ponieważ wykrywa automatyzację; tester nie obchodzi tej kontroli.
Tester nie uznaje samego komunikatu
o subskrypcji za paywall: jeśli treść artykułu jest w HTML, próbuje ją wyciągnąć.
`robots.txt` jest tylko odnotowywany jako wykonane sprawdzenie i nie kończy próby
przed wejściem na stronę; wynik zależy od faktycznej odpowiedzi HTTP/przeglądarki.
Tester nie obchodzi CAPTCHA ani logowania i nie automatyzuje testów typu „Human
challenge”. Pełne body artykułów nie są
zapisywane w raportach — próbki zawierają metadata i hash treści.

## Trwały pierwszy zbiór artykułów

Harvester pobiera linki wyłącznie ze stron głównych aktywnych źródeł i zapisuje
artykuły do SQLite oraz eksportu JSONL/HTML:

```bash
python3 article_harvester.py --browser --max-articles-per-source 50
```

Treść krótsza niż 200 słów nie trafia do eksportu ani do tabeli artykułów.
Adres odrzuconego materiału jest zapamiętywany technicznie, żeby nie pobierać
go ponownie. Opcja `--retry-rejected` pozwala świadomie spróbować ponownie.
Poza deduplikacją po znormalizowanym adresie URL harvester rozpoznaje także
duplikaty tego samego źródła po znormalizowanym tytule i pierwszych dwóch
zdaniach. Jeśli tytuł jest taki sam, ale pierwsze dwa zdania są inne, artykuły
pozostają osobnymi rekordami.

## Automatyczny profil źródła

Profil redakcyjny jest przypisywany raz do źródła, nie do pojedynczego artykułu.
Algorytm działa w tej kolejności:

1. używa jawnego `editorial_profile` z `sources.yaml`, jeśli został ustawiony;
2. w przeciwnym razie używa mapy `SOURCE_EDITORIAL_PROFILES` w `source_tester.py`;
3. jeśli źródła nie ma w mapie, zostawia `UNCLASSIFIED` zamiast zgadywać.

Kategorie to `LEFT`, `CENTER_LEFT`, `CENTER`, `CENTER_RIGHT`, `RIGHT` oraz
`STATE_ALIGNED`. Ta ostatnia jest osobna, bo np. media państwowe nie powinny
być sztucznie przypisywane do lewicy albo prawicy. Profil opisuje ogólną linię
źródła i nie jest oceną prawdziwości konkretnego artykułu.

## Dane wymagające ręcznego uzupełnienia

`sources.yaml` zawiera domeny startowe wywnioskowane z nazw w specyfikacji. Przed
użyciem produkcyjnym trzeba zweryfikować dokładne domeny, endpointy API, URL-e
warunków użycia i policy status. Domyślna polityka to `REVIEW_REQUIRED` oraz
`ai_usage_policy: NONE`; dostępność techniczna nie jest zgodą na użycie pełnego
tekstu w AI.
