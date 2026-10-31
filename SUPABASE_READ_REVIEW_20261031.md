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
