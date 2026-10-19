# Perspektywy redakcyjne — format 1

Zmiana obejmuje generowanie, aktualizacje, eksport Pages i interfejs. Nie zmienia
klasyfikacji redakcji, modelu OpenAI, progów embeddingów ani historycznych syntez.
Nie wymaga migracji SQL. Profil źródła nie oznacza oceny prawdziwości publikacji.

## Reguły

- LEFT/CENTER_LEFT to lewica; RIGHT/CENTER_RIGHT to prawica; CENTER to centrum.
- STATE_ALIGNED lub STATE_MEDIA to media kontrolowane przez państwo.
  Sam source_type=GOVERNMENT_AGENCY nie oznacza kontroli; agencja publiczna
  z przypisanym zwykłym profilem zachowuje ten profil.
- Niesklasyfikowane źródło zatrzymuje wygenerowanie danego opracowania z błędem
  opisującym źródło. Nie przyznajemy mu milcząco statusu centrum.
- Fakt z centrum albo z lewicy i prawicy jest wspólny. Sam materiał państwowy
  nie potwierdza informacji do wspólnej części. Liczą się wskazane artykuły
  podające konkretne ustalenie, a nie wspólny temat nagłówków.
- Gdy wszystkie niepaństwowe artykuły są jednej grupy, synteza/fakty obejmują
  tę grupę, a nad tytułem pojawia się informacja o jednostronnej podstawie.
  Ewentualne dodatkowe doniesienia państwowe zostają osobno.
- Bez wspólnych ustaleń brak zakładek Synteza/Fakty; widoczny jest komunikat
  „Źródła o różnych profilach nie podają wspólnych informacji”. Przy samych
  państwowych materiałach komunikat wskazuje ich wyłączną obecność.
- Puste perspektywy są ukrywane. Pozostałe części to kontekst i źródła.
  Usunięcie z widoku różnic/sprzeczności/sygnałów nie usuwa danych z bazy.
- Pasek na karcie i w oknie tematu liczy artykuły, także kilka jednej redakcji;
  państwowe i niesklasyfikowane nie należą do mianownika ani segmentów.
- Aktualizacja ma wydzielone nowe ustalenia wspólne/lewicowe/prawicowe/państwowe.
  Przejście znanego faktu do części wspólnej daje „Szersze potwierdzenie”.
  Powtórzenie znanych informacji nie tworzy aktualizacji ani nie cofa przeczytania.

## Generowanie i zgodność

Nowa synteza: dwa zapytania w obecnej puli równoległych zadań. Pierwsze wyciąga
atomowe fakty i cytowania; kod wyznacza ich części. Drugie dostaje wyłącznie
fakty dopuszczone do głównej syntezy oraz tytuł i tworzy narrację/kontekst.
Kod sprawdza identyfikatory artykułów, stabilność znanych faktów i odwołania
akapitów/kontekstu. Ocena znaczenia i poprawności przypisań jest zadaniem modelu.

Aktualizacja nowego formatu analizuje wszystkie artykuły wątku z ograniczeniem
rozmiaru payloadu. Zachowuje rejestr dotychczasowych faktów, uzupełnia ich
potwierdzenia i odświeża bieżący widok podziału. Historia aktualizacji pozostaje.
Syntezy starego formatu nadal korzystają ze starego sposobu aktualizacji;
nie przebudowujemy ich automatycznie.

Nowe wątki/kandydaci otrzymują ID topic_perspectives_…; zapisane opracowania
mają perspective_version=1. Nowe artykuły nie są dopasowywane do starych wątków.
Nie ma przepinania wcześniej przetworzonych artykułów ze starych opracowań.

Na końcu full/ai-only jest dodatkowa kontrola embeddingów wszystkich ACTIVE
wątków z syntezami w aktualnym oknie 36 godzin. Wykluczamy krawędzie pomiędzy
wersjami przed tworzeniem grup; jest też kontrola przed zapisem scalenia.
Stare łączą się wyłącznie ze starymi, nowe wyłącznie z nowymi, także w trybie
merge-existing-summaries. Przeniesione artykuły trafiają do kolejki aktualizacji.
Kontrola nie pyta AI o zgodę na scalenie. Kosztem są dodatkowe embeddingi
oraz ewentualne aktualizacje rzeczywiście scalonych tematów.

## Cofnięcie

Całość jest publikowana jako jeden commit pod tytułem:
`Add isolated editorial perspectives and final synthesized-topic deduplication`.
Punktem wyjścia jest commit `74db8f518e72e9388ccee67b8e43f26180511efd`.

Aby cofnąć: wykonać `git revert <SHA tego commita>` i wypchnąć commit cofający.
Zachowuje to historię i uruchamia ponowne wdrożenie Pages. Nie używać reset/force
push ani usuwać danych. Jeżeli po tej zmianie pojawią się inne poprawki, cofamy
wskazany commit, a nie dowolny ostatni commit.

Przy wdrożeniu nie uruchamiamy produkcyjnego AI, harvestera ani migracji.
Cofnięcie przywraca poprzedni kod i reguły; nie usuwa syntez ani scaleń, które
użytkowniczka zdąży później wygenerować produkcyjnym workflow. Rejestr nowych
perspektyw zostaje w JSON i nie wymaga odwracania schematu bazy.

## Weryfikacja

Testy bez płatnego API: podział faktów, centrum, wyjątki, doniesienia państwowe,
walidacja cytowań, potwierdzenia, promocje, zapis i historia, izolacja dopasowań
oraz końcowe scalanie przy silniejszej krawędzi pomiędzy wersjami. Interfejs:
ukrywanie pustej syntezy, niezależne przełączniki, liczniki artykułów, odczyt
oraz pełny/przycięty eksport. Przeglądarka: telefon 390 px i komputer 1280 px.
