# Jednorazowe wygenerowanie aktualizacji od nowa

Naprawa obejmuje wyłącznie wątki ze statusem `ACTIVE`, w których ostatni
artykuł pojawił się **mniej niż 55 godzin temu** (`last_seen_at`) i które mają
**co najmniej dwie widoczne aktualizacje**, liczone bez duplikatów także
z historii wersji. Synteza bazowa nie liczy się jako aktualizacja, podobnie
jak techniczne decyzje `NO_NEW_INFORMATION`. Wątki z jedną aktualizacją
pozostają bez zmian. Opcjonalny `topic_id` również podlega tym filtrom.
Zakres ustalany jest przy tworzeniu kopii przed wywołaniami AI.

Skrypt `rebuild_topic_updates.py` poprawia istniejące aktualizacje, korzystając
z obecnego promptu w `ai_pipeline.py`. Nie regeneruje syntezy bazowej ani nie
zmienia powiązań artykułów, kategorii, dat i numerów wersji. Jeśli wątek ma dwie
aktualizacje, obie są oceniane kolejno: pierwsza na podstawie swoich artykułów
i syntezy bazowej, a druga na podstawie swoich artykułów, syntezy bazowej
i **nowych ustaleń pierwszej aktualizacji**, jeżeli takie były. Analogicznie
działa dla kolejnych. Każda pierwotna paczka artykułów pozostaje zapisana.

Nowy tekst powstaje tylko przy statusie `NEW_INFORMATION`. Jeśli artykuły nie
dodają nowych faktów, model zwraca `NO_NEW_INFORMATION` z pustym tekstem:
taki rekord zachowuje artykuły i datę, ale nie jest widoczny jako aktualizacja
ani oznaczenie na stronie. Nie powstaje nawet krótkie potwierdzenie znanych
ustaleń. Dlatego po naprawie liczba **widocznych** aktualizacji może być mniejsza.
Oryginalne `new_article_ids`, `run_id`
i `generated_at` każdej aktualizacji pozostają zachowane. Skrypt uwzględnia
również aktualizacje przechowywane tylko w historii wersji, które pokazuje
interfejs. Nie tworzy dodatkowych aktualizacji dla samej naprawy.

## Uruchomienie z telefonu przez GitHub Actions

1. Otwórz projekt w Supabase, wybierz **SQL Editor → New query**. Skopiuj całą
   zawartość `supabase_migration_rebuild_updates.sql` z tego repozytorium
   i kliknij **Run**. To jednorazowa instalacja funkcji bezpiecznego zapisu;
   samo wykonanie SQL nie regeneruje tekstów ani nie zmienia aktualizacji.
2. Na GitHubie otwórz repozytorium → **Actions → Rebuild topic updates once**
   → **Run workflow**. Wybierz gałąź `main`. Zostaw `apply` zaznaczone,
   a `topic_id` i `resume_run_id` puste, aby przebudować aktywne wątki
   z co najmniej dwiema aktualizacjami. Kliknij zielone **Run workflow**.

Workflow korzysta z istniejących sekretów `SUPABASE_URL`, `SUPABASE_SECRET_KEY`
i `OPENAI_API_KEY` oraz zmiennej `OPENAI_MODEL`. Nie trzeba przesyłać kluczy
ani wpisywać ich do skryptu. To ręczny workflow bez harmonogramu.

Po zakończeniu odśwież dane na stronie. Każdy zakończony wątek jest poprawiany
od razu; nie trzeba czekać na zakończenie pozostałych wątków.

## Kopia i wznawianie

Przed pierwszym wywołaniem AI workflow zapisuje kopię do artefaktu
**original-topic-updates**. Po pracy zapisuje teksty i checkpoint do artefaktu
**rebuilt-topic-updates**. Pobierz je z podsumowania uruchomienia; są
przechowywane przez 30 dni. Zawierają wcześniejsze syntezy i aktualizacje,
bez kluczy API i bez pełnych treści artykułów.

Jeżeli uruchomienie przerwie się, ponownie uruchom workflow i w polu
`resume_run_id` wpisz numer poprzedniego uruchomienia widoczny w jego adresie
`.../actions/runs/NUMER`. Użyj tego samego modelu i zakresu `topic_id`.
Wątki już zapisane są pomijane; gotowe teksty oczekujące na zapis są używane
ponownie. Wznowienie zachowuje zakres z pierwotnej kopii, bez ponownego
przesuwania okna 55 godzin. Checkpointy utworzone przed wprowadzeniem tych
filtrów są odrzucane: dla tej naprawy zostaw `resume_run_id` puste.
Jeżeli przerwanie nastąpiło podczas generowania danego wątku,
skrypt wygeneruje jego aktualizacje ponownie od początku.
W wersji z kontrolą atomowych faktów poprawki formatu odpowiedzi pozwalają
wznowić dotychczasowy checkpoint tego samego promptu. Błędy identyfikacji
historii są ponownie sprawdzane przy wznowieniu, bez otwierania zakończonych
wątków. Jeśli normalny run zmienił w międzyczasie dane wątku, bezpieczny zapis
odmówi nadpisania; taki wątek wymaga nowej kopii.

Przy wznowieniu kopia w nowym artefakcie zachowuje także oryginalne dane
z pierwszego uruchomienia. Nowe uruchomienie **bez** `resume_run_id` rozpoczyna
nową naprawę i ponownie generuje aktualizacje; nie służy do wznowienia.

## Co dzieje się przy błędach

W ramach jednego wątku wszystkie teksty powstają przed podmianą danych.
Nie usuwa się starych aktualizacji na początku pracy. Funkcja SQL zapisuje
bieżący stan i wszystkie istniejące wersje historyczne w jednej transakcji,
więc strona nie odzyska dawnych powtórzeń z historii.

Skrypt nie zgaduje, które artykuły należały do aktualizacji. Brak zapisanych
identyfikatorów, brak treści artykułu albo ten sam `run_id` wskazujący różne
paczki w historii powodują pominięcie wątku i komunikat w logach. Pozostałe
wątki są przetwarzane, a workflow kończy się błędem, jeśli są takie pominięcia.

Workflow współdzieli blokadę z harvesterem, aby nie zmieniać aktualizacji
równocześnie ze zwykłą analizą. Dodatkowo funkcja SQL sprawdza zgodność stanu
z kopią i odmawia nadpisania wątku zmienionego w międzyczasie. Zachowuje
`updated_at`, aby naprawa nie pominęła artykułów oczekujących na zwykłą nową
aktualizację. Funkcję mogą wywołać wyłącznie serwerowe poświadczenia
`service_role`, nie klucz publiczny aplikacji.

Każda istniejąca aktualizacja wymaga zwykle jednego wywołania AI. W razie
braku nowych faktów na tym kończy się ocena. Jeżeli AI wybierze kandydatów,
drugie, osobne wywołanie sprawdza każdy pojedynczy fakt względem całej syntezy,
wszystkich wcześniej przebudowanych aktualizacji i nowych artykułów.
Kod składa tekst wyłącznie z zaakceptowanych faktów, bez kolejnego
generowania narracji. Zdanie łączące nowy fakt ze starymi też jest odrzucane.
Odrzucenie wszystkich faktów daje `NO_NEW_INFORMATION`. Błąd lub niekompletna
kontrola blokuje zapis całego wątku; wcześniejsze poprawnie zapisane wątki
pozostają zapisane. Ocena semantyczna nadal zależy od AI.
Schemat odpowiedzi ogranicza artykuły dowodowe do bieżącej paczki i wymaga
osobnej decyzji dla każdego faktu, również odrzuconego. Błędna selekcja lub
kontrola jest ponawiana raz z opisem błędu. Trwale niepoprawna odpowiedź
nadal blokuje zapis; skrypt nie dopisuje decyzji za AI.

Logi generowania, zapisu i błędów pokazują pełne tytuły wątków, aby można było
znaleźć je na stronie. Każdy zapis podaje liczbę ocenionych aktualizacji i liczbę
widocznych po naprawie. W checkpointach zapisane są również wybrane fakty
i decyzje kontroli nowości (`novelty_audit`).

## Uruchomienie lokalne

Ustaw zmienne środowiskowe jak dla zwykłego pipeline'u i zainstaluj
`requirements.txt`. Najpierw wykonaj powyższą migrację SQL. Następnie:

```bash
# Kopia i podgląd zakresu — bez wywołań AI i bez zmian w bazie:
python rebuild_topic_updates.py

# Wygenerowanie i zapis; istniejący checkpoint wznawia tę samą naprawę:
python rebuild_topic_updates.py --apply

# Opcjonalnie jeden wątek, z osobnym plikiem stanu:
python rebuild_topic_updates.py --topic-id topic_ID --state repair-one.json --apply
```

Nie uruchamiaj lokalnej naprawy równocześnie ze zwykłą analizą. Nie dodawaj
pliku kopii/checkpointu do repozytorium. Domyślny plik
`topic-update-rebuild.json` jest objęty `.gitignore`.
