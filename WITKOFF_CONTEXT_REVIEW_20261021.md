# Brak kontekstu w syntezie o Witkoffie

Wątek `topic_perspectives_912ce85ac69a6a99128ed97b`, publiczny eksport
`30e5c870e1c5b4b1033b` z 21 października 2026, 16:25 UTC.
Powstał w przebiegu `harvest_20261021T153326Z` na kodzie v77, już po
wprowadzeniu polecenia dodawania kontekstu. Nie jest to stary eksport.

## Ustalenia

Zapis zawiera 11 ustaleń. Wśród nich są spotkanie w Petersburgu,
uwolnienie Stephena Hubbarda i podziękowanie Witkoffa dla Putina.
Narracja składa się jednak z trzech pierwszych ustaleń o krytyce Tillisa,
z prefiksami źródeł dokładnie odpowiadającymi lokalnemu tekstowi awaryjnemu.
Nie przedstawia żadnej z mniej znanych osób i nie wykorzystuje dostępnego
tła wydarzenia.

Log joba `119312526525` potwierdza trzy zapytania: ekstrakcję, audyt nowości
i pisanie. Pisanie zakończyło się o 16:17:57 UTC. Raport zapisuje zero
zaakceptowanych dodatków kontekstowych, ale nie zapisywał liczby odrzuconych
akapitów ani przyczyn. Surowej odpowiedzi piszącego nie ma w publicznym
eksporcie; nie można ustalić, który dokładnie warunek walidatora zawiódł
ani czy odpowiedź zawierała pustą listę akapitów.

W kodzie potwierdzono dwie luki: awaryjny tekst nie zachowywał objaśnień
z odrzuconego akapitu, a mimo to dostawał `inline_context_version=1`.
Kolejka traktowała go potem jako już opracowany. Dobór fragmentów do pisania
szukał przede wszystkim instytucji, prawa i historii, pomijając sygnały
takie jak „senator” i „wysłannik”.

## Dostępne objaśnienia

[WP: reakcja Tillisa](https://wiadomosci.wp.pl/senator-usa-o-slowach-witkoffa-zenujace-i-oburzajace-7342473977104416a)
przedstawia go jako republikańskiego senatora i opisuje podziękowanie za
uwolnienie Hubbarda. [WP: spotkanie](https://wiadomosci.wp.pl/szokujace-slowa-witkoffa-o-putinie-wychwalal-go-na-spotkaniu-7342440298907744a)
przedstawia Witkoffa jako specjalnego wysłannika prezydenta USA oraz Hubbarda
jako amerykańskiego obywatela przetrzymywanego od 2022 roku.
To pozwala wyjaśnić role i okoliczności bez dodatkowych zapytań do AI.

## Zmiana v78

To samo zapytanie piszące zwraca krótkie objaśnienia podmiotów niezależnie
od akapitów. Kod wstawia je w nawiasach przy pierwszym użyciu nazwy,
również do tekstu awaryjnego, jeśli akapity odpadły. Nazwa musi występować
w dopuszczonym fakcie i w publikowanym tekście. Opisy nie trafiają do
rejestru faktów ani nie stają się aktualizacjami. Kompletny JSON niespełniający
schematu jest też sprawdzany element po elemencie; uciętej odpowiedzi nie
odzyskujemy. Źródłowe role mają
wyższy priorytet przy lokalnym doborze fragmentów, przy tych samych limitach
trzech źródeł i 3600 znaków. Prompt wymaga też okoliczności wypowiedzi,
zamiast kilku powtórzeń reakcji.

Raport i log podają liczbę przyjętych akapitów, przyczyny odrzucenia,
użycie tekstu awaryjnego i liczbę objaśnień. Rozpoznawalne stare kopie
faktów bez kontekstu kwalifikują się do jednego ponownego pisania z już
zapisanych ustaleń. Po próbie zapisuje się wersja 2, również jeśli model
nie doda objaśnień. Nie ma ponownej ekstrakcji, pętli naprawczej ani
regeneracji wszystkich opracowań.

Testy używają rzeczywistego zapisu oraz krótkich fragmentów publicznych
źródeł, ale symulowanej odpowiedzi modelu. Sprawdzają zwykłe pisanie,
odrzucenie akapitu ze złą datą, zachowanie objaśnień, niezmienność faktów,
zapis w bazie, kolejkę i brak ponownego wywołania. Nie uruchamiano płatnego
workflow ani nie zmieniano zapisanego tekstu w Supabase. Zmiana istniejącej
syntezy nastąpi przy kolejnym AI-only w oknie aktywności wątku.
