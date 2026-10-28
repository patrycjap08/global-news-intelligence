# Analiza przebiegu 40720453072 — 28 października 2026

Źródła: [przebieg GitHub Actions](https://github.com/patrycjap08/global-news-intelligence/actions/runs/40720453072), job 122929608204 oraz publiczny eksport `8f6e5b871fec24deb88e` z 16:18:52 UTC. Nie uruchamiano AI ani zapisów w produkcyjnej bazie podczas analizy.

## 14 nieudanych syntez

Każda zakończyła się lokalnym błędem `Brak materiałów dla wcześniej zapisanego faktu perspektyw`. W publicznym eksporcie wszystkie źródłowe ID zapisanych faktów tych wątków nadal są podpięte do właściwych wątków. Log etapu syntezy podaje mniej lokalnie odczytanych artykułów niż liczba podpiętych źródeł w eksporcie. Nie ma dowodu, że trzeba usuwać te fakty lub ponownie czytać strony wydawców.

| Wątek | Lokalne artykuły w logu | Podpięte artykuły w eksporcie |
| --- | ---: | ---: |
| [Europa] Rozmowy przywódców Finlandii i Norwegii z Putinem o Ukrainie | 9 | 11 |
| [Izrael] Wybory parlamentarne rozstrzygają o kierunku polityki kraju | 6 | 10 |
| [Brazylia] Lula wygrywa wybory prezydenckie, obóz Bolsonaro kwestionuje wynik | 5 | 8 |
| [Niemcy] Krytyka wystąpienia szefa Audi na wiecu Trumpa | 5 | 7 |
| [Polska] Maksymalne ceny benzyny i oleju napędowego | 5 | 7 |
| [USA] Kolejne zarzuty karne wobec Jamesa Comeya | 3 | 5 |
| [Europa] Przywódcy Finlandii i Norwegii rozmawiali z Putinem o negocjacjach pokojowych | 4 | 5 |
| [Polska] Przemyśl zawiesza partnerstwo ze Lwowem w sporze o upamiętnienie UPA | 4 | 5 |
| [Wielka Brytania] Dwaj mężczyźni oskarżeni w sprawie incydentu przy bazie Fairford | 3 | 4 |
| [Izrael] Frekwencja wyborcza i pozycja Netanjahu | 2 | 4 |
| [Świat] Microsoft oferuje odprawy dla dziesiątek tysięcy pracowników | 2 | 4 |
| [Ukraina] Rosyjski ostrzał rakietowy Kijowa powoduje ofiary i zniszczenia | 3 | 4 |
| [Europa] Polska i Wielka Brytania rozwijają współpracę obronną | 3 | 4 |
| [Demokratyczna Republika Konga] Epidemia eboli o rekordowej liczbie ofiar | 2 | 3 |

Początkowy `pull_state` stronicował `articles` bez jawnej kolejności. PostgreSQL nie gwarantuje zgodnej kolejności kolejnych zapytań LIMIT/OFFSET. Log nie zawiera identyfikatorów pominiętych lokalnie rekordów, więc sam dokładny mechanizm utraty nie jest odtwarzalny z logu. Usunięto tę słabość i dodano niezależną kontrolę kompletności.

Poprawka v88: uporządkowany odczyt artykułów, lokalne doczytanie brakujących podpiętych ID z Supabase przed scalaniem i syntezą, kontrola źródeł starego rejestru przed jakimkolwiek wywołaniem modelu. Jeżeli rekord rzeczywiście nie istnieje, diagnostyka zawiera ID faktów/artykułów i nie jest opisywana jako wadliwa odpowiedź AI. Poprzednia publikacja pozostaje. Odtworzenie lokalnych rekordów nie oznacza ponownej ekstrakcji przetworzonych artykułów.

## Ostrzeżenie 33/49

Wątek `topic_perspectives_27aa2513876ab487b7c9a230`: model zwrócił 12 akapitów, zaakceptowano 7. Raport zawiera 1 błąd liczby równoległych wpisów źródłowych, 4 odrzucenia tekstu niepopartego przypisanymi faktami oraz 1 niepoprawne przypisanie. Liczniki przyczyn mogą się nakładać. Pokryto 33 z 49 ID ustaleń; brakowało powiązań z 16 ID. Ostrzeżenie nie było przyczyną kodu wyjścia 1.

Autor wcześniej zwracał pełny tekst i oddzielną tablicę `paragraph_sources`. Nowy schemat API zwraca gotowe `paragraphs`, każdy z własnym `text_pl` i `fact_ids`. Eliminuje to rozbieżność długości i przesunięcie przypisań między dwiema tablicami. Cały artykuł z kontekstem i skrótem nadal powstaje w jednym zapytaniu. Wynik publiczny jest nadal jednym `summary_pl`. Starsze odpowiedzi pozostają czytelne.

Kontrola ID i liczb nie dowodzi pełnego pokrycia znaczeniowego. Nowy format usuwa przyczynę rozjeżdżania powiązań, ale celowo nie ukrywa ostrzeżeń o pozostałych niepopartych lub pominiętych treściach. Nie kupuje dodatkowych odpowiedzi naprawczych.
