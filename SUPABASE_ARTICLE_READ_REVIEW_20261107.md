# Timeout początkowego odczytu artykułów — 7 listopada 2026

[Przebieg 42381995231](https://github.com/patrycjap08/global-news-intelligence/actions/runs/42381995231)
zatrzymał się na etapie 1/4 przy `GET articles`. Supabase zwrócił HTTP 500
z PostgreSQL `57014`: `canceling statement due to statement timeout`.
Trzy próby zakończyły się błędem. Harvester, AI i eksport danych nie ruszyły.
Ten przebieg nie generował płatnych odpowiedzi AI ani nie zmieniał publikacji.

To błąd wykonania zapytania SQL, odrębny od HTTP 401 z tokenem harmonogramu
oraz wyczerpanego salda OpenAI. Serwer przerwał zapytanie po swoim limicie
czasu. Sam dłuższy timeout klienta HTTP nie zmienia tego limitu.

## Odczyt przed zmianą

Przy starcie tymczasowej maszyny `pull_state` odtwarza lokalny stan z bazy.
Pobiera całe archiwum artykułów wraz z pełnymi treściami. `select_all`
żądał po 1000 rekordów i zwiększał `OFFSET` na kolejnych stronach.
Duże dokumenty wymagają serializacji, a OFFSET wymaga pomijania coraz
większej liczby poprzednich rekordów. To zbędny koszt rosnącego archiwum.

Log nie zawiera planu SQL ani numeru strony. Nie dowodzi więc, że jedyną
przyczyną były OFFSET lub wielkość paczki; przeciążenie, blokady i dostępność
projektu wymagają osobnej diagnostyki po stronie Supabase.

## Zmiana

- Pełny odczyt `articles` z kolejnością `article_id.asc` korzysta z kursora:
  następna strona ma `article_id > ostatni_odczytany_id`. Używa istniejącego
  klucza głównego; nie wymaga indeksu ani migracji SQL.
- Domyślna paczka ma 250 rekordów. `SUPABASE_ARTICLE_READ_PAGE_SIZE` może
  ustawić rozmiar od 1 do 1000 w środowisku procesu. Bez konfiguracji działa 250.
- Dla tego odczytu `57014` trafia od razu do obsługi zmiany wielkości paczki.
  Zamiast trzykrotnie ponawiać identyczne ciężkie zapytanie, klient dzieli
  limit przez dwa i wraca do tego samego kursora. Po sukcesie pozostaje przy
  zmniejszonej wielkości. Gdy nawet jeden rekord kończy się timeoutem, zgłasza błąd.
- Krótka strona nie oznacza końca archiwum. Projekt może mieć niższy limit
  wyników API. Odczyt kończy się po pustej stronie, z kontrolą porządku i
  postępu identyfikatorów. Błędna odpowiedź nie staje się pustym archiwum.
- Log podaje sposób odczytu, zmniejszenie paczki i postęp co 20 stron.
  Nie zawiera kluczy ani pełnych treści.

Pozostałe odczyty, zapytania po konkretnych ID, polityka retry innych błędów,
zapisy do bazy oraz limity czasu po stronie serwera pozostają bez zmian.
Kolumny artykułów, pełne treści, deduplikacja i wejście do AI są takie same.
Modele, prompty, cache ekstrakcji, harmonogram i zasady publikacji nie zmieniają się.

## Bezpieczeństwo i weryfikacja

Niepełny odczyt nadal zatrzymuje cały proces przed harvesterem, AI i eksportem.
Poprawka nie przyjmuje częściowej listy jako kompletnego stanu deduplikacji.
Nie usuwa danych i nie uruchamia ponownego generowania zapisanych syntez.

Testy odtwarzają rzeczywiste parametry zapytań HTTP: pełne treści na wielu
stronach, niższy limit wyników serwera, timeout po częściowym odczycie,
zmniejszanie paczek bez pomijania danych, trwały timeout przy jednym rekordzie,
powtórzone/nieuporządkowane ID, błędną strukturę odpowiedzi, HTTP 401 i inne
błędy 500. Osobno sprawdzają kompletny zapis początkowego stanu do SQLite
oraz zatrzymanie pipeline'u przed płatnym AI przy błędzie `57014`.

Testy działają offline, bez produkcyjnych kluczy, zapisu do Supabase i wywołań
OpenAI. Nie zmierzono jeszcze czasu odczytu produkcyjnego po poprawce.

Weryfikacja: cały zestaw **497 testów Python — OK**, w tym 9 nowych regresji
odczytu archiwum. Po doprecyzowaniu przypadku trwałego timeoutu po częściowym
odczycie ponownie uruchomiono 9 testów tego odczytu — OK.

## Następne uruchomienie

Nowy przebieg musi korzystać z nowego commita na `main`. Opcja re-run starego
przebiegu zachowuje stary kod. Jeżeli pobieranie stanęło przed harvesterem,
tryb `full` pobierze brakujące nowe artykuły; `ai-only` ich nie pobiera.
Reset bazy ani usuwanie zapisanych wyników nie są potrzebne.

Jeśli błąd utrzyma się przy małych stronach, należy sprawdzić logi zapytań,
blokady i zasoby projektu. Sama paginacja nie naprawia niedostępności bazy.
