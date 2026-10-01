# Uruchomienie produkcyjne

## Jednorazowo w Supabase

1. Otwórz SQL Editor w projekcie Supabase.
2. Wklej całą zawartość `supabase_schema.sql`.
3. Uruchom zapytanie.

To tworzy tabele artykułów, deduplikacji, uruchomień, tematów i podsumowań.
Worker używa `SUPABASE_SECRET_KEY`, który może zapisywać dane mimo RLS. Nie
umieszczaj tego klucza w aplikacji telefonu.

Po wdrożeniu klasyfikacji pokrycia tematów uruchom jednorazowo w SQL Editor
plik `supabase_migration_topic_coverage.sql`. Doda on `topics.coverage_status`
oraz widok `source_topic_coverage` do porównywania źródeł.

Przed kolejnym uruchomieniem klasyfikacji kategorii uruchom jednorazowo
`supabase_migration_topic_category_polska.sql`. Dodaje kategorię `POLSKA` do
dozwolonej listy kategorii w bazie.

Przed kolejnym pełnym uruchomieniem uruchom także jednorazowo
`supabase_migration_topic_merges.sql`. Dodaje on przekierowanie dla tematów,
które AI połączy jako duplikaty. Scalony temat nie jest usuwany — dostaje
status `MERGED`, a aplikacja pokazuje nowy temat zbiorczy.

Uruchom również jednorazowo `supabase_migration_historical_topics.sql`.
Udostępnia on aplikacji tematy starsze niż 30 godzin, aby mogły pojawić się
w zakładce „Historyczne”. Tematy `MERGED` nadal pozostają ukryte.

Po wdrożeniu rozdzielenia widoczności od dopasowywania uruchom także
`supabase_migration_topic_current_window.sql`. Aplikacja pokazuje temat jako
aktualny przez 30 godzin bez aktualizacji, ale backend może nadal dopasować do
niego nowe artykuły przez 55 godzin. Po takim dopasowaniu temat wraca do
zakładki „Aktualne”.

## Sekrety repozytorium

W GitHubie wejdź w `Settings -> Secrets and variables -> Actions` i upewnij się,
że istnieją dokładnie:

- `OPENAI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY`
- `SUPABASE_PUBLISHABLE_KEY`

Wartość `SUPABASE_URL` ma postać `https://<project-ref>.supabase.co`.

Opcjonalnie w `Settings -> Secrets and variables -> Actions -> Variables` można
dodać:

- `OPENAI_MODEL`, domyślnie `gpt-4o-mini`;
- dzienny limit prób pobrania jest wyłączony; każde uruchomienie sprawdza
  własne okno najnowszych artykułów, a znane adresy pomija przez deduplikację;
- `AI_MAX_ARTICLES_PER_RUN`, domyślnie `100`. Pozostałe nieprzypisane artykuły
  czekają w Supabase na następne uruchomienia, żeby pierwszy cykl nie zużył
  niekontrolowanej liczby wywołań API.
- `AI_BATCH_SIZE`, domyślnie `50`; większe paczki grupowania są automatycznie
  ograniczane do 50, żeby odpowiedź JSON nie była zbyt długa.
- `AI_TOPIC_MERGE_MAX_REQUESTS`, domyślnie `20`; limit paczek do weryfikacji
  scalania w jednym przebiegu. Kod wymusza maksymalnie 20 także wtedy, gdy
  starsza zmienna repozytorium nadal ma wartość 80. Można ustawić mniej.
- `AI_TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY`, domyślnie `0.90`; minimalne
  podobieństwo cosinusowe kandydatów semantycznych (wcześniej 0.84).
  Kod nie dopuszcza wartości poniżej 0.90; można podwyższyć próg.
- `AI_TOPIC_MERGE_EMBEDDING_TOP_K`, domyślnie `3`; maksymalnie trzech
  sąsiadów semantycznych na temat (wcześniej pięciu). Można ustawić mniej.
- `AI_TOPIC_MERGE_MAX_RECENT_TITLES`, domyślnie `1`; liczba najnowszych tytułów
  przekazywanych do scalania, żeby duże komponenty nie przekraczały kontekstu.
- `OPENAI_REQUEST_TIMEOUT_SECONDS`, domyślnie `90`; maksymalny czas oczekiwania
  na pojedynczą odpowiedź OpenAI.
- `AI_SUMMARY_REQUEST_TIMEOUT_SECONDS`, domyślnie `180`; osobny timeout dla
  generowania i aktualizacji syntez.
- `AI_SUMMARY_MAX_PAYLOAD_CHARS`, domyślnie `300000`; po przekroczeniu tej
  wielkości treści artykułów są automatycznie skracane do wyciągów.
- `AI_SUMMARY_FALLBACK_EXCERPT_WORDS`, domyślnie `900`; początkowa długość
  wyciągu używanego dla dużych tematów.
- `AI_CATEGORY_BATCH_SIZE`, domyślnie `30`; liczba tematów w jednej paczce
  klasyfikacji kategorii.
- `AI_CATEGORY_REQUEST_TIMEOUT_SECONDS`, domyślnie `45`; timeout klasyfikacji
  kategorii. Po błędzie zbyt duża paczka jest automatycznie dzielona.

## Pierwsze uruchomienie

Po zapisaniu schematu kliknij w repozytorium `Actions -> Global News Intelligence
— harvest and analysis -> Run workflow`. Pierwsze uruchomienie można obserwować
w logach. Zaczyna od pobrania istniejącego stanu z Supabase, więc nie powinno
ponownie pobierać artykułów zapisanych wcześniej lokalnie.

Jeżeli artykuły są już w Supabase, a chcesz ponowić tylko grupowanie i
opracowania AI, w formularzu `Run workflow` wybierz tryb `ai-only`. Ten tryb
nie odwiedza źródeł i korzysta z artykułów oczekujących w bazie.

Jeżeli istniejące syntezy zostały rozdzielone na kilka osobnych wątków, w
formularzu `Run workflow` wybierz tryb `merge-existing-summaries`. Ten tryb
analizuje tylko aktywne wątki z ostatnich 55 godzin, które mają już zapisaną
syntezę. Najpierw lokalnie tworzy paczki podobnych wątków, potem AI zatwierdza
scalenia. Po scaleniu zachowywana jest najstarsza synteza, a nowe artykuły są
przekazywane do osobnego wywołania AI jako aktualizacja tej syntezy. Wątki
historyczne pozostają poza tym trybem. Opcjonalna zmienna
`AI_EXISTING_TOPIC_MERGE_MAX_TOPICS` ogranicza liczbę analizowanych wątków;
`0` oznacza wszystkie aktywne wątki z syntezami.

W zwykłym trybie po grupowaniu nowych artykułów działa dodatkowy szybki etap
scalania podobnych aktywnych tematów, a dopiero potem generowane są syntezy.

Publikacja wyników jest stopniowa: każdy wygenerowany tekst jest od razu
zapisywany w Supabase. Po odświeżeniu danych aplikacja pokazuje gotowe syntezy
bez czekania na zakończenie całego przebiegu. Wątki spełniające kryteria źródeł
mogą być widoczne także przed wygenerowaniem opisu. Brak syntezy nie stanowi
dodatkowego warunku ukrywania wątku.

Filtr leksykalny wymaga trzech wspólnych charakterystycznych rdzeni słów
albo jednej wspólnej frazy z dwóch takich słów. Niezależne grupy kandydatów
są pakowane razem, do 100 tematów na paczkę; AI porównuje wyłącznie tematy
w obrębie tej samej grupy. Nakładające się grupy zachowują osobne paczki.
Limit 20 obejmuje paczki weryfikacji scalania, nie etykietowanie, embeddingi,
kategorie ani syntezy. Retry po błędzie API może ponowić tę samą paczkę.
To zmniejsza liczbę porównań, ale słabiej podobne relacje mogą pozostać osobno.

## Aktualizacje bez powtarzania faktów

Model porównuje nowe materiały z syntezą bazową i wszystkimi wcześniejszymi
aktualizacjami. Prompt wymaga opisywania tylko nowych ustaleń, szczegółów lub
korekt; parafraza i kolejne źródło tego samego faktu nie są nową informacją.
Gdy artykuły wyłącznie potwierdzają znane ustalenia, aktualizacja powinna
zawierać jedno krótkie potwierdzenie bez ponownego wyliczania szczegółów.
Ta zasada obowiązuje również podczas ponownego generowania odpowiedzi
w trybie naprawy. Nie zmienia wcześniej zapisanych tekstów.

## Usunięta integracja X

Worker i aplikacja nie pobierają ani nie dopasowują wpisów z X. Nie ma już
opcji `include_x` ani workflow testującego konto. Sekret `X_BEARER_TOKEN`
nie jest używany i można go usunąć w ustawieniach GitHuba.

Istniejąca baza nie wymaga zmian, aby nowy kod działał. Opcjonalny
`supabase_migration_remove_x.sql` usuwa dawne surowe wpisy, konta,
powiązania i widoki X. Wcześniej zapisane teksty syntez i historia pozostają
zachowane; migracja nie przepisuje historycznych opracowań.

## Harmonogram

Workflow uruchamia się dwa razy dziennie o `07:17` i `16:17` czasu
`Europe/Warsaw`. GitHub Actions obsługuje tę strefę i uwzględnia zmianę czasu
letniego/zimowego. Harmonogram nie jest związany z laptopem — działa także
wtedy, gdy komputer jest wyłączony.
