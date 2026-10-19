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

## Kompletność i atomowość faktów

Korekta `Extract complete atomic facts with per-article coverage` precyzuje
ekstrakcję w dotychczasowym zapytaniu. Model ma przejrzeć każdy pełny artykuł,
w tym dalsze akapity, zebrać istotne działania, decyzje, okoliczności, skalę,
reakcje i skutki, a następnie porównać każde ustalenie ze wszystkimi artykułami
paczki. Jedno ustalenie to jedno samodzielnie sprawdzalne twierdzenie;
wspólna informacja i szczegół występujący tylko w części źródeł są rozdzielane.
Nie ma minimalnej ani narzuconej liczby faktów. Parafrazy nie tworzą duplikatów.

Wymagane article_coverage potwierdza przejrzenie każdego artykułu lub podaje
powód braku istotnych informacji o wydarzeniu. Od v62 kod sam wylicza indeksy
ustaleń z facts[].article_ids. Odrzuca odpowiedź pomijającą artykuł; nie publikuje jej
częściowo i nie uruchamia dodatkowego zapytania naprawczego. Log odpowiedzi
podaje liczbę ustaleń, artykułów, potwierdzeń oraz zakres ustaleń na artykuł.
Kontrola nie dowodzi prawdziwości ani semantycznej kompletności odpowiedzi;
te nadal zależą od modelu. Znane potwierdzenia nie tworzą aktualizacji.

Rozbieżne liczby wymagają zachowania źródła, czasu i zakresu: osiem zatrzymań
w jednym zdarzeniu nie musi przeczyć dziesięciu łącznie w dwóch zdarzeniach.
Pierwszy tekst syntezy dostaje nazwy redakcji i daty tylko materiałów
potwierdzających dopuszczone fakty, aby móc czytelnie opisać rozbieżności.
Nie otrzymuje tekstów ani ustaleń pozostałych perspektyw.

Bez zmiany modelu, progów embeddingów, reguł profili i niezmienności
opublikowanej syntezy. Większa kompletność może zwiększyć liczbę tokenów
odpowiedzi. Dotychczasowych opracowań nie przebudowujemy automatycznie;
nowe instrukcje dotyczą kolejnych analiz, bez migracji i produkcyjnych wywołań
przy wdrażaniu. Cofnięcie tego commita przywraca poprzednią ekstrakcję.

## Identyfikatory faktów i źródeł

Korekta `Constrain perspective evidence IDs and add targeted AI rollback SQL`
ogranicza identyfikatory w ścisłym schemacie odpowiedzi. Przy pierwszej
ekstrakcji known_fact_id może być tylko pusty. Przy potwierdzeniu znanego
faktu model wybiera istniejący identyfikator i zwraca pusty text_pl; kod
sam zachowuje oryginalny tekst. Nowe fakty nadal wymagają własnej treści
i uzasadnienia nowości. Nie rozluźniamy weryfikacji zmienionych twierdzeń.

Schemat pierwszej syntezy dopuszcza w kontekście tylko article_ids materiałów
potwierdzających wspólne fakty. fact_ids akapitów też mają zamknięty zbiór.
Bez takich materiałów listy cytowań muszą być puste, a wiedza ogólna wymaga
needs_verification=true. Weryfikacja w kodzie pozostaje dodatkową kontrolą.
W razie błędu walidacji zapisujemy także odpowiedź i nazwę etapu w topic_runs;
wcześniej zwykły ValueError nie zachowywał tych danych. Nie zwiększamy liczby
zapytań ani nie zmieniamy opublikowanych syntez.

`sql_rollback_ai_20261019T080527Z.sql` to jednorazowy skrypt wyłącznie dla
wskazanego przebiegu, z metadanymi i 162 powiązaniami 13 starych wątków
z archiwalnego eksportu 2026-10-19 04:18:57 UTC (artefakt 12162828048).
Przywraca ich syntezy z zachowanych wersji, usuwa 286 nowych kandydatów
i decyzje wykluczenia 142 artykułów, zachowuje pobrane artykuły i harvest.
Prywatna kopia cofanych danych trafia do gni_recovery.ai_rollbacks.
Skrypt odmawia wykonania po nowszym harveście/analizie lub przy braku historii.
Nie odtwarza dokładnych technicznych dat starych przypisań, których eksport
nie zawiera; ustawia je nie później niż poprzednia analiza, aby samo cofnięcie
nie tworzyło aktualizacji. input_hash przywróconej starszej wersji dostaje
znacznik odtworzenia, jeśli nie zachowano poprzedniego hasha.

Po SQL uruchomić NOWE ai-only na aktualnym main, a nie Re-run jobs starego
uruchomienia, które odtwarzałoby stary commit. Pobrane artykuły kwalifikują się
do nazwania w ciągu 24 godzin od fetched_at. SQL raportuje materiały starsze
od tego okna, nie przestawia ich dat. Eksport Pages odświeży kolejny workflow;
sam SQL nie zmienia już opublikowanych plików strony.

Kontrola zależnych scaleń blokuje wyłącznie zewnętrzne przekierowania do
NOWYCH kandydatów przeznaczonych do usunięcia. Starsze przekierowania do
13 przywracanych wątków pozostają bez zmian i nie blokują operacji, ponieważ
ich docelowe wątki nadal istnieją. Pierwsza wersja SQL zbyt szeroko obejmowała
oba zbiory. Przerwanie przez tę kontrolę wycofywało całą operację; można
wkleić poprawiony plik i wykonać go ponownie.

## Wyłącznie media kontrolowane przez państwo

W STATE_ONLY etap perspective_summary nie jest wywoływany. Zapis obejmuje
wyłącznie przypisane źródłom doniesienia w sekcji STATE, bez głównej syntezy,
leadów z faktów i generowanego kontekstu. Stare wątki oparte wyłącznie na
takich źródłach są pomijane w kolejce pierwszych syntez i aktualizacji.
Interfejs ustala ten warunek również z rzeczywistych artykułów, więc ukrywa
stary tekst/lead, główne zakładki i wcześniejsze aktualizacje nawet przy
nieaktualnych metadanych opracowania. Dane w bazie pozostają bez zmian.

Publiczna agencja typu GOVERNMENT_AGENCY z normalnym profilem redakcyjnym
nie jest automatycznie medium kontrolowanym przez państwo. Regułę oznaczają
STATE_ALIGNED/STATE_MEDIA w profilu albo source_type=STATE_MEDIA.

## Synteza w formie artykułu

Prompt pierwszej syntezy wymaga opisania wszystkich dopuszczonych main_facts
w spójnym artykule informacyjnym, z akapitami grupującymi powiązane ustalenia.
Zabrania list i mechanicznego przepisywania pojedynczych faktów. Przy kilku
odrębnych ustaleniach wymaga co najmniej dwóch akapitów; nie dopisuje treści
przy pojedynczym fakcie. Elementy paragraphs nadal rozdzielamy pustą linią.
Synteza i zakładka Fakty opisują te same ustalenia w różnych formach.
Usunięto nieprecyzyjny zakaz powtórzeń między tymi dwiema częściami; kontekst
nadal ma dostarczać dodatkowego tła bez powielania treści artykułu.
Reguły dopuszczania faktów, STATE_ONLY i niezmienności opublikowanej syntezy
pozostają bez zmian. Doprecyzowanie dotyczy nowych syntez, bez dodatkowych
wywołań API i bez automatycznego przepisywania istniejących opracowań.

## Jedno źródło powiązań faktów z artykułami

Przebieg Actions 39231054381 ujawnił 13 odrzuceń przez rozbieżne lub błędne
pomocnicze fact_indexes w article_coverage. Była to redundantna numeracja
wyliczalna z facts[].article_ids. Od v62 model jej nie zwraca: article_coverage
jest obiektem z obowiązkowym kluczem każdego wysłanego article_id i polem
no_relevant_facts_reason_pl. Ścisły schemat wymusza obecność wszystkich kluczy.
Kod wylicza pokrycie i logowane liczniki bezpośrednio z cytowań faktów.

Starsze odpowiedzi z listą article_coverage też są obsługiwane: błędne indeksy
są odtwarzane lokalnie bez zmiany treści faktów i bez dodawania/usuwania ich
article_ids. Nadal odrzucamy obce cytowania i pominięte/powtórzone artykuły.
Artykuł bez zwróconych cytowań i bez uzasadnienia oznaczamy needs_review
w diagnostyce pokrycia oraz ostrzegamy w logach. Nie odrzucamy przez ten
brak całego opracowania, nie uznajemy artykułu za nieistotny i nie dopisujemy
mu automatycznie żadnego potwierdzenia. Nie dodajemy wywołań AI.
Przypadki z rzeczywistych logów są utrwalone w test_data i testowane bez API.

## Ścisłe cytowania i pojedyncza korekta odpowiedzi

Od v63 nowe fakty mogą cytować wyłącznie dokładne article_ids z wysłanej
paczki. Potwierdzenia znanych faktów mogą ponadto zachować wcześniejsze
cytowania; kod nadal sprawdza ten warunek osobno dla każdego faktu. Nie ma
dopasowywania podobnych identyfikatorów ani automatycznego zmieniania źródła.
Schemat wymaga niepustej treści nowego faktu, a przy istniejącym rejestrze
także niepustego why_new_pl. Potwierdzenia mają pustą treść i uzasadnienie,
bo kod przywraca ich niezmieniony, znany tekst.

Jeśli odpowiedź ekstrakcji lub pisania nie przejdzie walidacji semantycznej,
ponawiamy tylko ten etap jeden raz. Model dostaje konkretne zastrzeżenie,
wadliwą odpowiedź i te same dane wejściowe, w tym pełne treści artykułów
przy ekstrakcji. Musi ponownie sprawdzić źródło lub nowość ustalenia;
kod nie dopisuje uzasadnień. Ponowna wadliwa odpowiedź kończy temat błędem
z diagnostyką, bez zapisywania częściowego opracowania. Poprawne odpowiedzi
nie powodują dodatkowych zapytań. Błędy transportu mają osobną dotychczasową
politykę ponowień. Aktualizacja nadal nie wywołuje pisania syntezy i nie
zmienia opublikowanego tekstu ani kontekstu.

Przy braku wspólnych faktów paragraphs=[] jest wymagane. Kontekst może być
pusty, jeśli tytuł nie daje podstaw do neutralnego objaśnienia; nie jest to
błąd ani powód do wymyślania tła. Zachowujemy fakty poszczególnych perspektyw,
a strona pokazuje komunikat o braku wspólnych informacji zamiast zakładek
głównej syntezy/faktów. Jeśli wspólne fakty istnieją, ogólny kontekst nadal
jest obowiązkowy. STATE_ONLY w dalszym ciągu nie wywołuje pisania w ogóle.

Testy regresji odtwarzają cztery wadliwe odpowiedzi z Actions 39236469690,
wraz z rzeczywistymi profilami źródeł i wcześniejszym rejestrem faktów
z publicznego eksportu. Odpowiedzi naprawcze są symulowane; testy nie
wywołują OpenAI ani nie modyfikują bazy. Uruchomienie:
`python -m pip install -r requirements-dev.txt`, następnie
`python -m unittest discover -p 'test_*.py'`.

## Fakty perspektyw a oś aktualizacji

Pełny perspective_state obejmuje również fakty dopisane w aktualizacjach.
Interfejs nie powtarza ich w dolnej sekcji „Co dodatkowo podają źródła”:
porównuje jej fakty z wszystkimi wyświetlanymi aktualizacjami i szerszymi
potwierdzeniami według fact_id, a dla starszych wpisów także identycznej
treści po ujednoliceniu białych znaków i wielkości liter. Nie stosuje
przybliżonego dopasowania ani nie łączy różniących się liczb/twierdzeń.

Nowe informacje pozostają w swojej aktualizacji, wcześniejsze odrębne
ustalenia pozostają w sekcjach profili. Puste grupy i pusta sekcja znikają.
Pełny rejestr faktów, pierwotna synteza, dane źródłowe, historia aktualizacji
i oznaczenia przeczytania pozostają bez zmian. Przy STATE_ONLY aktualizacji
nie wyświetlamy, więc nie odfiltrowujemy na ich podstawie doniesień STATE.
Poprawka działa na istniejących danych bez ponownego AI i bez zapisu do bazy.
Regresja OS82 z publicznego eksportu jest w test_data; sprawdza ją
`node test_frontend_perspective_updates.js`.

Etykiety nad paskiem udziału artykułów pokazujemy tylko dla procentów większych
od zera po zaokrągleniu. Wpisy typu „Lewicowe 0% (0)” znikają; obliczenia
udziałów i sam pasek zachowują dotychczasowe wartości.
