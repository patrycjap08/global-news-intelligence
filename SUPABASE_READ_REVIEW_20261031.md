# Timeout Supabase przy przygotowaniu tytułów

Przebieg zakończył się po scaleniu 18 grup, zanim rozpoczęło się pisanie
syntez. Stos błędu wskazuje `normalize_topic_titles` oraz odczyt
`topic_summaries`, zakończony timeoutem po trzech próbach.

Etap tytułów pobierał całe dokumenty `summary` ze wszystkich zapisanych
analiz, choć korzystał wyłącznie z jednozdaniowego opisu. Dokumenty zawierają
także ustalenia, ich źródła, poprzednie publikacje i aktualizacje. Powtarzanie
takiego odczytu zwiększa transfer oraz obciążenie bazy wraz z jej historią.

| Obszar | Po poprawce |
| --- | --- |
| Tytuły | Bieżące 36 godzin i jawnie wskazane tematy po scaleniu. Powiązania oraz metadane artykułów po ID, do 50 ID w paczce. |
| Opisy do tytułów | Dopiero po ustaleniu, które tytuły wymagają poprawy. Projekcja trzech krótkich pól dla bieżącego, bazowego i starego formatu. Brak odczytu pełnego JSON. |
| Kategorie | Ta sama lekka projekcja, tylko dla tematów bez kategorii. |
| Scalanie | Pełne analizy tylko z aktywnego okna, do 20 ID w paczce. Bez odczytu analiz, jeśli w puli nie ma nowego tematu do porównania. |
| Kolejka syntez | Pełne analizy tylko dla tematów w oknie 36 godzin z co najmniej dwoma przypiętymi artykułami, do 20 ID w paczce. |
| Wznawianie | Projekcja samej listy przetworzonych artykułów, zamiast pełnego rejestru ustaleń i aktualizacji. |

Odczyty po ID mają stałą kolejność. Kontrola tytułów na końcu sprawdza tylko
przetwarzane tematy, zamiast ponownie skanować całą historię. Zachowano
obsługę dawnych i obecnych formatów analiz oraz walidację tytułów. Nie zmieniono
progów ani zasad scalania, timeoutów, retry ani zapisanych publikacji.

Weryfikacja: **463 testy Python zakończone pomyślnie**, w tym 11 nowych
regresji. Testy odtwarzają odrzucenie pełnego odczytu JSON, potwierdzają brak
czytania archiwalnych analiz, obsługę opisów w trzech formatach, limit paczek
oraz zachowanie zapisanych publikacji. Nie wykonywano płatnych zapytań AI
ani operacji na produkcyjnej bazie.

Po wdrożeniu należy ponowić `ai-only` z `main`. Artykuły i wcześniej zapisane
wyniki pozostają w bazie; nie jest potrzebny SQL resetujący ani migracja.
Poprawka usuwa nadmiarowe odczyty. Awaria dostępności Supabase nadal pozostaje
błędem, zamiast być ukrywana jako poprawne zakończenie.

## Osobny błąd dostępności projektu: HTTP 522

Następny przebieg [41190145343](https://github.com/patrycjap08/global-news-intelligence/actions/runs/41190145343),
już na poprawce `f01d51b`, zatrzymał się na pierwszym odczycie `sources`, przed
harvesterem i AI. Cloudflare zwrócił `522 connection_timeout`: nie mógł
nawiązać połączenia TCP z serwerem projektu. To nie timeout dużej analizy.
Odpowiedź zawierała `retry_after: 120`, ale klient nie zaliczał HTTP 522
do błędów przejściowych i przerywał po pierwszej próbie. Następnie eksport
strony również otrzymał HTTP 522.

Zwykły odczyt publicznego adresu API później otrzymał oczekiwane HTTP 401
bez klucza. Potwierdza to odpowiedź bramki, a nie poprawność połączenia z
Postgresem. Niezależnie użytkowniczka sprawdziła `select now(), 1` w SQL
Editorze i otrzymała connection timeout. Stan panelu projektu i globalne
„All Systems Operational” nie wystarczają więc do uznania projektu za sprawny.
Na podstawie tych danych nie ustalono, czy powodem są zasoby, limit połączeń
czy problem infrastruktury dostawcy.

Obsługa błędu po poprawce:

- HTTP 520–524 jest ponawiane z przerwą co najmniej 120 sekund.
- Respektowane są `Retry-After` (liczba lub data HTTP) oraz `retry_after` z JSON.
  Obowiązuje dłuższa z wymaganych przerw. Jeśli wskazana przerwa przekracza
  300 sekund, klient przerywa z błędem zamiast ponawiać wcześniej.
- Limit pozostaje 3 próby. Błędy uprawnień i inne trwałe HTTP 4xx nie są
  ponawiane. Log podaje próbę i czas oczekiwania, bez kluczy API.
- Nieudany odczyt początkowego stanu kończy przebieg z kodem 1 i jasnym
  komunikatem. Harvester i AI nie startują. `skip_public_export=true`
  zapobiega dodatkowemu odczytowi niesprawnej bazy przez eksport strony.

Weryfikacja łączna: **473 testy zakończone pomyślnie**, w tym 10 nowych testów
dostępności. Oczekiwanie jest zastępowane w testach; nie wykonywano płatnego
AI, zapisu do produkcyjnej bazy ani restartu projektu.

Przed kolejnym AI-only należy przywrócić działanie prostego SELECT w panelu
Supabase. Restart projektu wykonuje właściciel w Project Settings → General.
Jeżeli prosty SELECT nadal nie działa po restarcie, trzeba sprawdzić zasoby
i logi projektu lub zgłosić problem do Supabase. Samo retry klienta nie
naprawia trwałej niedostępności serwera.
