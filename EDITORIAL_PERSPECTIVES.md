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

Nowa synteza: co najmniej dwa zapytania w obecnej puli równoległych zadań.
Pierwszy etap wyciąga atomowe fakty i cytowania z pełnych artykułów; przy dużym
zestawie wykonuje kolejne paczki, a każda widzi ustalenia z poprzednich.
Kod wyznacza ich części. Drugie dostaje wyłącznie
fakty dopuszczone do głównej syntezy oraz tytuł i tworzy narrację/kontekst.
Kod sprawdza identyfikatory artykułów, stabilność znanych faktów i odwołania
akapitów/kontekstu. Ocena znaczenia i poprawności przypisań jest zadaniem modelu.

Aktualizacja nowego formatu analizuje wszystkie artykuły wątku. Limit
AI_SUMMARY_MAX_PAYLOAD_CHARS (domyślnie 300000 znaków) jest celem rozmiaru
paczki, a nie limitem treści. Artykuły nigdy nie są zastępowane wyciągami ani
metadanymi w analizie syntez i faktów. Pojedynczy artykuł przekraczający cel
przekazywany jest w całości; jeśli przekroczy twardy limit modelu, analiza
kończy się błędem zamiast zapisać niepełne opracowanie. Stare aktualizacje
również analizują całe artykuły w paczkach i przekazują zaakceptowane
aktualizacje z poprzednich paczek do następnych. Zapis następuje dopiero po
przejściu wszystkich paczek. Zachowuje rejestr dotychczasowych faktów, uzupełnia ich
potwierdzenia i odświeża bieżący widok podziału w osobnym perspective_state. Historia aktualizacji pozostaje.
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

Korekta pod tytułem `Preserve full article texts in synthesis and update batches`
usuwa skracanie tekstów. Przy cofaniu całego formatu perspektyw należy najpierw
cofnąć tę późniejszą korektę, a następnie commit wprowadzający perspektywy.
Korekta nie zmienia modelu embeddingów ani zasady odświeżania bieżącej syntezy.

## Niezmienna synteza po publikacji

Korekta `Keep published syntheses immutable during topic updates` wyłącza
ponowne pisanie syntezy i kontekstu przy KAŻDEJ późniejszej analizie nowego
formatu, także po scaleniu. Wywołanie perspective_summary występuje wyłącznie
przy pierwszym opracowaniu. Później wykonywane jest tylko wyciąganie faktów
z pełnych artykułów w paczkach. Brak nowych ustaleń oznacza brak aktualizacji.

base_summary pozostaje dokładną kopią poprzednio opublikowanego opracowania.
Bieżące fakty, cytowania, podział i perspektywy znajdują się w osobnym
perspective_state. Jest przekazywany następnej analizie, aby ta nie odkrywała
ponownie informacji już dopisanych wcześniej. Interfejs i eksport łączą
pierwotny tekst/kontekst z bieżącymi faktami i perspektywami.

Jeśli pierwotnie nie było wspólnych faktów i tekst syntezy jest pusty, późniejsze
szersze potwierdzenie udostępnia wspólne fakty i aktualizację, bez tworzenia
nowej syntezy. Widoczna jest wtedy tylko zakładka Fakty. Bez wspólnych informacji
wciąż nie ma obu zakładek, zgodnie z wcześniejszym ustaleniem. Jeśli pierwotna
synteza była jednostronna, komunikat zachowuje informację o jej pierwotnej
podstawie również po pojawieniu się innych profili.

Korekta nie przywraca automatycznie wcześniejszych historycznych wersji już
przepisanych syntez. Od momentu zastosowania zachowuje ich obecny zapis.
Nie zmienia modelu embeddingów ani progów. Przy cofaniu całego formatu cofnąć
korekty w odwrotnej kolejności, przed commitem wprowadzającym perspektywy.
