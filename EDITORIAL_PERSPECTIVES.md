# AI-only i publikacja perspektyw — v88

Obowiązująca wersja: `ai-prompts-v88-complete-inputs-paired-paragraphs`.
Poniższe zasady zastępują wcześniejsze opisy v61–v73; tamte implementacje
pozostają w historii Git. Format bazowy `perspective_version=1` i klasyfikacja
`fact_classification_version=1` pozostają zgodne wstecz. Bieżący widok
ma dodatkowo `publication_version=2`.

## Cel publikacji

Czytelnik najpierw dostaje krótki, aktualny opis wydarzenia. Osobno może sprawdzić
ustalenia ze źródłami, oceny i interpretacje oraz tło. Profil polityczny portalu
nie decyduje o prawdziwości i nie dowodzi przemilczania tematu. Dwa portale mogą
uzupełniać się albo cytować tę samą depeszę lub cudzą ocenę.

- `FACT`: neutralna informacja; trafia do części ogólnej także wtedy, gdy
  pochodzi z jednego źródła. Sformułowania nie mogą obiecywać niezależnej weryfikacji.
- `STATEMENT`: wypowiedź, zapowiedź lub zarzut z nazwanym autorem. Zarzut nie
  staje się ustalonym faktem.
- `EDITORIAL`: ocena lub interpretacja redakcji/analityka. Jest wyświetlana
  raz, z autorem i źródłami, które ją przytaczają. Cytowanie Le Monde przez
  prawicowy portal nie jest automatycznie własnym stanowiskiem tego portalu.
- Materiał pochodzący wyłącznie z mediów kontrolowanych przez państwo pozostaje
  osobnym doniesieniem. Nie trafia do neutralnej syntezy. Dotyczy to również
  widoku starych zapisów oraz archiwalnych tekstów dołączonych przy scaleniu.

Lista źródeł i pasek pokazują wszystkie przypisane artykuły. Nie są liczbą
niezależnych potwierdzeń; fakty pokazują własne, zaakceptowane przypisania.
Kolory podpisów odpowiadają paskowi. Zero nadal ma napis `0%` i odcinek 4 px.

## Jeden przebieg

1. Nadaj nazwy nieprzetworzonym artykułom.
2. Porównaj i scal kandydatów przed syntezami, uporządkuj tytuły.
3. Uruchom jedną kolejkę opracowań. Każdy temat ma ekstrakcję nowych lub
   zmienionych materiałów, kontrolę nowości krótkich ustaleń i najwyżej jedno
   napisanie bieżącej syntezy.
4. Uzupełnij brakujące kategorie.

Nie ma końcowego scalania uruchamiającego drugą kolejkę. Dotyczy to `full`,
`ai-only` i workflow jednego źródła. Ręczny tryb kompatybilności
`merge-existing-summaries` nadal istnieje jako osobna operacja; nie jest
wywoływany automatycznie na końcu zwykłego przebiegu.

## Grupowanie tematów

Próg pozostaje **0,78** dla wszystkich tematów. Wejście embeddingu to tytuł
(do 300 znaków) i krótki bieżący opis (do 650 znaków). Jeśli kandydat nie ma
opisu, używany jest nagłówek jego artykułu. Długie syntezy i przypadkowe wzmianki
o innych wydarzeniach nie poszerzają tekstu embeddingu.

Porównania obejmują nowe–nowe i nowe–stare, także przy ponowieniu nieukończonego
harvestu. Nie ma par stary–stary. Para powyżej progu przechodzi dodatkowy tani
filtr wspólnego konkretnego zdarzenia w tytule/opisie. Sama wspólna osoba lub
państwo nie wystarcza. To konserwatywna heurystyka tekstowa: może pozostawić
osobno dwa powiązane tematy i nie gwarantuje poprawnej identyfikacji wydarzenia.
Nie wykonuje dodatkowego zapytania AI.

Grupa zaczyna się od najsilniejszej pary. Następny temat musi pasować do obu
stałych punktów odniesienia. Grupa może zawierać najwyżej jeden temat spoza
bieżącej puli nowych; nowy „most” nie scala pośrednio dwóch starych historii.

Przy łączeniu publikacji zachowywane są rejestry faktów, cytowania,
identyfikatory aktualizacji, przetworzone artykuły oraz oryginalne teksty.
Zapis unii poprzedza przekierowanie starych wątków. Operacje są idempotentne,
ale wieloetapowy zapis REST nie jest jedną transakcją SQL. `first_published_at`
nie zmienia się po nowej analizie; dla dawnych rekordów używany jest fallback
`first_seen_at`. Scalenie nie zmienia czasu utworzenia przypisania artykułu
ani nie zamienia już przeczytanego materiału w nową wiadomość.

## Ekstrakcja i koszt

Pełne teksty są wysyłane tylko dla nowych artykułów lub zmienionego
`content_hash`, w paczkach do ośmiu i według limitu wielkości pakietu.
Artykuł nie jest skracany. Wcześniejsze artykuły pozostają metadanymi/cytowaniami.

Każdy zaakceptowany fakt z nowej ekstrakcji musi mieć samodzielny tekst,
poprawny typ i przypisanie do konkretnego artykułu przez jego klucz
w `article_results`. Wypowiedzi i oceny wymagają `attribution`.
Od v77 nie żądamy cytatu ani identyfikatora fragmentu źródła i nie sprawdzamy
dosłownego dopasowania brzmienia. Model nadal odczytuje pełne artykuły;
kontrole ID, struktury i klasyfikacji nie są dowodem prawdziwości parafrazy.
Poprawność znaczenia i zgodność ustalenia z materiałem nadal zależą od modelu.
Nowe odpowiedzi i cache faktów nie wymagają ani nie dopisują `evidence_quote`.

Braki, obce ID, placeholdery i niepoprawne ustalenia są pomijane lokalnie.
Nie ma napraw pokrycia ani ponownych prób generowania odpowiedzi perspektyw.
Poprawne elementy tej samej paczki pozostają użyteczne. Pusty wynik nie jest
interpretowany jako dowód przemilczenia przez redakcję.

Wyniki każdej paczki są zapisywane w `topic_runs`, etap
`ARTICLE_EXTRACTION_CACHE`, zanim worker wyśle kolejne zapytanie. Klucz obejmuje
wersję ekstraktora, model, temat, identyfikator i treść artykułu oraz profil
źródła. Ponowienie po awarii wykorzystuje zapisane wyniki, także oznaczone jako
pominięte. Zmiana treści/modelu/tematu/wersji ekstraktora unieważnia trafienie.
Odczyt cache korzysta z klucza głównego tabeli, nie wymaga nowego indeksu.
Błąd zapisu cache zatrzymuje dany temat przed dalszym wydawaniem tokenów.

Domyślne ustawienia:

| Ustawienie | Wartość | Zakres |
| --- | --- | --- |
| `AI_TOPIC_MAX_CALLS` | 16 (minimum 3) | Wszystkie zapytania perspektyw na temat; z rezerwą na audyt i tekst |
| `AI_STAGE_MAX_OUTPUT_TOKENS` | 16000 | Limit odpowiedzi jednego zapytania, razem z rozumowaniem |
| `OPENAI_EXTRACTION_REASONING_EFFORT` | low | Ekstrakcja i kontrola nowości, modele gpt-5/gpt-6 |
| `AI_SUMMARY_REASONING_EFFORT` | medium | Pisanie krótkiej syntezy |
| `AI_SUMMARY_CONCURRENCY` | 10 | Równoległe tematy, zapisy bazy na koordynatorze |

Budżet nie gwarantuje kompletności. Po jego wyczerpaniu pozostały materiał
jest pomijany zamiast uruchamiania pętli napraw. Poprawnie zakończona analiza
zapisuje artykuły jako przetworzone, również jeśli nie dostarczyły użytecznych
ustaleń. Nie uruchamia ponownie takich pominięć przy każdym `ai-only`.
`quality_report` rozróżnia artykuły rzeczywiście wysłane, użyte z cache,
pominięte ustalenia, pominięte etapy i koszt tokenów; log zawiera ID tematu.
Limity te nie obejmują etykietowania, kategorii, embeddingów ani ręcznych
narzędzi starego formatu.

## Nowość i bieżący tekst

Audyt porównuje krótkie treści, nigdy pełne artykuły. Ma do 24 kandydatów
w paczce i maksymalnie osiem najbliższych tekstowo znanych ustaleń na kandydata.
Działa także dla pierwszej publikacji. Krótkie aliasy `K1`, `C1` zastępują
przepisywanie hashy. Model wybiera `NEW`, `DUPLICATE` albo `DETAIL`.

Walidacja blokuje odniesienia do siebie, obcych i późniejszych ID, ewidentnie
niezwiązanych treści, zmianę typu oraz zrównanie różnych liczb/zaprzeczeń.
Błędna decyzja usuwa tylko niepewnego kandydata, bez próby poprawy. Jednoznaczny
duplikat uzupełnia źródła istniejącego faktu; nie dodaje aktualizacji.
Nie przenosimy wszystkich cytowań zdania złożonego na wszystkie jego składowe.
Dobór podobnych tekstów i walidacje są heurystykami, nie formalnym dowodem
równoważności. Różne parafrazy mogą pozostać osobno.

`base_summary` pozostaje archiwum pierwszej publikacji. `current_summary`
jest odświeżane raz, gdy zmieniły się ustalenia lub po scaleniu rejestrów.
Same nowe potwierdzenia nie kupują kolejnego pisania i nie tworzą aktualizacji.
Niepoprawne akapity są pomijane. Jeśli model nie zwróci żadnego użytecznego
akapitu, krótką syntezę tworzą zaakceptowane ustalenia z przypisaniem do źródła,
bez kolejnego zapytania. Zmieniony artykuł traci stare cytowania przed ponowną
ekstrakcją; niepodparte innym źródłem stare ustalenia znikają z bieżącego rejestru.
Archiwum pozostaje zachowane.

Od v75 pisanie dostaje także `primary_fact_id`: przyjęte ustalenie najbliższe
roboczemu tytułowi. Pierwszy akapit ma opisać samo wydarzenie, zanim poda
wycenę, liczbę odbiorców lub warunki. Gdy częściowo poprawna odpowiedź pomija
to ustalenie, kod dodaje jego zaakceptowane brzmienie z przypisaniem źródła,
bez ponownego zapytania. Raport zapisuje `narrative_core_fallback`.

Kolejka może rozpoznać ewidentne pominięcie kilku kluczowych elementów tytułu
w publikacji `publication_version=2`. Taki temat może dostać jedno nowe pisanie
na podstawie zapisanego rejestru, bez nowych artykułów, ekstrakcji ani audytu
nowości. Nie jest to przebudowa wszystkich syntez ani test pełnej semantycznej
kompletności. Po uzupełnieniu rdzenia ten sam brak nie wywołuje kolejnego
pisania. Stare formaty nie są automatycznie regenerowane przez ten warunek.

## Widok i kontekst

Najpierw bieżąca synteza z potrzebnym tłem, potem oceny; pełny rejestr jest w zakładce
Fakty. Historia aktualizacji nie jest wyświetlana; pozostaje w danych do
audytu i oznaczeń przeczytania. Wcześniejsze syntezy pozostają zwijanym
archiwum. Karty nie mają powtarzanych nagłówków typu informacji ani „Autor:”.
Przypisanie wypowiedzi w treści i źródła pozostają. Od v77 nie ma rozwijanych
cytatów. Dawne fragmenty pozostają w zapisanych danych, bez wyświetlania.
Obecność informacji w archiwum nie usuwa jej z bieżącego stanu.
Wielokrotne identyczne karty ocen są łączone z sumą ich źródeł.

Od v76 osobny kafelek Kontekst jest ukryty we wszystkich opracowaniach,
również historycznych. Zapisane dawne objaśnienia pozostają w danych;
frontend nie dokleja ich automatycznie do tekstu.

Nowe pisanie wplata potrzebny kontekst bezpośrednio w krótką syntezę.
Przy pierwszym użyciu mniej znanej osoby model ma dodać kilka słów o jej
funkcji, zwykle w nawiasie. Prezydenci państw nie wymagają objaśnienia,
państwa i znane nazwy geograficzne również nie. Organizacja lub nieoczywisty
skrót wymagają krótkiego rozwinięcia i wyjaśnienia działalności. Objaśnienia
nie powtarza się, jeśli rola została już podana w zdaniu.

Model może dodać dobrze ugruntowaną wiedzę ogólną spoza artykułów, gdy jest
niezbędna do zrozumienia historii. Nie służy to dopisywaniu nowych bieżących
zdarzeń, domniemanych motywów, zarzutów ani niepewnych funkcji osób.
Niepewne dodatki mają zostać pominięte. Jakość wiedzy modelu i zgodność
funkcji z datą wydarzenia nie są niezależnie weryfikowane dodatkowym API.

To samo zapytanie piszące dostaje również opcjonalne `context_sources`:
wybrane lokalnie, dosłowne fragmenty już pobranych artykułów. Limit wynosi
trzy źródła, 1200 znaków na źródło i 3600 znaków łącznie. Wybór preferuje
zdania opisujące organizacje, wcześniejsze zdarzenia, przepisy i mechanizmy;
jest heurystyką i nie gwarantuje znalezienia całego przydatnego tła.
Źródła państwowe i bez rozpoznanego profilu nie dostarczają tych fragmentów.

Nowy schemat pisania wymaga tylko `paragraphs`. Każdy akapit wskazuje
`fact_ids` dla zdarzenia i krótkie `context_spans` dla dodanych objaśnień/tła.
Walidacja sprawdza odwołania do faktów, dosłowne występowanie oznaczonych
fragmentów w akapicie i dopasowanie pozostałej treści oraz liczb do ustaleń.
Cały akapit nie może składać się wyłącznie z dodatku kontekstowego.
To heurystyka, a nie dowód prawdziwości lub zgodności znaczenia.
Dodatki są zachowane osobno jako `narrative_context` do audytu; nie trafiają
do rejestru Faktów, potwierdzeń źródeł ani nowych ustaleń w aktualizacji.
Nie ma dodatkowej ekstrakcji, weryfikacji API ani płatnych prób naprawy.

Bieżący zapis v2 zawierający co najmniej dwa skróty spoza listy powszechnych
nazw może dostać jedną próbę pisania z objaśnieniami. Reguła jest celowo wąska;
nie przebudowuje wszystkich syntez. `inline_context_version=1` zapisuje się
również przy pustych dodatkach, aby ten sam warunek nie kupował kolejnego
pisania przy każdym AI-only. Nowe dane mogą odświeżyć syntezę według zwykłych
zasad. `quality_report` zawiera liczbę przekazanych źródeł, znaków fragmentów
i zaakceptowanych dodatków kontekstowych.

Od v77 istniejąca publikacja v2, która jest całkowicie pusta po odrzuceniu
ustaleń z powodu dosłownych cytatów, może otrzymać jedną ekstrakcję nowym
protokołem. To dotyczy np. tematu protestów przewoźników we Włoszech.
`fact_extraction_version=2` zapisuje się także po pustym wyniku. Pozostałe
pominięcia oraz niepuste publikacje nie uruchamiają tej próby.
Cache używa wersji `article-facts-v2`, aby stary pusty wynik odrzuconych
cytatów nie zastąpił nowego odczytu. Nie ma pętli napraw ani ponawiania całego
AI-only przez kod. Samo wdrożenie nie uruchamia płatnego przebiegu.

Interfejs odróżnia brak zachowanych wyników ekstrakcji od opracowania
zawierającego wyłącznie oceny. Całkowicie pusty wynik pokazuje jako
nieprzygotowaną syntezę, zamiast twierdzić, że w materiałach nie było
neutralnych ustaleń lub że istnieją niewidoczne perspektywy. Profil centrowy
sam w sobie nie ustanawia prawdziwości ani typu ustalenia.

Indeks listy zawiera podgląd syntezy i metadane aktualizacji. Nie zawiera
rejestru faktów, cytatów ani audytu nowości aktualizacji. Pełny szczegół jest
pobierany po otwarciu. Tekst aktualizacji pozostaje dokładny, aby zachować
zgodność oznaczenia przeczytania między podglądem i pełnym widokiem.

## Wdrożenie i ograniczenia danych historycznych

Nie jest potrzebna nowa migracja SQL. Kod nie uruchamia sam regeneracji całej
bazy ani automatycznego dzielenia błędnie scalonych dawnych wątków.
Frontend od razu scala identyczne oceny w jednym widoku, ukrywa historię aktualizacji i
ukrywa placeholdery oraz osobny kafelek kontekstu. Stare parafrazy, błędne
cytowania i nietrafne scalenia zapisane przed v74 mogą nadal wymagać osobnej
korekty. Nowa synteza powstaje przy następnym kwalifikującym się przetwarzaniu;
bez nowych danych nie kupujemy jej tylko dlatego, że zmienił się kod.
Wyjątkami są opisana wyżej kontrola ewidentnie brakującego rdzenia w v75
oraz pojedyncza próba objaśnienia nieznanych skrótów w v76.

Testy obejmują przykłady Francji, sankcji i Ukrainy z publicznego snapshotu
`ded1b21dd927e527f0d4`, błąd transportu w połowie ekstrakcji i ponowienie z cache,
awarię zapisu, zmianę treści artykułu, budżet, nieuwzględnianie starych par,
rozróżnienie autora oceny od cytującej redakcji i zachowanie historii.
Odpowiedzi API są symulowane; testy nie zastępują kontroli jakości kolejnych
rzeczywistych odpowiedzi modelu.

## Pełne pokrycie informacji w syntezie (v86)

Synteza i zakładka Fakty mają przedstawiać ten sam zakres przyjętych
informacji FACT/STATEMENT. Jedno pisanie obejmuje wszystkie `main_facts`,
łączy powtórzenia i dodaje potrzebne tło w tym samym tekście. Nie obowiązuje
redakcyjny limit 250 słów ani techniczne ucinanie do czterech akapitów.
Oceny redakcyjne pozostają w odrębnych perspektywach. Brakujące powiązania
faktów z zaakceptowanymi akapitami są raportowane bez dodatkowych zapytań.
Szczegóły i przykład 57 ustaleń opisuje
[przegląd pokrycia syntez](SYNTHESIS_COVERAGE_REVIEW_20261023.md).

## Eksperyment: osobny skrót w dwóch akapitach (v87)

Strona pokazuje „Synteza” i „Skrót”, bez listy faktów. Pełny tekst nadal
obejmuje wszystkie ustalenia. Rejestr i osobne oceny redakcyjne pozostają.
Skrót wybiera najważniejsze informacje bezpośrednio z `main_facts`, zamiast
dziedziczyć ewentualne braki starszej syntezy. Powstaje w tym samym zapytaniu
co pełny artykuł: dochodzi krótka instrukcja oraz tokeny wyjścia skrótu,
jego metadanych i ewentualnego rozumowania. Nie wysyłamy ponownie całego
wejścia ani artykułów i nie otwieramy osobnego zapytania.

Odpowiedź zawiera `brief_paragraphs` o dokładnie dwóch elementach z tekstem
i ID wykorzystanych faktów. Kod sprawdza ich strukturę, identyfikatory,
powiązanie z podanymi ustaleniami, liczby, brak powtórzenia całego akapitu
i niedozwolonych podziałów. To nie jest dowód semantycznej poprawności.
Niepoprawny skrót jest pomijany, pełna synteza pozostaje. Nie ma zapytań
naprawczych. Wynik trafia do `current_summary.brief_pl`, a pełna synteza
zostaje w `summary_pl`. Wspólna definicja ID w schemacie nie dubluje enumów
przy dużych rejestrach faktów.

Dla już zapisanych publikacji bez skrótu kolejka AI-only kwalifikuje jedną
próbę `perspective_brief`, w normalnym oknie aktualnych tematów, o ile
istnieją pełny tekst i zapisane fakty. Gdy nie ma nowej informacji ani
innej przyczyny ponownego pisania, wysyłane są tylko fakty. Model pozostaje
ten sam, rozumowanie jest niskie, a wyjście ma limit 3000 tokenów
(`AI_BRIEF_MAX_OUTPUT_TOKENS`). Znacznik `brief_generation_version=1`
zapobiega powtarzaniu ukończonej próby także przy odrzuconej odpowiedzi.
Nowe ustalenia mogą później dać nową syntezę ze skrótem w jednym pisaniu.

Samo uzupełnienie skrótu nie jest nową wiadomością, nie tworzy aktualizacji
i nie zmienia oznaczenia przeczytania. Przeglądarka niczego nie generuje
ani nie odpyta modelu przy otwieraniu zakładki. Starsza historia poza oknem
kolejki nie jest masowo przepisywana. Nie potrzeba migracji JSON w bazie.
