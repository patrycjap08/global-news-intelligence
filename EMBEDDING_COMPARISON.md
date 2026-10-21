# Porównanie dwóch tekstów embeddingów

Workflow `GNI — porównanie embeddingów bez scalania` jest niezależny od full,
AI-only, jednego źródła i eksportu Pages. Czyta tylko metadane wybranych wątków,
zapisane opisy/syntezy i nagłówki artykułów. Nie pobiera treści artykułów,
nie generuje opisu przez GPT i nie zmienia niczego w Supabase.

Domyślnie wybiera osiem wątków Francji z rozmowy. W Actions → Run workflow
można pozostawić listę pustą lub wkleić od 2 do 20 `topic_id`.
Pierwsze uruchomienie może wyzwolić push na izolowaną gałąź
`diagnostics/embedding-france-20261019`; push na main nie uruchamia obliczenia.

- A: dokładna produkcyjna funkcja `_topic_embedding_text`: tytuł do 300 znaków
  i bieżący krótki opis do 650 znaków.
- B: tylko aktualny tytuł i pełny zapisany krótki opis, bez syntezy i nagłówków.

Opis nie jest gwarantowany dla każdego kandydata: powstaje przy pierwszej
syntezie, a przy samych państwowych materiałach może pozostać pusty. Brak opisu
zatrzymuje porównanie przed wywołaniem API, bez zastępowania go innym tekstem.
Przekierowane wątki zachowują wskazane ID i jawny status w raporcie.

Oba warianty dostają ten sam snapshot odczytu, model `text-embedding-3-small`
i liczbę wymiarów jak workflow główny. Jedno zapytanie embeddingów obejmuje
do 16 tekstów dla 8 wątków (identyczne teksty są deduplikowane).
Od v74 warianty często są identyczne; wtedy wysyłane jest tylko 8 tekstów. Pozostałe
obliczenia są lokalne. Nie ma wywołań modelu czatu. Ponowienia API zachowują
dotychczasowy limit; użycie tokenów trafia do raportu.

Artefakt przebiegu zawiera `pairs.csv` ze WSZYSTKIMI parami, `report.json`
z dokładnymi tekstami i wektorami, `summary.md` oraz samodzielny `report.html`.
HTML pokazuje obie macierze i suwak progu z symulacją obecnego grupowania
dwoma stałymi punktami odniesienia. Warianty zachowują rozdział formatów
i stosują ten sam próg do wszystkich tematów. Nowy raport startuje z obecnym
progiem produkcyjnym 0,78. Zakres suwaka 0,35–0,95 pozwala porównać również skalę
wariantu B. Symulacja obejmuje tylko wskazany zestaw, nie wszystkie aktywne
wątki; niższy próg nie musi zmniejszać liczby grup przy obecnej regule dwóch
punktów odniesienia. Niskie wartości nie są rekomendacją dla produkcji.
Raport nie ocenia, czy zbliżone wydarzenia powinny być
jednym wątkiem; wynik nie zmienia produkcyjnego progu.

Symulacja pokazuje grupowanie według obu kotwic w wybranym zestawie. Nie
stosuje produkcyjnego filtra konkretnego zdarzenia ani podziału nowe/stare;
nie jest prognozą liczby scaleń w zwykłym przebiegu.
