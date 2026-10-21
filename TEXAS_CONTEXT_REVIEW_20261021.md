# Brak kontekstu w temacie o listach w Teksasie

Przykład: `topic_perspectives_e84ae96c37928ee8c95d7cb6`, eksport publiczny
z 21 października 2026, 09:42 UTC, generacja `33e7ba0d246895d567ca`.
Zapis zawiera trzy fakty i pusty `background_context`. Narracja używa TENT
i USPS bez objaśnienia. Publiczny eksport nie zawiera surowej odpowiedzi
piszącego modelu, więc nie da się ustalić dokładnego brzmienia odrzuconego tła.

## Co można było wyjaśnić

- [CBS News](https://www.cbsnews.com/texas/news/transgender-mailers-flood-texas-2026-midterms/)
  opisuje rejestrację Texas Transgender Student Union LLC we wrześniu 2026,
  adres usługi rejestrowej w Wyoming oraz rozwija nazwę USPS.
- [HuffPost](https://www.huffpost.com/entry/fishy-trans-resources-letters-sent-to-families-spark-confusion-in-texas_n_6ad7dad9e4b04f71533d7a0a)
  wskazuje, że TENT działa od 2010 i że ulotka odsyła do tej organizacji po
  informacje o opiece afirmującej płeć.

To pozwala odróżnić organizację wymienioną w ulotce od spółki podanej jako
nadawca. Sama rejestracja lub adres nie dowodzą, kto faktycznie wysłał listy.
Nie należy dopisywać misji organizacji ani motywów nadawcy bez źródła.

## Przyczyna i zmiana

Pisanie otrzymywało wybrane główne fakty, a lokalna walidacja kontekstu
wymagała oparcia jego treści i liczb w tych faktach. Daty 2010 i 2026 nie
występują w trzech zaakceptowanych ustaleniach. Zapisany zestaw nie dawał
więc piszącemu ani walidatorowi podstawy do wykorzystania tego tła.

v76 usuwa osobny kafelek kontekstu zgodnie z ostateczną decyzją produktową.
Potrzebne objaśnienia i tło trafiają do samej syntezy. Model może dodać
ugruntowaną wiedzę ogólną spoza artykułów, a to samo zapytanie otrzymuje
opcjonalnie krótkie fragmenty lokalnych źródeł. Mniej znane osoby wymagają
krótkiej informacji o funkcji; organizacje i skróty — rozwinięcia i opisu
roli. Prezydenci i państwa nie wymagają przedstawiania.

Nie dodano zapytań naprawczych ani ponownej ekstrakcji. Bieżące zdarzenia
nadal wymagają powiązania z rejestrem faktów. Oznaczone dodatki kontekstowe
są audytowane osobno i nie udają nowych faktów potwierdzonych źródłowo.
Wiedza modelu nie jest weryfikowana niezależnym API; niepewne informacje
mają zostać pominięte. Starych kafelków nie dokleja się do narracji.

Ten temat kwalifikuje się do jednej próby pisania bez nowych artykułów.
Wersja próby zapisuje się również przy braku dodatków, aby nie wywoływać
pisania w pętli. Nie regenerujemy automatycznie wszystkich publikacji.

## Weryfikacja

`test_inline_context.py` sprawdza przypadek na krótkich fragmentach źródeł,
objaśnienia z wiedzy ogólnej i tło w narracji, brak nowych faktów/aktualizacji,
limit wejścia i brak kolejnego wywołania po zakończonej próbie. Odpowiedzi
modelu są symulowane; nie uruchamiano płatnego AI-only ani nie zmieniano
zapisanego opracowania. Test frontendowy sprawdza ukrycie dawnych kafelków.
