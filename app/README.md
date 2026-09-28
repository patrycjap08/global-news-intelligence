# GNI — aplikacja webowa

To jest pierwsza wersja interfejsu mobile-first. Ma gazetowy układ, jasne beżowe
tło, typografię szeryfową dla nagłówków oraz widok tematów, źródeł i opracowań.

## Podłączenie Supabase lokalnie

```bash
cp app/config.example.js app/config.js
```

W `app/config.js` wpisz `SUPABASE_URL` oraz `SUPABASE_PUBLISHABLE_KEY`. Nie wpisuj
`SUPABASE_SECRET_KEY` — klucz serwerowy nie może trafić do aplikacji telefonu.

Następnie uruchom z katalogu repozytorium:

```bash
python3 -m http.server 4173
```

Otwórz `http://127.0.0.1:4173/app/`.

Jeśli `config.js` nie istnieje albo Supabase odmówi odczytu, aplikacja pokazuje
bezpieczny podgląd interfejsu zamiast pustej strony. Dane produkcyjne wymagają
odczytu przez użytkownika zalogowanego w Supabase albo osobnej warstwy backendowej
z RLS; klucz sekretny nie powinien być używany w przeglądarce.
