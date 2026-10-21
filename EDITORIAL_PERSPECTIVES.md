# AI-only i publikacja perspektyw — v75

Obowiązująca wersja: `ai-prompts-v75-narrative-core`.
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
poprawny typ, przypisanie do konkretnego artykułu i dosłowny fragment
`evidence_quote` występujący w jego pełnej treści. Wypowiedzi i oceny wymagają
`attribution`. Sprawdzenie fragmentu chroni przed cytatem spoza artykułu;
nie dowodzi samo w sobie, że polska parafraza logicznie wynika z cytatu.
Znaczenie i klasyfikacja nadal zależą od modelu.

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
| `OPENAI_EXTRACTION_REASONING_EFFORT` | low | Ekstrakcja i kontrola nowości, modele gpt-5 |
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

Najpierw bieżąca synteza, potem oceny i kontekst; pełny rejestr jest w zakładce
Fakty. Historia aktualizacji nie jest wyświetlana; pozostaje w danych do
audytu i oznaczeń przeczytania. Wcześniejsze syntezy pozostają zwijanym
archiwum. Karty nie mają powtarzanych nagłówków typu informacji ani „Autor:”.
Przypisanie wypowiedzi w treści i źródła pozostają. Rozwijane cytaty są dostępne.
Obecność informacji w archiwum nie usuwa jej z bieżącego stanu.
Wielokrotne identyczne karty ocen są łączone z sumą ich źródeł.

Kontekst jest opcjonalny. Ma wyjaśniać wcześniejsze wydarzenia, uwarunkowania,
instytucje i mechanizmy. Nie ma być streszczeniem ani opisem „o czym jest artykuł”.
Krótkie odniesienie do znanego faktu jest dozwolone, jeśli prowadzi do dodatkowego
objaśnienia. Organizacja wymaga opisu działalności/roli, nie samej nazwy.
Treść musi mieć podstawę w dostępnych ustaleniach; biogramów nie dopisujemy
z pamięci. Puste lub oznaczone `needs_verification` tło nie jest pokazywane.

Indeks listy zawiera podgląd syntezy i metadane aktualizacji. Nie zawiera
rejestru faktów, cytatów ani audytu nowości aktualizacji. Pełny szczegół jest
pobierany po otwarciu. Tekst aktualizacji pozostaje dokładny, aby zachować
zgodność oznaczenia przeczytania między podglądem i pełnym widokiem.

## Wdrożenie i ograniczenia danych historycznych

Nie jest potrzebna nowa migracja SQL. Kod nie uruchamia sam regeneracji całej
bazy ani automatycznego dzielenia błędnie scalonych dawnych wątków.
Frontend od razu scala identyczne oceny w jednym widoku, ukrywa historię aktualizacji i
ukrywa placeholdery oraz niezweryfikowany kontekst. Stare parafrazy, błędne
cytowania i nietrafne scalenia zapisane przed v74 mogą nadal wymagać osobnej
korekty. Nowa synteza powstaje przy następnym kwalifikującym się przetwarzaniu;
bez nowych danych nie kupujemy jej tylko dlatego, że zmienił się kod.
Wyjątkiem jest opisana wyżej kontrola ewidentnie brakującego rdzenia w v75.

Testy obejmują przykłady Francji, sankcji i Ukrainy z publicznego snapshotu
`ded1b21dd927e527f0d4`, błąd transportu w połowie ekstrakcji i ponowienie z cache,
awarię zapisu, zmianę treści artykułu, budżet, nieuwzględnianie starych par,
rozróżnienie autora oceny od cytującej redakcji i zachowanie historii.
Odpowiedzi API są symulowane; testy nie zastępują kontroli jakości kolejnych
rzeczywistych odpowiedzi modelu.
