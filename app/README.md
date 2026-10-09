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
pełnych treści artykułów i kluczy). Po harvest workflow zapisuje artefakt
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
