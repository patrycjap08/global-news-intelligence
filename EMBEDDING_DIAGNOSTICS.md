# Przykłady działania embeddingów

Po nowym głównym workflow (`full` lub `ai-only`) uruchom
[sql_embedding_samples.sql](sql_embedding_samples.sql) w Supabase SQL Editor.
Nie ma migracji: raport jest zapisywany w istniejącej tabeli `topic_runs`,
stage `EMBEDDING_DIAGNOSTICS`. Starszych wyników nie można odtworzyć.

Pierwsze zapytanie pokazuje po pięć przykładów z każdej dostępnej kategorii:

- wybrane pary z podobieństwem od progu do progu + 0,03;
- wybrane pary z większym podobieństwem;
- pominięte pary od progu - 0,03 do progu;
- pary nad progiem pominięte przez limit trzech sąsiadów.

Przy progu 0,88 zakres tuż pod progiem to 0,85–0,88. Dokładna wartość
progu jest zapisana w każdym raporcie, więc zmiana konfiguracji nie zmienia
interpretacji dawnych próbek. Wynik podobieństwa nie jest prawdopodobieństwem
ani `confidence` oceniającego modelu AI. Wybrana para to kandydatura do oceny,
a nie decyzja o scaleniu. Podobieństwo bliskie 1 może także wynikać z podobnych
szablonów tytułów, np. codziennych serwisów informacyjnych.

Pozycje są liczone niezależnie dla obu kierunków. Wystarczy, że para
przekracza próg i mieści się w limicie sąsiadów z jednej strony. Teksty i
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
