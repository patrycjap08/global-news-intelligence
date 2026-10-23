# Pokrycie faktów w syntezie — 23 października 2026

Sprawdzony publiczny wątek: `[Indie] Donalda Tuska powitanie w Indiach`
(`topic_perspectives_efe86fd7a5c0cf982ec81c3d`). Zapisany rejestr zawiera
57 ustaleń FACT/STATEMENT, łącznie 1003 słowa. Bieżąca synteza ma 67 słów
i dwa akapity. Brakuje między innymi celów gospodarczych wizyty, danych
handlowych, sektorów współpracy, planowanych umów i wypowiedzi uczestników.

## Przyczyny

- Wszystkie 57 ustaleń trafia do `main_facts`; wejście pisania ich nie ucina.
- Aktywny prompt żądał krótkiego artykułu, zwykle 2–4 akapitów, do około
  250 słów. Pozwalał zostawiać szczegóły wyłącznie w zakładce Fakty.
- Schemat odpowiedzi dodatkowo ograniczał tekst do 6000 znaków i metadane
  do czterech akapitów. Walidator analizował tylko `supplied[:4]`, więc
  nawet dłuższa odpowiedź mogła stracić poprawną dalszą część.
- W pliku była wcześniejsza, nieużywana definicja `WRITING_INSTRUCTIONS`,
  żądająca wszystkich faktów. Późniejsza definicja zastępowała ją krótkim
  wariantem. To utrudniało rozpoznanie faktycznie wysyłanych instrukcji.
- Walidacja nie raportowała ustaleń pominiętych przez piszący model.

## Zmiana v86

Jedno zapytanie piszące nadal zwraca jeden gotowy `summary_pl` z kontekstem.
Ma objąć wszystkie odrębne informacje z `main_facts`, z zachowaniem liczb,
dat, warunków, autorów wypowiedzi i niepewności. Powtórzenia znaczeniowe
należy opisać raz, łącząc ich identyfikatory przy tym samym akapicie.
Nie chodzi o jedno zdanie lub akapit na każdy wpis rejestru.

Usunięto limit 250 słów, 6000 znaków i czterech akapitów oraz nieużywaną
definicję promptu. Walidacja przechodzi po całej odpowiedzi. Długość ma
wynikać z informacji, bez sztucznego wydłużania. Oceny EDITORIAL pozostają
w osobnej części, poza faktograficzną syntezą. Limit tokenów pojedynczego
żądania i dotychczasowe limity kosztu tematu nadal obowiązują.

`quality_report.writing_validation.fact_coverage` zapisuje oczekiwaną liczbę
ustaleń, liczbę ID powiązanych z zaakceptowanymi akapitami i brakujące ID.
Braki powodują ostrzeżenie w logach, bez kolejnego zapytania do AI. Jest to
kontrola powiązań, nie dowód semantycznego pokrycia każdego szczegółu.
Poprawne akapity są zachowywane. Przy całkowicie niepoprawnej odpowiedzi
awaryjny tekst może wykorzystać wszystkie zaakceptowane ustalenia,
zamiast ograniczać się do pierwszych trzech. Nie jest to ponowne pisanie AI.

## Zakres i weryfikacja

Test odtwarza publiczny rejestr 57 ustaleń, odpowiedź dłuższą niż 6000
znaków i cztery akapity, pominięte ID, błędny późny akapit oraz kilka
duplikujących się ustaleń opisanych jednym zdaniem. Sprawdza także, że
wszystkie ustalenia docierają do jednego pisania i tekst przechodzi przez
normalizację bez ucięcia. Wywołania modelu są zastąpione odpowiedziami
testowymi; test nie ocenia jakości nowo wygenerowanej prozy.

Zmiana nie wymaga migracji ani ponownej ekstrakcji zapisanych faktów.
Nie uruchamia płatnego przebiegu, nie usuwa syntez i nie kwalifikuje
automatycznie dawnych tematów do masowego ponownego pisania. Zapisany
przykład Tuska pozostaje starym tekstem do czasu świadomego ponownego
opracowania lub normalnej aktualizacji po nowych ustaleniach.
