# Audyt pobierania źródeł — 28 października 2026

Kontrola objęła 28 źródeł z zerowymi wynikami, blokadami, dużą liczbą odrzuceń albo powiązanych z nimi czytników. Użyto funkcji produkcyjnych `discover_candidates`, `fetch_one`, `extract_article` i `classify_item`. Sprawdzano do trzech najnowszych kandydatów na źródło. Powtórna kontrola używała zapisanych odpowiedzi HTTP, a nowe adresy pobierała normalnie. Żadnych wywołań AI ani zapisów w produkcyjnej bazie.

To próbki techniczne, nie gwarancja dostępności całego źródła. Liczba kandydatów po filtracji nie oznacza liczby nowych artykułów, ponieważ audyt nie odczytuje produkcyjnego stanu deduplikacji.

## Wyniki HTTP

| Źródło | Poprawne przed | Poprawne po | Wynik / zmiana |
| --- | ---: | ---: | --- |
| ABC News | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| Axios | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| Bild | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| CBS News | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| The Daily Signal | 3/3 | 3/3 | Pełny tekst z oficjalnego RSS; w próbkach brak potrzeby żądania HTML artykułu. |
| Der Spiegel | 2/3 | 2/3 | Płatny wstęp jako PAYWALL; publiczne teksty nadal pobierane. |
| Deutsche Welle | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| Do Rzeczy | 3/3 | 3/3 | Jawne RSS Kraj/Świat/Ekonomia i news sitemap; brak zależności od kanałów wykrywanych z HTML. |
| EFE | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| El País | 3/3 | 3/3 | Relacje en-directo nie zajmują okna zwykłych artykułów; HTTP działa lokalnie, blokady GitHub wymagają kontroli na runnerze. |
| Financial Times | 0/3 | 0/3 | Nadal prawdziwa strona Security Verification HTTP 403. Nie jest pobierana jako artykuł. |
| HuffPost | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| Kyiv Independent | 0/3 | 3/3 | Wykluczone profile autorów, tagi i strony nawigacyjne; jawny RSS wiadomości. |
| La Repubblica | 2/3 | 2/3 | Płatny wstęp jako PAYWALL; publiczne teksty nadal pobierane. |
| Le Figaro | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| Le Monde | 2/3 | 3/3 | Jawny RSS; relacje /live/ nie zajmują okna zwykłych artykułów. |
| Meduza | 0/3 | 3/3 | Prawidłowy główny kontener treści, bez karty polecanego tekstu. Pełny tekst z publicznego RSS. |
| Mother Jones | brak próbek | brak próbek | Lokalny proxy odrzuca połączenie CONNECT HTTP 403; nie jest to dowód awarii źródła. W danych użytkowniczki działało 8 nowych artykułów. |
| National Review | brak próbek | brak próbek | Lokalny proxy odrzuca połączenie CONNECT HTTP 403; nie jest to dowód awarii źródła. W danych użytkowniczki działało 10 nowych artykułów. |
| New York Post | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| NPR | 3/3 | 3/3 | Jawne kanały RSS niezależne od odczytu strony głównej. |
| Polsat News | 3/3 | 3/3 | Jawne RSS Polska/Świat/Biznes i news sitemap; wykrywanie działa także przy zablokowanej stronie głównej. |
| Reuters | 2/3 | 2/3 | Jawna news sitemap; krótkie płatne wstępy rozpoznawane jako PAYWALL. |
| Sky News | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| Suspilne | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |
| Times | 1/3 | 1/3 | Publiczne teksty odczytywane HTTP; krótkie płatne wstępy jako PAYWALL, bez ponowienia w przeglądarce. |
| TVP Info | 0/3 | 0/3 | Próba HTTP daje krótkie strony wymagające przeglądarki; konfiguracja BROWSER pozostaje. Ostatnie zero z raportu użytkowniczki oznaczało 15 już zapisanych materiałów. |
| Washington Post | 3/3 | 3/3 | Próbki poprawne; nie zmieniano czytnika. |

## Wspólne poprawki

- Prawidłowe oznaczenie płatnego wstępu, kiedy wydawca deklaruje ograniczenie i udostępnia mniej niż 100 słów. Taki materiał nie uruchamia ponownego odczytu w przeglądarce ani pętli uzupełniania krótkich materiałów. Publiczny dostępny tekst pozostaje dostępny.
- HTTP 401/403 bez oznak CAPTCHA jest raportowane jako BLOCKED. Błędy HTTP nie stają się artykułami przez długą treść strony błędu.
- Zablokowane odczyty, CAPTCHA i nieudane odpowiedzi zwiększają `failed_count`. Awaria całego wykrywania źródła również zapisuje `failed_count=1`, zamiast samych uwag z zerowym licznikiem.
- Nie obniżono minimum 100 słów i nie włączono wyłączonych źródeł.

## Weryfikacja na GitHubie

Lokalny Chromium nie mógł zweryfikować certyfikatu proxy. Nie wyłączano weryfikacji TLS. Zamiast zmieniać zaufanie certyfikatów przygotowano osobny workflow `audit-sources.yml`, uruchamiający standardowy Chromium na GitHubie. Sprawdza do dwóch artykułów dla 12 źródeł, bez sekretów OpenAI/Supabase, zapisów do bazy i wywołań AI. Raport ma pokazywać także blokady i błędy; pomyślne zakończenie workflow nie oznacza dostępności wszystkich źródeł.

Test wykonano: [GitHub Actions 40754563867](https://github.com/patrycjap08/global-news-intelligence/actions/runs/40754563867), job 123049914709, commit `fed5746`. Raport z runnera ma pierwszeństwo przy ocenie problemów widocznych w produkcyjnym SQL.

| Źródło | Poprawne próbki | Pozostały wynik |
| --- | ---: | --- |
| Axios | 1/2 | BLOCKED, COMPLETE |
| Do Rzeczy | 0/0 | brak adresów, HTTP 403 |
| El País | 1/2 | COMPLETE, BLOCKED |
| Financial Times | 0/2 | CAPTCHA |
| Kyiv Independent | 2/2 | COMPLETE |
| Meduza | 2/2 | COMPLETE |
| Polsat News | 2/2 | COMPLETE |
| Reuters | 0/0 | brak adresów, HTTP 401 |
| Sky News | 0/2 | CAPTCHA |
| The Daily Signal | 2/2 | COMPLETE |
| Times | 0/2 | PAYWALL |
| TVP Info | 2/2 | COMPLETE |

Potwierdzono poprawne pobieranie Polsatu, Meduzy, Daily Signal, Kyiv Independent i TVP Info. Reuters i Do Rzeczy nadal blokują wykrywanie adresów z runnera. Sky News i Financial Times blokują odczyt artykułów. Axios oraz El País są dostępne częściowo. Próbki Times w tym przebiegu były płatnymi wstępami; inne publiczne teksty działały w teście HTTP.

Nie ma w kodzie poprawki, która zapewni dostęp do zasobu blokowanego przez wydawcę lub wymagającego uprawnień. Nie obchodzono CAPTCHA ani płatnego dostępu i nie wyłączono źródeł w celu ukrycia problemu. W razie potrzeby pełnego pokrycia tych źródeł potrzebny jest dozwolony dostęp wydawcy lub jego licencjonowany kanał.

Weryfikacja: 443 testy automatyczne, 78 prób odczytu HTTP w 28 źródłach oraz niezależna kontrola HTTP/przeglądarkowa 12 źródeł na GitHubie. Testy nie uruchamiały AI i nie zapisywały danych w produkcyjnej bazie.

## Zastosowanie

Uruchomić nowy `full` z `main`, aby pobrać brakujące artykuły i uruchomić ich analizę. `ai-only` nie pobiera źródeł. Nie usuwać istniejących artykułów ani opracowań. Meduza może od razu odzyskać wcześniej zbyt krótkie odczyty, jeśli pełna treść jest w aktualnym RSS. Pozostałe zapamiętane odrzucenia TOO_SHORT można ponowić przez `retry_rejected` w kolejnym full; opcja pozostaje wyłączona domyślnie.
