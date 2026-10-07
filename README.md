# Global News Intelligence

Repozytorium zawiera harvester artykułów, trwałą deduplikację oraz produkcyjny
worker uruchamiany przez GitHub Actions. Docelowa baza danych to Supabase, a
GitHub przechowuje kod i workflow — nie pełne archiwum artykułów.

## Szybki start produkcyjny

1. Uruchom `supabase_schema.sql` w SQL Editorze projektu Supabase.
2. Dodaj cztery sekrety GitHuba opisane w `DEPLOYMENT.md`.
3. Uruchom ręcznie workflow `Global News Intelligence — harvest and analysis`.

Szczegółowa instrukcja znajduje się w [DEPLOYMENT.md](DEPLOYMENT.md).

Pipeline wykonuje kolejno: pobranie stanu deduplikacji z Supabase, odkrywanie
artykułów przez RSS/sitemapy/sekcje oraz stronę główną jako fallback, zapis tylko nowych artykułów, synchronizację z Supabase,
grupowanie AI 1 i opracowania AI 2. Klucze nie są wpisane do kodu.

Integracja z X została usunięta. Analiza korzysta z artykułów prasowych.
Główny przebieg automatycznie wybiera pary embeddingów o podobieństwie
co najmniej 0.86, bez limitu sąsiadów i bez zatwierdzania przez AI. AI następnie
opracowuje tytuł i syntezę/aktualizację. Grupa zaczyna się od najsilniejszej dostępnej pary. Każdy
dołączany element musi osiągnąć próg z co najmniej jednym z tych dwóch
stałych punktów odniesienia; samo połączenie z późniejszym członkiem grupy
nie wystarcza. Pozostałe elementy mogą utworzyć osobne grupy. Szczegóły konfiguracji są w `DEPLOYMENT.md`.

Aktualizacje powstają tylko wtedy, gdy nowe artykuły dodają fakty do syntezy
i całej wcześniejszej historii. Wynik `NO_NEW_INFORMATION` zachowuje artykuły
w źródłach bez nowego tekstu i oznaczenia aktualizacji. Widoczne aktualizacje
mają datę i godzinę czasu polskiego. Starsze teksty można przebudować według
[instrukcji jednorazowej naprawy](REBUILD_TOPIC_UPDATES.md).
Aktualizacje są składane z pojedynczych faktów po osobnej kontroli nowości,
bez ponownego generowania całej narracji. Logi naprawy pokazują tytuły wątków.

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
TVN24 korzysta z jawnie skonfigurowanych sekcji `/swiat` i `/polska`; kandydatami
są wyłącznie artykuły tego serwisu z końcówką URL `-st<id>`, z pominięciem
poddomeny Eurosportu oraz materiałów sportowych i pogodowych.
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

Harvester zbiera linki z RSS/Atom, news sitemap, sitemap, skonfigurowanych
sekcji i strony głównej jako fallbacku. Zapisuje artykuły do SQLite oraz
eksportu JSONL/HTML:

```bash
python3 article_harvester.py --browser
```

Treść krótsza niż 100 słów nie trafia do eksportu ani do tabeli artykułów.
Adres odrzuconego materiału jest zapamiętywany technicznie, żeby nie pobierać
go ponownie. Opcja `--retry-rejected` pozwala świadomie spróbować ponownie.
Poza deduplikacją po znormalizowanym adresie URL harvester rozpoznaje także
duplikaty tego samego źródła po znormalizowanym tytule i pierwszych dwóch
zdaniach. Jeśli tytuł jest taki sam, ale pierwsze dwa zdania są inne, artykuły
pozostają osobnymi rekordami.

### Jak czytać logi przebiegu

Logi używają krótkich prefiksów: `[RUN]` oznacza cały przebieg, `[HARVEST]`
pobieranie źródeł, `[AI]` analizę tematów, a `[SYNC]` synchronizację z Supabase.
W podsumowaniu harvestera:

- `już zapisane` — adres artykułu był już w bazie, więc nie pobierano go ponownie;
- `wcześniej odrzucone jako za krótkie` — adres był wcześniej sprawdzony i zapisany na liście odrzuconych;
- `odrzucone teraz jako za krótkie` — pobrany materiał nie przekroczył minimalnej długości;
- `duplikaty` — materiał został pobrany, ale treść odpowiadała już zapisanemu artykułowi;
- `błędy` — pobieranie albo zapis konkretnego materiału zakończyły się błędem.

Etap syntez pokazuje postęp w formacie `ukończone/łącznie` oraz liczbę tematów
pozostałych do wykonania. Surowe odpowiedzi AI nie są wypisywane do konsoli;
w przypadku błędu można je znaleźć w historii `topic_runs`.

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

W głównym workflow etap nadawania nazw odrzuca również artykuły spoza zakresu
(sport, zwykła prognoza pogody, celebryci, rozrywka, lifestyle i inne treści
bez istotnego znaczenia publicznego). Decyzja korzysta z istniejącego zapytania
AI, na podstawie tytułu i pierwszych 100 słów. Katastrofy oraz istotne skutki
społeczne, gospodarcze i decyzje władz pozostają w zakresie. Odrzucone materiały
pozostają w bazie z `topic_hint = AI_EXCLUDED:<kategoria>:<powód>`, nie otrzymują
kandydata wątku i nie wracają do kolejnego AI-only. W logach etapu 1 widać
liczbę odrzuceń, a w `topic_runs` etapu `LABELING` — decyzje i uzasadnienia.
Filtr dotyczy nowo analizowanych artykułów; nie usuwa istniejących wątków.

Logi tworzenia embeddingów i automatycznego scalania mają prefiks `[EMBEDDING]`;
`[AI]` oznacza etapy generowania tekstu. Przy niepoprawnej lub uciętej
odpowiedzi log pokazuje zwrócony tekst (do 6000 znaków: dla dłuższej
odpowiedzi początek i koniec), status, powód przerwania, model, limit tokenów
i zużycie tokenów rozumowania. Kategorie pokazują te dane także przed
podziałem paczki. Pusta odpowiedź jest oznaczona wprost; `max_output_tokens`
może oznaczać wyczerpanie budżetu na rozumowanie, zanim powstanie JSON.

Poprawianie nazwy wątku (również po scaleniu) wysyła do AI tylko obecną
nazwę, jednozdaniowy opis, jeśli istnieje, i maksymalnie cztery tytuły
artykułów oraz identyfikator do przypisania odpowiedzi. Nie wysyła fragmentu
syntezy ani początków artykułów.

Zapis pierwszej syntezy odświeża `last_seen_at` aktywnego wątku: jest widoczny
w Aktualnych przez kolejne 24 godzin od pierwszej publikacji, także gdy
AI-only nadrabia starsze artykuły. Ponowna analiza istniejącej syntezy bez
nowych informacji nie odświeża tego czasu. Już zapisane pierwsze syntezy
z ostatnich 24 godzin można naprawić jednorazowo skryptem
`supabase_repair_first_synthesis_current.sql`.

Kolejka syntez i aktualizacji w głównym przebiegu oraz AI-only kwalifikuje
tylko aktywne wątki z `last_seen_at` z ostatnich 48 godzin. Brak lub błędna
data wyklucza generowanie. Limit jest sprawdzany przy budowie kolejki
i ponownie przed zapytaniem do AI, aby nie generować dla wątków, które
przekroczyły go podczas oczekiwania. W logach pominięcia mają tytuł i powód.

W głównym przebiegu kategorie są uzupełniane po syntezach i aktualizacjach.
Kategorie zwrócone i zapisane wraz z syntezą nie wymagają osobnego zapytania.
Końcowy klasyfikator obejmuje tylko kwalifikujące się wątki, które nadal
nie mają kategorii, zachowując wcześniejsze przypisania.

Nadawanie nazw używa schematu odpowiedzi z obowiązkowym wpisem dla każdego
konkretnego `article_id` z paczki (`decisions`), zamiast dwóch list dowolnej
długości. Każdy wpis ma decyzję KEEP z nazwą albo kategorię odrzucenia
z uzasadnieniem. Kod sprawdza kompletność przed jakimkolwiek zapisem
artykułów lub kandydatów. Niepoprawne decyzje zapisują surową odpowiedź
i szczegóły błędu w historii LABELING oraz w logach.

Syntezy i aktualizacje w głównym przebiegu oraz AI-only są generowane
od wątków z największą łączną liczbą unikalnych podpiętych artykułów.
Przy remisie pierwszeństwo ma nowsze `last_seen_at`, a następnie identyfikator
wątku dla stabilnej kolejności. Liczba nowych artykułów nie zmienia priorytetu.

Pierwsze syntezy zawierają w `background_context` osobny punkt dla każdej
nazwanej osoby i organizacji pojawiającej się w syntezie lub faktach, z
krótkim opisem funkcji/roli albo działalności. Dalej może pojawić się szersze
tło historyczne, prawne i społeczne, bez powtarzania narracji. Objaśnienia
z artykułów mają przypisane źródła; wiedza ogólna i niepewne role są oznaczone
`needs_verification=true`. Aktualizacje nadal zachowują istniejącą bazową
syntezę i kontekst. Zmiana promptu dotyczy kolejnych generowanych syntez.
