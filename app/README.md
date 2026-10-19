# GNI — aplikacja webowa

To jest pierwsza wersja interfejsu mobile-first. Ma gazetowy układ, jasne beżowe
tło, typografię szeryfową dla nagłówków oraz widok tematów, źródeł i opracowań.

## Podłączenie Supabase lokalnie

```bash
cp app/config.example.js app/config.js
```

W `app/config.js` wpisz `SUPABASE_URL` oraz `SUPABASE_PUBLISHABLE_KEY`. Nie wpisuj
`SUPABASE_SECRET_KEY` — klucz serwerowy nie może trafić do aplikacji telefonu.

Przed pierwszym uruchomieniem aplikacji wykonaj w Supabase SQL Editorze kolejno:

1. `supabase_migration_topic_updates.sql` — historia wersji opracowań;
2. `supabase_app_views.sql` — bezpieczne widoki dla aplikacji.

Widoki nie udostępniają aplikacji pełnego tekstu artykułów.

Status przeczytania tematów jest zapisywany lokalnie w przeglądarce (`localStorage`).
Każdy użytkownik ma własny status na swoim urządzeniu. Otworzenie tematu zapisuje
odczytaną wersję; gdy pojawi się kolejna wersja opracowania, temat ponownie staje
się nieprzeczytany.

Następnie uruchom z katalogu repozytorium:

```bash
python3 -m http.server 4173
```

Otwórz `http://127.0.0.1:4173/app/`.

Jeśli `config.js` nie istnieje, aplikacja pokazuje podgląd interfejsu.
Przy skonfigurowanym połączeniu błąd sieci nie przełącza jej na dane przykładowe:
przycisk odświeżania pozostaje dostępny, a ostatni poprawny zestaw danych jest
zachowany. Aplikacja zapisuje go też lokalnie w IndexedDB (gdy przeglądarka
udostępnia tę pamięć) i pokazuje po ponownym otwarciu, z informacją o czasie
ostatniego poprawnego odświeżenia. Usunięcie danych witryny usuwa również cache.

Lista pobiera tylko wątki wieloźródłowe, ich powiązania i potrzebne metadane
artykułów. Z syntez pobiera pola potrzebne do kart; pełne opracowanie ładuje
się po otwarciu wątku. Nowoczesna synteza zawiera wszystkie zaakceptowane
aktualizacje. Starszy format korzysta dodatkowo z historii wersji, ale tylko
dla otwartego wątku. Cała historia wszystkich tematów nie jest pobierana przy
każdym odświeżeniu.

Żądania mają limit czasu i ograniczone ponowienia po błędach przejściowych.
Jednoczesne odświeżenia współdzielą jedno pobieranie, a dane są podmieniane
po uzyskaniu kompletnego zestawu. Powrót połączenia lub powrót do aplikacji
po nieudanym pobraniu uruchamia ponowną próbę. Wszystko korzysta z istniejących
widoków — ta poprawka nie wymaga nowej migracji bazy.

Dane produkcyjne wymagają wykonania widoków oraz użycia klucza publishable;
klucz sekretny nie powinien być używany w przeglądarce.


## Publiczne dane z GitHub Pages

`export_public_site.py` eksportuje wyłącznie publiczne widoki interfejsu (bez
pełnych treści artykułów i kluczy). Także po częściowo nieudanym harvest workflow eksportuje już zapisane wyniki i zapisuje artefakt
`gni-public-data`; deploy Pages pobiera najnowszy dostępny artefakt z main.
Błąd eksportu nie zastępuje ostatniego poprawnego zestawu. Data danych pozostaje
widoczna na stronie; workflow i jednorazowy eksport nadal zużywają egress bazy.
Przeglądanie strony w trybie statycznym nie odpytuje Supabase.

Pierwszy eksport przy niedostępnym API: uruchom `sql_export_public_site.sql` w
SQL Editor, ustaw limit wyników wystarczający na wszystkie wątki i pobierz CSV
lub JSON. Nie kopiuj ręcznie komórek (mogą być skrócone). Następnie:

```sh
python export_public_site.py --input eksport.csv --output app/data
```

Importer odrzuca ucięty/niekompletny eksport. Po dodaniu `app/data` i publikacji
konfiguracja automatycznie wybiera `staticDataUrl`. Indeks zawiera dane kart,
pełna synteza i historia są pobierane z osobnego pliku po otwarciu wątku.
Nazwy katalogów wynikają z hasha całego eksportu, więc stary indeks nie pobierze
przypadkiem szczegółów z nowej wersji. Odświeżanie nie uruchamia workflow.

Pierwszy zestaw jest dostarczany jako skompresowany `app/bootstrap-data.tar.gz.b64`; deploy rozpakowuje go do `data/` i usuwa archiwum z publikowanej strony. Nowsze artefakty mają pierwszeństwo, starsze nie cofają danych.


Kategorie można łączyć jako „Dowolna” (LUB) lub „Wszystkie” (I). W trybie LUB
liczniki kategorii nie zależą od zaznaczonych kategorii; w trybie I pokazują
przecięcie każdej kategorii z całym aktualnym wyborem. Oba tryby uwzględniają
zakładkę, ukrywanie przeczytanych, profil źródeł i wyszukiwane hasło.
Zakładka, sortowanie, kategorie, sposób ich łączenia, profil, ukrywanie
przeczytanych i hasło są zapamiętywane lokalnie na tym urządzeniu.
Wyszukiwanie obejmuje tytuł, krótki opis i nazwy źródeł.

Syntezy bez podziału na akapity są dzielone na granicy zdania, gdy taki podział
jest możliwy, bez dopisywania treści. Oznaczony „Podsumowując” ostatni akapit
nie jest wyświetlany. Nowe prompty wymagają co najmniej dwóch akapitów,
polszczyzny i tła historycznego w Kontekście. Aktualizacje są redagowane
w już istniejącym niezależnym audycie nowości: lista zdań wskazuje zaakceptowane
indeksy faktów; program odrzuca pominięte, obce i odrzucone indeksy.
Nie dodano kolejnego zapytania do modelu.

Nowe syntezy wymagają osobnego `general_context` w odpowiedzi AI. Przed
zapisem pole jest włączane na początek istniejącej listy Kontekst pod etykietą
„Ogólny kontekst”, a objaśnienia osób i organizacji są zachowane. Nie wymaga
to migracji bazy ani dodatkowego zapytania do AI. Starsze syntezy pozostają
bez automatycznej przebudowy przy generowaniu samych aktualizacji.


Wątki z dowolnym znakiem cyrylicy w wyświetlanym tytule są ukrywane przez
interfejs przed przygotowaniem listy i liczników, we wszystkich zakładkach,
także po wczytaniu danych z pamięci urządzenia. Filtr nie usuwa danych z bazy.
Prompty nazw roboczych, poprawiania tytułów, scalania i syntez wymagają
polszczyzny oraz polskich nazw/transkrypcji bez cyrylicy.

Pełne opracowania są pobierane przy otwarciu wątku. Po zmianie eksportu strona odświeża manifest i ponawia pobranie nieaktualnego adresu. Błąd pobrania pokazuje przycisk ponowienia; podgląd nie udaje pełnej syntezy ani pustej listy faktów. Odświeżenie tej samej generacji zachowuje pobrane szczegóły.

Status przeczytania odnosi się do syntezy i ostatniej widocznej aktualizacji.
Samo podpięcie nowego artykułu albo analiza NO_NEW_INFORMATION nie oznacza
nieprzeczytanego wątku, także przy włączonym „Ukryj przeczytane”. Dotychczasowe
lokalne oznaczenia z datą przeczytania są zachowywane; nowsza opublikowana
aktualizacja ponownie oznacza wątek jako nieprzeczytany.

Nowe syntezy mają wspólne ustalenia oraz przełączane perspektywy lewicowe,
prawicowe i mediów kontrolowanych przez państwo. Bez wspólnych faktów znikają
zakładki Synteza/Fakty. Pasek pokazuje udział artykułów (bez państwowych).
Zasady aktualizacji, izolacji wersji i cofnięcia jednego commita opisuje
[EDITORIAL_PERSPECTIVES.md](../EDITORIAL_PERSPECTIVES.md).
