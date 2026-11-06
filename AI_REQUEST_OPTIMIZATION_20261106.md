# Mniejsze wejście zapytań AI — v90

Zmiana dotyczy transportu zapytań i dwóch etapów nadawania nazw. Nie uruchamia
ponownej analizy, nie usuwa faktów i nie zmienia zasad publikacji aktualizacji.

## Modele

| Etap | Przed zmianą | Po zmianie |
| --- | --- | --- |
| Robocza nazwa wątku dla artykułu, decyzja o zakresie | GPT-6 Luna, none | GPT-5 Nano, minimal |
| Poprawianie tytułów | GPT-6 Luna, none | GPT-5 Nano, minimal |
| Kategorie | GPT-6 Luna, none | Bez zmian |
| Ekstrakcja i kontrola nowości | GPT-6 Luna, low | Bez zmian |
| Pisanie syntezy, kontekstu, skrótu i aktualizacji | Dotychczasowe ustawienia Luny | Bez zmian |
| Embeddingi | text-embedding-3-small | Bez zmian |

Według [cennika](https://developers.openai.com/api/docs/pricing) i
[karty Nano](https://developers.openai.com/api/docs/models/gpt-5-nano),
sprawdzonych 6 listopada 2026, standardowe stawki za milion tokenów bez cache
wynoszą: Nano 0,05 USD wejście / 0,40 USD wyjście, Luna 0,10 / 0,50 USD.
To niższa stawka wejścia o 50%, wyjścia o 20%. Nie oznacza stałej oszczędności
całego przebiegu: liczba tokenów odpowiedzi i rozumowania zależy od modelu.
Nano otrzymuje minimalne rozumowanie tylko w nazwach i tytułach. Ręcznie
ustawiony poziom rozumowania pozostaje respektowany.

[OpenAI zapowiada wyłączenie Nano i jego snapshotów 11 grudnia 2026](https://developers.openai.com/api/docs/deprecations).
Od tej daty produkcyjne nazwy i tytuły wybiorą Lunę automatycznie. Inne
jawnie ustawione modele pozostają bez zmian. Guard nie wymaga zapytania API.
Laboratorium porównań nie podmienia samodzielnie wybranego modelu.

## Wejście i instrukcje

- JSON nie zawiera spacji po separatorach. Odstępy, akapity i tabulatory
  wewnątrz pełnych artykułów pozostają dokładnie takie same.
- `content_hash` i `canonical_url` są pomijane tylko w listach artykułów
  wysyłanych do modelu. Oryginalny payload pozostaje nienaruszony. Hash nadal
  wykrywa zmienione treści, a URL pozostaje w bazie i materiałach źródłowych.
- ID artykułów, pełne treści, język, daty, nazwy, typy i profile źródeł,
  poprzednie ustalenia i ich przypisania są zachowane.
- Audyt, pisanie i osobny skrót nie dostają reguł dotyczących pól tytułów,
  których nie zwracają. Blok 1110 znaków zastępuje reguła językowa 189 znaków.
  To 921 znaków mniej w samym bloku instrukcji. Nie jest to pomiar tokenów
  ani kosztu rzeczywistych zapytań.
- Etapy zwracające tytuł, w tym produkcyjna ekstrakcja z `headline_pl`, nadal
  dostają pełne reguły polskich tytułów. Przy nieznanym schemacie są zachowywane.
- W laboratorium usunięto również niepasujące polecenie tworzenia tytułu i
  kategorii. Schemat laboratorium już wcześniej nie dopuszczał tych pól.

Nie skracano głównych promptów ekstrakcji, audytu nowości, syntezy ani skrótu.
Ich porównanie SHA-256 z wersją sprzed zmiany dało identyczne wyniki. Nie
zmieniono schematów produkcji, walidacji, klasyfikacji FACT/STATEMENT/EDITORIAL,
reguł autorstwa ocen, deduplikacji, budżetów, retry ani pełnej historii ustaleń.

## Wznowienie i sprawdzenie

Projekcja danych następuje dopiero przy budowaniu zapytania API. Klucze
checkpointów i cache artykułów są identyczne z v89 dla tego samego materiału.
Zmiana treści nadal unieważnia odpowiednie trafienie. Wersji ekstraktora nie
podnoszono. Nowa wersja promptu służy oznaczeniu nowych wywołań w logach.

Testy obejmują faktyczne argumenty SDK z atrapą odpowiedzi, nienaruszone pełne
teksty i metadane, zgodność kluczy wznowienia, pełne instrukcje poszczególnych
etapów, połączoną ocenę z różnych źródeł, datę przejścia na Lunę i zgodność
laboratorium. Bez płatnych zapytań OpenAI, uruchamiania harvestu i zmian w bazie.
Jakości nowych odpowiedzi Nano ani kosztu całego przebiegu nie mierzono na API.

Weryfikacja: `python -m unittest discover -q` — **488 testów, OK**.
