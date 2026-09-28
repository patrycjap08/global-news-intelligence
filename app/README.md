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

Następnie uruchom z katalogu repozytorium:

```bash
python3 -m http.server 4173
```

Otwórz `http://127.0.0.1:4173/app/`.

Jeśli `config.js` nie istnieje albo widoki Supabase nie zostały jeszcze utworzone,
aplikacja pokazuje
bezpieczny podgląd interfejsu zamiast pustej strony. Dane produkcyjne wymagają
wykonania widoków oraz użycia klucza publishable; klucz sekretny nie powinien być
używany w przeglądarce.
