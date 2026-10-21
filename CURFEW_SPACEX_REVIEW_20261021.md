# Kontrola faktów i syntez: Francja oraz SpaceX

Sprawdzone dane: publiczny eksport z 21 października 2026, 09:42:23 UTC,
generacja `33e7ba0d246895d567ca`. Wcześniejsze opracowanie francuskie pochodzi
z eksportu 04:55 UTC, generacja `ded1b21dd927e527f0d4`.

## Godzina policyjna w odpowiedzi na zamieszki

Wcześniejszy rejestr zawierał 85 ustaleń, w tym 81 w zakładce Fakty.
To nie było 85 różnych wiadomości. Przykłady powtórzeń znaczenia:

| Ustalenia w poprzednim rejestrze | Ocena |
| --- | --- |
| Laurent Nunez „poinformował”, że wojska Sentinelle będą wspierać policję podczas demonstracji; Nunez „oświadczył”, że wojska Sentinelle zostaną rozmieszczone, by wspierać policję podczas protestów | Ta sama zapowiedź, inne słowa. |
| Nunez zapowiada RAID, GIGN, BRI, helikoptery, pojazdy Centaure i armaty wodne; plan obejmuje tę samą listę sił i sprzętu | Powtórzenie informacji; zapisano ją też z różnymi typami FACT/STATEMENT. |
| W Bordeaux od wtorku wprowadzono godzinę policyjną dla nieletnich bez dorosłych; w Bordeaux obowiązywała godzina policyjna dla nieletnich bez dorosłych | Wspólny rdzeń; pierwszy zapis dodaje termin. |
| Macron nie przyjął dymisji Nuneza; Pałac Elizejski polecił nowe metody działania; Macron utrzymał Nuneza na stanowisku i zlecił nowe metody działania | Trzeci zapis ponownie łączy dwie wcześniejsze informacje. |
| Wprowadzono lokalne, częściowe godziny policyjne w kilku miastach; rząd wprowadza godziny policyjne w niektórych miastach | W dużej części ten sam opis. Bez dat i źródeł nie należy udawać, że znamy dokładnie relację czasową tych wersji. |

Przyczyną rozrostu była kumulacja zapisów po scalaniu tematów i aktualizacjach.
Lokalne porównanie identycznego tekstu nie usuwa parafraz. Różnice klasyfikacji
również pozostawiały ten sam przekaz w kilku zapisach. Audyt nowych kandydatów
nie oznacza pełnej ponownej deduplikacji całego odziedziczonego rejestru.

Najnowszy zapis zawiera 6 ustaleń: 5 kart w Faktach i jedną ocenę. Te pięć kart
opisuje zapowiedź lokalnych ograniczeń, ich późniejszą ocenę i rozszerzenie,
ostrzeżenie polskiego MSZ, decyzję dotyczącą ministra oraz szerszy bilans
zamieszek. Nie są pięcioma parafrazami jednej informacji. Niektóre są jednak
zbyt złożone: jedna karta łączy kilka szczegółów, zamiast jednego ustalenia.

Spadek z 85 do 6 nie jest miarą skuteczności samej deduplikacji. W raporcie
ekstrakcji są także odrzucenia z powodu braku dosłownego cytatu. Nie można
twierdzić, że wszystkie usunięte pozycje były duplikatami.

Liczby zatrzymanych, np. 2231, około 2331 i ponad 2400, nie są automatycznie
tym samym faktem. Trzeba zachować źródło, zakres i czas pomiaru; mogą to być
aktualizacje lub rozbieżności. Nie wprowadzono arbitralnego limitu pięciu kart
ani ukrywania różnych liczb przez przybliżone porównanie słów.

## Udziały SpaceX dla dzieci obiecane przez Elona Muska

Wątek `topic_perspectives_8eff32214c2a5a89a6798c6c` ma pięć przyjętych ustaleń.
Pierwsze zawiera samą obietnicę Muska: przekazanie w przyszłym roku po jednej
akcji SpaceX każdemu dziecku w USA. Opublikowana synteza pomija tę obietnicę,
a opisuje tylko wycenę, liczbę dzieci i niejasne warunki. Jest więc niepełna.

W rejestrze są różne szacunki: około 146 USD i 73 mln dzieci oraz około
150 USD i 72 mln dzieci, z szacunkiem 10,8 mld USD. To nie są tekstowe duplikaty
do bezwarunkowego zlania. Informacja o funduszu Anthropic jest dodatkowym
porównaniem, nie sednem obietnicy Muska.

Kod sprawdzał każdy akapit osobno, ale nie sprawdzał, czy po odrzuceniu
niepoprawnego akapitu pozostała główna informacja. Lokalny test odtwarza taki
wynik: fakt zawiera cytat angielski, jego polskie streszczenie może nie przejść
heurystyki podobieństwa, a akapit o liczbach nadal zostaje. Publiczny eksport
nie zawiera surowej odpowiedzi piszącego modelu, więc nie rozstrzyga dokładnego
powodu odrzucenia pierwotnego akapitu w tym konkretnym wywołaniu.

## Zmiany

- Dialog nie pokazuje historii aktualizacji ani powtarzanych etykiet rodzaju
  ustalenia i „Autor:”. Źródła i rozwijane dosłowne fragmenty pozostają.
- Pisanie otrzymuje identyfikator głównej informacji i ma od niej zacząć.
- Częściowo poprawna odpowiedź nie może pominąć tej informacji. W razie potrzeby
  kod zachowuje jej przyjęte brzmienie, bez płatnej próby naprawy.
- Przy następnym AI-only ewidentnie niepełna bieżąca publikacja może dostać
  jedno ponowne pisanie z zapisanego rejestru. Nie wymaga wysyłania artykułów
  ani nowego audytu faktów. Po uzupełnieniu nie kwalifikuje się ponownie z tego
  samego powodu. To ograniczona heurystyka pominięcia rdzenia, nie dowód pełnej
  semantycznej kompletności syntezy.

Testy korzystają z ograniczonego zestawu danych tego publicznego eksportu.
Nie uruchomiono płatnego workflow ani zmian danych produkcyjnych.
