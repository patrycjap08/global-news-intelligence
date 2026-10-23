# Lokalne porównanie modeli syntez

Laboratorium pobiera wybrane wątki z Supabase i zamraża ich pełne artykuły
w lokalnym pliku. Używa obecnych promptów, reguł doboru faktów, deduplikacji,
podziału perspektyw i walidacji z `perspective_summaries.py`. Działa także,
gdy w bazie istnieje już opracowanie: dotychczasowa synteza nie jest wejściem
ani ograniczeniem nowego eksperymentu.

Tytuł wątku, treści artykułów i metadane źródeł wystarczą. Profile źródeł są
potrzebne do odtworzenia perspektyw; daty i ID do porównań i przypisania faktów.
Program nie pobiera nowych artykułów z internetu, nie nazywa ich, nie tworzy
kategorii, nie scala wątków i niczego nie zapisuje w Supabase.

## Uruchomienie na Windows

Pobierz ZIP laboratorium i rozpakuj cały folder. Możesz też użyć tych plików
w pobranym repozytorium. Potrzebny jest Python 3.10 lub nowszy.
W terminalu otwartym w tym folderze:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lab.txt
Copy-Item synthesis_lab_config.example.py synthesis_lab_config.py
Copy-Item synthesis_lab.env.example .env.lab
```

W `.env.lab` wpisz lokalnie klucz OpenAI oraz `SUPABASE_URL` i
`SUPABASE_SECRET_KEY` tego samego projektu co w workflow. Kluczy nie wpisuj
do kodu. Skrypt nie kopiuje ich do wyników. Klasa obsługująca Supabase
technicznie blokuje wszystkie metody HTTP poza GET.

W `synthesis_lab_config.py` edytuj `TOPICS`: jeden lub kilka tytułów, ich
fragmentów albo identyfikatorów. Przy kilku dopasowaniach program pokaże ID
i przerwie wybór, zamiast losowo wybierać pierwszy temat. Wątki nie muszą być
z ostatnich 36 godzin. Wątek scalony wymaga wskazania ID zachowanego wątku.

```powershell
# Szukanie w bazie, bez generowania:
.venv\Scripts\python.exe synthesis_lab.py --search "SpaceX"

# Pobranie wybranych wątków i wszystkich podpiętych artykułów, bez AI:
.venv\Scripts\python.exe synthesis_lab.py --fetch

# Pokazanie planu, bez generowania:
.venv\Scripts\python.exe synthesis_lab.py

# Wywołanie wybranych modeli na zapisanych artykułach:
.venv\Scripts\python.exe synthesis_lab.py --run

# Raport otwierasz dwuklikiem lub:
Start-Process lab-data\report.html
```

Na macOS/Linux odpowiednio: `python3 -m venv .venv`, `.venv/bin/python`
zamiast `.venv\Scripts\python.exe` oraz `cp` zamiast `Copy-Item`.

Po zmianie modeli uruchom ponownie **tylko `--run`**. `--fetch` świadomie
zastępuje snapshot nowymi danymi z bazy. Same zmiany `TOPICS` nie zmieniają
już pobranego pliku; po wybraniu innych tematów wykonaj ponownie `--fetch`.
Po pobraniu snapshotu połączenie z Supabase nie jest potrzebne.

## Dwa tryby porównania

`mode: "full"`: od początku odczytuje wszystkie artykuły z lokalnego snapshotu,
wyciąga fakty/wypowiedzi/oceny, deduplikuje ustalenia i pisze syntezę.
Możesz osobno zmienić model i poziom rozumowania dla:

| Etap w konfiguracji | Co robi | Co wysyła do modelu |
| --- | --- | --- |
| `extraction` | Odczytuje i klasyfikuje ustalenia | Pełne artykuły, paczki do 8 |
| `audit` | Weryfikuje nowość i powtórzenia | Krótkie ustalenia, paczki do 24 |
| `writing` | Pisze aktualną syntezę i jej kontekst | Wybrane fakty i ograniczone fragmenty źródeł |

Liczba wywołań zależy od rozmiaru wątku i liczby ustaleń. Podział na perspektywy
i prezentacja ocen nie mają osobnych wywołań AI. Nie prosimy modelu o nowe
tytuły i kategorie; te pola zostały usunięte ze schematu ekstrakcji w laboratorium.
Pozostałe prompty i reguły publikacji pochodzą z bieżącego kodu produkcyjnego.

`mode: "writing"` i `facts_from: "nazwa-wcześniejszego-wariantu"`: używa
dokładnie tego samego rejestru faktów co wskazany wariant. Wywołuje tylko
pisanie, zwykle raz. To najlepszy pierwszy test stylu, kompletności i powtórzeń
w syntezie: różnicy nie powoduje inny zestaw wyciągniętych faktów. Perspektywy
i oceny zostają takie same, bo ten test ich ponownie nie ekstrahuje.

Przykładowa konfiguracja zawiera obecny pełny wariant nano i dwa warianty
samego pisania. Pełny test innego modelu jest w komentarzu do odkomentowania.
W bazowym wariancie ustawienia odpowiadają workflow: nano `low` dla ekstrakcji
i audytu, nano `medium` dla pisania.

## Wyniki i koszty eksperymentu

`lab-data/report.html` pokazuje warianty obok siebie: syntezę, dodatkowe
ustalenia/perspektywy i oceny, pełny rejestr faktów, liczbę zapytań, czas,
wejście/wyjście/cache/rozumowanie oraz oszacowany koszt w USD.
Możesz prześledzić artykuły po ID i otworzyć ich oryginalne adresy.

`lab-data/results/<identyfikator>/result.json` zawiera pełny wynik i metadane.
Pliki `call-*.json` zachowują dokładny prompt, wejście, schemat, surową
odpowiedź i użycie tokenów. Przypisane do każdego wywołania ustawienia modelu
pozwalają sprawdzić także przypadki lokalnego odrzucenia faktów lub tekstu.

Identyczny test używa już zapisanego wyniku, **bez ponownych wywołań**.
Zmiana tylko modelu piszącego nie kupuje odczytu artykułów w bazowym wariancie
drugi raz. Błędne próby również są zachowywane. `--run --repeat` jawnie
wykonuje nową płatną próbę wszystkich skonfigurowanych wariantów. Po przerwaniu
procesu w trakcie zapytania program zatrzyma się przy jego śladzie: nie zakłada,
że zerwane połączenie oznacza brak opłaty, i nie ponawia zapytania automatycznie.

Braki i błędne elementy są pomijane według obecnych zasad produkcyjnych,
bez płatnych napraw. Diagnostyka wskazuje, czy synteza użyła tekstu awaryjnego,
czy model pominął artykuły lub czy zabrakło budżetu na etap. Istnieje limit
zapytań na wątek oraz tokenów na wywołanie; nie jest to limit kwoty w USD.

Koszt jest wyliczany z użycia zwróconego przez API. Tokeny rozumowania są
**częścią wyjścia**, nie kolejną opłatą doliczaną do wyjścia. Koszt może być
nieznany po błędzie sieci albo dla modelu bez stawki. Nowe stawki można wpisać
w `PRICE_OVERRIDES`. Szacunek nie uwzględnia dopłat za region, długi kontekst,
zapisy cache ani podatków; nie zastępuje rozliczenia w panelu OpenAI.

## Modele i ceny

Stan sprawdzenia: **23 października 2026**, USD za **milion tokenów**, zwykły
synchroniczny API Standard, wejście bez cache i krótki kontekst.
Punktem odniesienia jest obecny `gpt-5-nano`.

| Model | Wejście | Wyjście łącznie z rozumowaniem | × nano: wejście / wyjście |
| --- | ---: | ---: | ---: |
| `gpt-5-nano` | 0,05 | 0,40 | 1 / 1 |
| `gpt-6-luna` | 0,10 | 0,50 | 2 / 1,25 |
| `gpt-4o-mini` | 0,15 | 0,60 | 3 / 1,5 |
| `gpt-5.4-nano` | 0,20 | 1,25 | 4 / 3,125 |
| `gpt-5-mini` | 0,25 | 2,00 | 5 / 5 |
| `gpt-4.1-mini` | 0,40 | 1,60 | 8 / 4 |
| `gpt-5.4-mini` | 0,75 | 4,50 | 15 / 11,25 |
| `gpt-6.1-sol` | 2,00 | 10,00 | 40 / 25 |
| `gpt-5.4` | 2,50 | 15,00 | 50 / 37,5 |
| `gpt-5.5` | 5,00 | 30,00 | 100 / 75 |
| `gpt-6-astra` | 10,00 | 50,00 | 200 / 125 |

Źródła: [bieżący cennik](https://developers.openai.com/api/docs/pricing),
[nano](https://developers.openai.com/api/docs/models/gpt-5-nano),
[5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini),
[4o mini](https://developers.openai.com/api/docs/models/gpt-4o-mini),
[4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
[5.4 nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano),
[5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini),
[5.4](https://developers.openai.com/api/docs/models/gpt-5.4),
[5.5](https://developers.openai.com/api/docs/models/gpt-5.5).

Nie ma jednego stałego mnożnika ceny całego wątku: modele mogą zużyć inną
liczbę tokenów rozumowania, mieć inny udział cache i wygenerować więcej/mniej
ustaleń. Tabela porównuje **stawki**, raport mierzy rzeczywiste użycie prób.

Najpierw porównałabym samo pisanie przez `gpt-6-luna`, `gpt-5.4-mini`
i obecne nano na trzech różniących się tematach. `gpt-4.1-mini` pozwoli też
sprawdzić model bez osobnego rozumowania. Dopiero potem warto testować droższą
ekstrakcję i audyt. To hipotezy do sprawdzenia, nie wynik benchmarku na Twoich
artykułach.

Starsze modele 4.x, GPT-5 nano/mini i GPT-5.4 nano mają w dokumentacji oznaczenie
`Deprecated`. Ich faktyczna dostępność zależy od konta i harmonogramu wycofania.
`--list-models` sprawdza widoczność dla Twojego klucza bez generowania tekstu.
Konfiguracja przyjmuje też inne modele OpenAI obsługujące Responses API
i Structured Outputs; zgodność parametrów i dostęp trzeba sprawdzić w ich karcie.
Nie podmieniamy modelu automatycznie po błędzie, bo zepsułoby to porównanie.
