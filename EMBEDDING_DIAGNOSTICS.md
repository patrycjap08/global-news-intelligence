# Przykłady działania embeddingów

Po nowym głównym workflow (`full` lub `ai-only`) uruchom
[sql_embedding_samples.sql](sql_embedding_samples.sql) w Supabase SQL Editor.
Nie ma migracji: raport jest zapisywany w istniejącej tabeli `topic_runs`,
stage `EMBEDDING_DIAGNOSTICS`. Starszych wyników nie można odtworzyć.

Pierwsze zapytanie pokazuje po pięć przykładów z każdej dostępnej kategorii:

- wybrane pary z podobieństwem od progu do progu + 0,03;
- wybrane pary z większym podobieństwem;
- pominięte pary od progu - 0,03 do progu;
- pary nad progiem pominięte przez limit sąsiadów (tylko historyczne raporty).

Przy progu 0,86 zakres tuż pod progiem to 0,83–0,86. Dokładna wartość
progu jest zapisana w każdym raporcie, więc zmiana konfiguracji nie zmienia
interpretacji dawnych próbek. Wynik podobieństwa nie jest prawdopodobieństwem
ani `confidence` oceniającego modelu AI. W głównym workflow wybrane pary są scalane automatycznie; AI nie
weryfikuje już decyzji. Starsze raporty pokazywały kandydatury do oceny AI. Podobieństwo bliskie 1 może także wynikać z podobnych
szablonów tytułów, np. codziennych serwisów informacyjnych.

Pozycje są liczone niezależnie dla obu kierunków. W głównym przebiegu nie
ma już limitu sąsiadów: każda para nad progiem jest wybierana. `top_k` w
nowym raporcie wynosi JSON null; zaktualizowany SQL wyświetla „bez limitu”.
Starszy SQL odczytujący tę wartość jako liczbę nadal działa i pokazuje NULL.
Kategoria pominięcia przez limit sąsiadów pozostaje do odczytu starszych
raportów; w nowych powinna mieć zero par. Teksty i
tytuły są zapisywane przed scalaniem, dokładnie tak, jak wysłano je do API
embeddingów. Nie przechowujemy wektorów ani pełnych treści artykułów.

Raport zachowuje do 20 par na kategorię: 10 najbliższych progowi i do 10
pozostałych dobranych deterministycznie po identyfikatorach. To próbki do
ręcznej oceny, a nie reprezentatywna próba pozwalająca oszacować odsetek błędów.
Aby obejrzeć większe podobieństwa, zwiększ `example_number <= 5` do 20.
Drugie zapytanie pokazuje pełne liczniki par w tych zakresach, niezależnie
od wielkości zapisanej próbki.

Porównania wykorzystują już obliczane podobieństwa. Zapis nie dodaje zapytań
do OpenAI i nie zmienia par wybranych przez algorytm. Raporty powstają także
przy zerowej liczbie wybranych par, jeśli wykonano embeddingi. Przebieg bez
embeddingów nie tworzy nowego raportu: wtedy SQL pokazuje ostatni wcześniejszy,
więc sprawdź datę. Błąd zapisu jest ostrzeżeniem w logach; nie powoduje przejścia
na filtr słów ani przerwania scalania. Dane diagnostyczne nie są udostępniane
przez publiczne widoki aplikacji.

## Przedziały aż do 0,60

Po nowym przebiegu uruchom [sql_embedding_score_bands.sql](sql_embedding_score_bands.sql).
To jedno zapytanie pokazuje do pięciu par w każdym przedziale co 0,02 od
0,84–0,86 do 0,60–0,62. Zachowujemy pięć par najbliższych dolnej granicy
przedziału oraz pełny licznik par w przedziale, bez dodatkowych wywołań API.
Puste przedziały mają NULL w tytułach. Niższe wyniki są diagnostyczne; próg
scalania pozostaje 0,86. Nowe próbki mają `selected_for_merge`; pole
`selected_for_ai` jest false, bo decyzja nie jest wysyłana do modelu.

Scalanie zaczyna grupę od najsilniejszej dostępnej pary A–B. Każdy kolejny
element musi osiągnąć próg z A albo B, które pozostają stałe; połączenie
wyłącznie z późniejszym członkiem nie wystarcza. Pozostałe elementy mogą
utworzyć osobne grupy. Przy remisie kolejność wyznaczają identyfikatory. AI opracowuje
potem tytuł oraz syntezę/aktualizację. Faktyczne scalenia są zapisywane w
`topic_runs` jako `EMBEDDING_MERGE`, z zachowanym identyfikatorem wątku,
listą połączonych tematów i minimalnym wynikiem wybranej krawędzi.

Raport zawiera `grouping = strongest_pair_anchors` oraz `anchored_groups`.
Każda grupa zapisuje identyfikatory pary odniesienia, jej score oraz minimalny
score do punktu odniesienia. `selected_for_merge` oznacza, że para przekracza
próg i jej elementy trafiły do tej samej planowanej grupy. Licznik
`selected_pair_count` nadal liczy wszystkie pary ponad progiem, także
rozdzielone przez regułę punktów odniesienia. Faktycznie zapisane scalenia
należy sprawdzać w `EMBEDDING_MERGE`, gdzie są również dane pary odniesienia.
