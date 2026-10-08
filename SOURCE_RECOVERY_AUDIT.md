# Audyt pobierania źródeł — 8 października 2026

Przegląd objął 79 pozycji z `sources.yaml`: 68 włączonych oraz 11 wyłączonych.
Testy wykonano w środowisku roboczym, bez zapisów do produkcyjnej bazy i bez wywołań AI.
Dostępność z tego środowiska nie gwarantuje tej samej dostępności z runnera GitHub.

## Naprawione wspólne błędy

- Zachowanie dat publikacji z RSS/Atom i news sitemap, dat `lastmod` oraz tytułów.
- Połączenie metadanych tego samego adresu z kilku metod przed sortowaniem i ograniczeniem puli.
- Najnowsze datowane wpisy i mapy podrzędne przed starymi; wpisy bez dat zachowują kolejność źródła.
- RSS używa linku artykułu zamiast GUID; Atom ignoruje linki `self`/załączników.
- Sitemap nie traktuje adresów ilustracji jako adresów artykułów.
- Tekst szablonu CAPTCHA w skrypcie nie oznacza widocznej blokady.
- Respektowanie metody odczytu BROWSER, gdy została skonfigurowana dla źródła.
- Odrzucenia inne niż za krótka treść i przekierowania do istniejących artykułów są jawnie logowane.

## Jak zastosować

Uruchom **full**. AI-only nie pobiera stron źródeł.
Opcjonalnie przy pierwszym full zaznacz `retry_rejected`, aby ponownie sprawdzić zapamiętane odrzucenia za krótkiej treści, w tym materiały Business Insider.
Domyślnie ta opcja pozostaje wyłączona. Ponowna kontrola może wydłużyć pobieranie; nadal obowiązuje limit puli kandydatów.
Dla Axios pełna treść otrzymana z oficjalnego RSS może zastąpić dawny za krótki odczyt bez tej opcji.
Nie jest potrzebna migracja ani ręczna zmiana bazy. Dotychczas zapisane treści artykułów nie są automatycznie przepisywane.

## Granice naprawy

Nie obniżono minimum 100 słów. Krótka wiadomość lub publiczny fragment może nadal zostać prawidłowo odrzucony.
Nie obchodzono CAPTCHA, logowania ani płatnego dostępu. Nie włączono źródeł wcześniej wyłączonych.
Financial Times nadal zwracał stronę weryfikacji HTTP 403. Reuters zwracał HTTP 401 na stronie głównej.
Blokady Axios, Sky News i Daily Signal widoczne w logach GitHub nie wystąpiły w testach stron w tym środowisku; dodanie RSS i poprawienie fałszywych rozpoznań pomaga, lecz wymaga potwierdzenia kolejnym full na GitHubie.

## Przegląd wszystkich pozycji

Pierwsza kontrola obejmowała stronę główną, do dwóch jawnie skonfigurowanych kanałów i do dwóch adresów wybranych z RSS/linków strony głównej.
To próbki techniczne, nie reprezentatywny pomiar liczby nowych artykułów. Brak próbki artykułu nie jest dowodem awarii; część źródeł wymaga map stron lub przeglądarki.
Kolumna słów pokazuje wynik **przed poprawkami**, również gdy wybrany adres był stroną nawigacyjną.

| Źródło | Włączone | HTTP strony głównej | Słowa w próbkach przed poprawkami | Zmiana / uwaga |
|---|---|---|---|---|
| ABC News | tak | 200 | 695, 619 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| ANSA | tak | 200 | 4241, 2047 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Associated Press | nie | 200 | brak próbki | Pozostaje wyłączone. |
| Axios | tak | 200 | 66, 49 | RSS z pełną publiczną treścią; poprawiony odczyt rozwinięcia na stronie. |
| Bankier | tak | 200 | 519, 791 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| BBC | tak | 200 | 1038, 354 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Bild | tak | 200 | 16, 16 | Adresy artykułów; wykluczone strony startowe. |
| Bloomberg | nie | 403 | brak próbki | Pozostaje wyłączone. |
| Business Insider Polska | tak | 200 | 52, 1555 | Wybór sekcji treści zamiast sekcji nagłówka/wstępu. |
| Caixin | tak | brak odpowiedzi | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. Brak odpowiedzi w tej próbie wymaga weryfikacji z runnera. |
| CBS News | tak | 200 | 511, 40 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| CGTN | tak | 200 | 2232, 2319 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| China Daily | tak | 200 | 325, 1538 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| CNN | tak | 200 | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Corriere della Sera | tak | 200 | 779, 947 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Der Spiegel | tak | 200 | 379, 41 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Deutsche Welle | tak | 200 | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Die Zeit | nie | brak odpowiedzi | brak próbki | Pozostaje wyłączone. |
| Do Rzeczy | tak | 200 | 239, 352 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Dziennik Gazeta Prawna | tak | 200 | 648, 15 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Economist | nie | 402 | brak próbki | Pozostaje wyłączone. |
| EFE | tak | 403 | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| El Mundo | tak | 200 | 2131, 1048 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| El País | tak | 403 | 9 CAPTCHA, 1105 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Euronews | tak | 200 | 2130, 1369 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| FAZ | tak | 200 | 30, 3 | Wykluczone rozpoznane strony nawigacyjne. |
| Financial Times | tak | 403 | 23 CAPTCHA, 23 CAPTCHA | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Fox News | tak | 200 | 1064, 1075 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| France 24 | tak | 403 | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Gazeta Wyborcza | nie | 200 | brak próbki | Pozostaje wyłączone. |
| Global Times | tak | 200 | 757, 326 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Guardian | tak | 200 | 1389, 1997 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| HuffPost | tak | 200 | 9, 9 | Tylko adresy /entry/, bez stron kategorii. |
| Independent | tak | 200 | 576, 1267 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Interfax-Ukraine | tak | 200 | 597, 44 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Kommersant | tak | 200 | 9, 9 | Aktualny RSS/news sitemap; odczyt właściwych akapitów div; tylko /doc/ID. |
| Krytyka Polityczna | tak | 200 | 1408, 876 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Kyiv Independent | tak | 200 | 312, 93 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Kyiv Post | tak | 200 | 1287, 1185 | Aktualny /feed; tylko /post/ID. |
| La Repubblica | tak | 200 | 68, 66 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Le Figaro | tak | 200 | 866, 23 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Le Monde | tak | 200 | 846, 77 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Libération | nie | brak odpowiedzi | brak próbki | Pozostaje wyłączone. |
| Meduza | tak | 200 | 261, 23 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Moscow Times | tak | 200 | 1124, 631 | Aktualny RSS i daty; tylko adresy wiadomości. |
| Mother Jones | tak | brak odpowiedzi | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. Brak odpowiedzi w tej próbie wymaga weryfikacji z runnera. |
| National Review | tak | brak odpowiedzi | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. Brak odpowiedzi w tej próbie wymaga weryfikacji z runnera. |
| NBC News | tak | 200 | 2639, 227 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| New York Post | tak | 200 | 8, 577 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| New York Times | nie | brak odpowiedzi | brak próbki | Pozostaje wyłączone. |
| Niezależna | tak | 200 | 463, 367 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| NPR | tak | 200 | 10, 75 | Datowane adresy artykułów; wykluczone subdomeny pomocy. |
| Onet | tak | 200 | 303, 288 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| PAP | tak | 200 | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Parkiet | tak | 200 | 1876, 2570 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Politico | nie | 402 | brak próbki | Pozostaje wyłączone. |
| Politico Europe | tak | 402 | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Polsat News | tak | 200 | 8, 7 | Adresy datowanych wiadomości i Graffiti zamiast kategorii. |
| Reuters | tak | 401 | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| RIA Novosti | tak | 200 | 1245, 1487 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| RT | tak | 200 | 783, 1280 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Rzeczpospolita | tak | 200 | 865, 632 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Sky News | tak | 200 | 556, 748 | Oficjalny RSS world jako dodatkowa droga odkrywania. |
| South China Morning Post | tak | 403 | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Suspilne | tak | 200 | 398, 894 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| TASS | tak | 200 | 92, 138 | Aktualny RSS; daty; tylko adresy wiadomości. |
| Telegraph | nie | 402 | brak próbki | Pozostaje wyłączone. |
| The Daily Signal | tak | 200 | 1421, 430 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Times | tak | 200 | 23, 20 | Nowa domena .com; tylko adresy artykułów. |
| TVN24 | tak | 200 | 367, 829 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| TVP Info | tak | 200 | brak próbki | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Ukrinform | tak | 200 | 2971, 174 | RSS; poprawiony link zamiast GUID; wykluczone strony informacyjne. |
| Vox | tak | 200 | 856, 2522 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Wall Street Journal | nie | brak odpowiedzi | brak próbki | Pozostaje wyłączone. |
| Washington Examiner | tak | 200 | 157, 18 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| Washington Post | tak | 200 | 1035, 1212 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| WP | tak | 200 | 236, 238 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |
| wPolityce | nie | 200 | brak próbki | Pozostaje wyłączone. |
| Xinhua | tak | 200 | 658, 1817 | Konfiguracja bez zmian; korzysta z poprawek wspólnego odczytu dat/odkrywania. |

## Kontrola po poprawkach

Poniżej dodatkowa kontrola rzeczywistego odkrywania adresów przez harvester (do dwóch map głównych i jednej podrzędnej na źródło), a następnie pierwszego wybranego artykułu. Odczyt HTTP, bez przeglądarki; dla Axios publiczna treść z RSS.

| Źródło | Adresów w kontrolnej puli (limit 100) | HTTP próbki | Słów w próbce | Metoda |
|---|---|---|---|---|
| Polsat News | 100 | 200 | 322 | HTTP_HTML |
| NPR | 100 | 200 | 222 | HTTP_HTML |
| Axios | 100 | 200 | 467 | PUBLISHER_RSS |
| HuffPost | 100 | 200 | 213 | HTTP_HTML |
| Times | 100 | 200 | 17 | HTTP_HTML |
| Sky News | 15 | 200 | 606 | HTTP_HTML |
| FAZ | 100 | 200 | 175 | HTTP_HTML |
| Bild | 100 | 200 | 564 | HTTP_HTML |
| TASS | 100 | 200 | 70 | HTTP_HTML |
| Kommersant | 100 | 200 | 402 | HTTP_HTML |
| Moscow Times | 92 | 200 | 561 | HTTP_HTML |
| Ukrinform | 100 | 200 | 391 | HTTP_HTML |
| Kyiv Post | 100 | 200 | 1105 | HTTP_HTML |

Krótki wynik The Times wymaga nadal dostępu/odczytu przeglądarkowego; migracja domeny naprawia odkrywanie, nie gwarantuje pełnej treści. Próbka TASS była autentyczną krótką wiadomością i nie spełnia minimum 100 słów. Brak odpowiedzi w pojedynczej próbie nie rozstrzyga dostępności całego źródła.

Regresje: 161 testów Python zakończonych powodzeniem, w tym 11 nowych testów odzyskiwania źródeł.

Próba dodatkowej kontroli The Times w przeglądarce nie doszła do odczytu strony: w środowisku audytu brak zainstalowanego pliku Chromium. Workflow full instaluje Chromium przed pobieraniem; tej części nie potwierdzono tutaj testem na żywej stronie.
