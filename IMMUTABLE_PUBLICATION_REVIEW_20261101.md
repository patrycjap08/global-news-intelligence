# Pierwsza synteza, skrót i aktualizacje — 1 listopada 2026

## Przyczyna

Pierwsza publikacja była zachowywana w `base_summary`, ale interfejs wybierał
przepisywane `current_summary`. Pierwszy tekst pojawiał się tylko jako zwijane
archiwum. W danych zachowywano aktualizacje, lecz interfejs je ukrywał.

## Nowy kontrakt

- Pierwsza synteza i pierwszy skrót są główną treścią widoku i pozostają
  niezmienne. Zapis chroni je także wtedy, gdy odpowiedź zawiera inny tekst.
- Kolejne analizy czytają nowe lub zmienione artykuły i porównują przyjęte
  ustalenia z dotychczasowym rejestrem. Nowy fakt, wypowiedź lub ocena
  redakcyjna tworzy datowaną aktualizację. Nowe potwierdzenie aktualizacji
  nie tworzy. Profil źródła oceny może być lewicowy, prawicowy lub centrowy.
- Aktualizacja wykorzystuje zaakceptowane ustalenia i przypisania źródeł.
  Nie uruchamia ponownego pisania całej syntezy ani skrótu.
- Po technicznym scaleniu nieopublikowane wcześniej ustalenia przechodzą
  kontrolę nowości bez ponownego czytania przetworzonych artykułów.
- Strona pokazuje aktualizacje od najnowszej i nie powtarza ich ocen
  w części ocen z pierwszej publikacji. Zwijane archiwum pierwszego tekstu
  oraz archiwum dołączonych publikacji znikają z widoku. Dane pozostają.
- Skrót powstaje w zapytaniu piszącym pierwszą syntezę. Domyślnie ma dwa
  akapity. Dla złożonej sprawy instrukcja i walidacja dopuszczają trzy lub
  cztery, bez wydłużania dla samej długości.
- Starsza publikacja bez skrótu może dostać jedną próbę uzupełnienia
  na podstawie jej pierwotnych ustaleń lub samego pierwszego tekstu. To nie
  zmienia syntezy, istniejącego skrótu ani oznaczenia przeczytania.
- Laboratorium modeli nadal może pisać niezależny szkic na tym samym
  rejestrze przez `draft_publication`. Ten tryb nie nadpisuje publikacji.

## Weryfikacja i ograniczenia

479 testów Pythona oraz 14 zestawów testów JavaScript przechodzi.
Regresje obejmują zapis niezmiennej pierwszej publikacji, osobne aktualizacje
faktów i ocen wszystkich trzech profili, brak aktualizacji dla potwierdzeń,
scalenie bez ponownego odczytu artykułów, elastyczny skrót, stare aktualizacje
w jednym przebiegu oraz zgodność laboratorium. Test przeglądarkowy Chromium
przy szerokości 390 px potwierdza początkowy tekst, widoczną aktualizację,
pojedynczą kartę oceny i brak archiwalnego nagłówka.

Nie uruchomiono płatnego AI, pobierania artykułów ani resetu danych. Nie jest
potrzebna migracja bazy. Historyczne treści nie są masowo regenerowane.
Kontrola nowości i zgodności znaczenia nadal zależy od modelu i opisanych
heurystyk. Identyfikatory faktów nie stanowią dowodu semantycznej poprawności.
