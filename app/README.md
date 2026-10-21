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
odczytaną treść; temat ponownie staje się nieprzeczytany po nowej zaakceptowanej
aktualizacji. Samo dołączenie źródeł ani analiza bez nowych ustaleń nie resetuje odczytu.

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
Krótki opis jest widoczny pod tytułem na karcie i w otwartym wątku,
również po pobraniu pełnej syntezy. Korzysta z już zapisanego tekstu.

Syntezy bez podziału na akapity są dzielone na granicy zdania, gdy taki podział
jest możliwy, bez dopisywania treści. Oznaczony „Podsumowując” ostatni akapit
nie jest wyświetlany. Bieżący prompt wymaga zwięzłej polszczyzny i potrzebnego
tła w samej syntezie, zgodnie z opisem v76 poniżej. Aktualizacje są redagowane
w już istniejącym niezależnym audycie nowości: lista zdań wskazuje zaakceptowane
indeksy faktów; program odrzuca pominięte, obce i odrzucone indeksy.
Nie dodano kolejnego zapytania do modelu.

Dawny format syntez zawierał osobne `general_context` w odpowiedzi AI. Przed
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

Pierwsza synteza pozostaje archiwum. Od v74 nowe ustalenia mogą odświeżać
bieżącą narrację i kontekst; zasady kosztu i kwalifikacji opisuje dokument
EDITORIAL_PERSPECTIVES.md.

Od v74 aplikacja pokazuje current_summary z bieżącym rejestrem faktów.
Historia aktualizacji nie jest wyświetlana w dialogu; zapisane aktualizacje
nadal służą do ustalania nowych informacji i statusu przeczytania. Pierwsza
synteza i opracowania dołączone przy scalaniu pozostają zwijanym archiwum.
Karty faktów pokazują treść i źródła, bez powtarzanych nagłówków
typu „Informacja”, „Wypowiedź lub zarzut” i dopisków „Autor:”. Przypisanie
w samej treści, klasyfikacja i dane o autorze są zachowane
w danych. Identyczna ocena przytaczana przez kilka profili jest jedną kartą
z autorem i źródłami. Od v77 nie ma rozwijanych cytatów; treść ustaleń i nazwy źródeł pozostają.

Od v75 synteza ma zaczynać się od głównej informacji związanej z tytułem.
Jeżeli walidacja zachowa tylko poboczne akapity, brakujący rdzeń zostanie
uzupełniony przyjętym ustaleniem bez dodatkowego wywołania AI. Ewidentne braki
w istniejącym bieżącym tekście mogą kwalifikować się do jednego pisania
podczas następnego AI-only, na zapisanych faktach, bez odczytywania artykułów.

Od v76 nie ma osobnego kafelka Kontekst, również przy dawnych opracowaniach.
Potrzebne tło i krótkie objaśnienia osób, organizacji i skrótów mają być
wplecione w samą syntezę. Prezydentów i państw nie trzeba przedstawiać.
Model może korzystać z dobrze ugruntowanej wiedzy ogólnej, jeśli potrzebne
objaśnienie nie występuje w artykułach. Nie dopisuje w ten sposób nowych
bieżących doniesień ani niepewnych funkcji lub powiązań.

To samo zapytanie piszące może dostać do 3600 znaków wybranych fragmentów
z najwyżej trzech już pobranych źródeł. Dodane objaśnienia są zachowane
w audycie narracji; nie stają się faktami potwierdzonymi przez artykuły.
Nie ma zapytań naprawczych. Istniejące syntezy z kilkoma nieznanymi skrótami
mogą dostać jedną próbę takiego pisania przy najbliższym AI-only; pusty wynik
również zapisuje zakończenie tej próby, aby nie powtarzać kosztu.

Od v77 ekstrakcja nie żąda dosłownych cytatów ani nie odrzuca ustaleń z powodu
ich niedopasowania. AI nadal czyta pełne treści i przypisuje ustalenia do
artykułów; wypowiedzi i oceny wymagają autora. Puste publikacje powstałe
wyłącznie po odrzuceniu cytatów mogą otrzymać jedną próbę nowym protokołem
przy następnym AI-only. Próba zapisuje zakończenie również przy pustym wyniku.
Brak zachowanych wyników jest opisany jako nieprzygotowana synteza, bez
stwierdzenia, że w artykułach nie ma neutralnych informacji.
