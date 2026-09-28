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
- `HARVEST_DAILY_MAX_ARTICLES_PER_SOURCE`, domyślnie `50`; jest to limit
  nowych prób pobrania na źródło w całym dniu UTC, wspólny dla trzech
  uruchomień. Wartość `0` oznacza brak limitu i nie jest zalecana;
- `AI_MAX_ARTICLES_PER_RUN`, domyślnie `100`. Pozostałe nieprzypisane artykuły
  czekają w Supabase na następne uruchomienia, żeby pierwszy cykl nie zużył
  niekontrolowanej liczby wywołań API.
- `AI_BATCH_SIZE`, domyślnie `50`; większe paczki grupowania są automatycznie
  ograniczane do 50, żeby odpowiedź JSON nie była zbyt długa.

## Pierwsze uruchomienie

Po zapisaniu schematu kliknij w repozytorium `Actions -> Global News Intelligence
— harvest and analysis -> Run workflow`. Pierwsze uruchomienie można obserwować
w logach. Zaczyna od pobrania istniejącego stanu z Supabase, więc nie powinno
ponownie pobierać artykułów zapisanych wcześniej lokalnie.

Jeżeli artykuły są już w Supabase, a chcesz ponowić tylko grupowanie i
opracowania AI, w formularzu `Run workflow` wybierz tryb `ai-only`. Ten tryb
nie odwiedza źródeł i korzysta z artykułów oczekujących w bazie.

## Harmonogram

Workflow uruchamia się trzy razy dziennie o `06:17`, `12:17` i `18:17` UTC.
GitHub Actions pokazuje czas w UTC. Harmonogram nie jest związany z laptopem —
działa także wtedy, gdy komputer jest wyłączony.
