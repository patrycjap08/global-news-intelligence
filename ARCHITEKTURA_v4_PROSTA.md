# Prosta architektura aplikacji — wersja 4

## Decyzja

Najprostszy układ, który spełnia wymagania aplikacji na telefon i nie wymaga płatnego serwera:

- GitHub Actions — uruchamia pobieranie trzy razy dziennie.
- Supabase Free — przechowuje artykuły, tytuły, deduplikację, tematy, agregacje i konto użytkowniczki.
- PWA — aplikacja webowa instalowana na telefonie jak zwykła aplikacja.
- OpenAI API — wykonuje dwa etapy analizy.

GitHub pozostaje miejscem dla kodu, konfiguracji i workflow. Nie zapisujemy całej historii artykułów jako kolejnych commitów, ponieważ repozytorium szybko zaczęłoby rosnąć. GitHub Actions może bezpiecznie korzystać z kluczy zapisanych jako sekrety repozytorium; klucz OpenAI nigdy nie trafia do kodu ani aplikacji telefonu.

## Przebieg jednego uruchomienia

Uruchomienia są trzy razy dziennie, np. rano, w południe i wieczorem. Dokładne godziny mogą być ustawione w UTC w workflow GitHub.

1. Harvester sprawdza skonfigurowane RSS/Atom, news sitemapę, sitemapę i sekcje HTML; strona główna jest fallbackiem, gdy wcześniejsza metoda nie zwróci linków.
2. Z tych metod zbiera linki do artykułów i deduplikuje je przed pobraniem.
3. Dla każdego linku normalizuje adres URL.
4. Sprawdza w bazie unikalny klucz: source_id + canonical_url.
5. Jeśli artykuł już istnieje, nie otwiera go ponownie. Aktualizuje tylko informację, że ponownie pojawił się na stronie głównej.
6. Jeśli artykuł jest nowy, pobiera jego tytuł i treść w oryginalnym języku.
7. W jednym dniu UTC harvester wykonuje maksymalnie 50 nowych prób pobrania na źródło, wspólnie dla trzech uruchomień. Materiał krótszy niż 200 słów jest odrzucany i nie trafia do tabeli artykułów ani do pliku dla AI. Jego adres może trafić wyłącznie do tabeli technicznej odrzuceń, aby nie pobierać go ponownie.
8. Gdy nie ma nowych artykułów, uruchomienie kończy się bez wywołań AI.
9. Gdy pojawiły się nowe artykuły, uruchamiany jest etap AI 1 — grupowanie po tytułach i treści.
10. Dla każdej grupy uruchamiany jest etap AI 2 — przygotowanie lub aktualizacja polskiego opracowania.
11. Aplikacja może pokazywać wątki jeszcze bez syntezy. Każda synteza jest zapisywana od razu po wygenerowaniu i dostępna po odświeżeniu danych, bez czekania na pozostałe tematy ani zakończenie całego przebiegu.

## Reguła niepobierania drugi raz

To jest twarda reguła:

- ten sam canonical_url u tego samego źródła nie jest pobierany ponownie;
- parametry śledzące, takie jak utm_source, są usuwane przed porównaniem;
- przekierowania są zapisywane jako adres końcowy;
- ponowne pojawienie się linku na stronie głównej nie tworzy drugiego artykułu;
- jeśli dwa różne adresy tego samego źródła mają ten sam znormalizowany tytuł i identyczne pierwsze dwa zdania, drugi adres jest zapisywany jako alias, a nie jako drugi artykuł;
- jeśli tytuł jest taki sam, ale pierwsze dwa zdania są inne, materiał pozostaje osobnym artykułem;
- tytuł jest przechowywany bez tłumaczenia i bez nadpisywania;
- jeśli pierwszy zapis miał status FAILED, CAPTCHA albo METADATA_ONLY, można go osobno oznaczyć do kontrolowanej próby ponownej, ale nie będzie automatycznie pobierany przy każdym uruchomieniu.

Ważna różnica: stronę główną trzeba odwiedzać trzy razy dziennie, ale treść artykułu tylko przy pierwszym wykryciu nowego adresu.

## Baza danych

### sources

Katalog źródeł:

- identyfikator i nazwa;
- strona główna;
- kraj lub region;
- profil redakcyjny: LEFT, CENTER_LEFT, CENTER, CENTER_RIGHT, RIGHT, STATE_ALIGNED, OTHER, UNCLASSIFIED;
- typ źródła;
- aktywność;
- techniczne ustawienia zgód i popupów.

Profil redakcyjny jest opisem źródła, a nie oceną prawdziwości artykułu. STATE_ALIGNED jest osobną kategorią dla mediów silnie związanych z państwowym przekazem; nie wciskamy ich sztucznie na oś lewica–prawica.

### articles

Jeden rekord na jeden artykuł:

- article_id;
- source_id i nazwa źródła;
- canonical_url;
- tytuł oryginalny;
- pełna treść oryginalna;
- język oryginalny;
- autor, jeśli został znaleziony;
- czas publikacji, jeśli został znaleziony;
- czas pierwszego pobrania;
- status treści;
- liczba słów;
- hash treści;
- sentyment: początkowo NULL;
- ton: początkowo NOT_ANALYZED.

### article_homepage_sightings

Historia pojawienia się artykułu na stronie głównej:

- article_id;
- źródło;
- czas wykrycia;
- pozycja na stronie, jeśli została znaleziona.

Ta tabela pozwala później sprawdzić, które artykuły były eksponowane przez źródło, bez ponownego pobierania ich treści.

### topic_runs

Jeden rekord na każde grupowanie:

- czas uruchomienia;
- lista nowych artykułów wejściowych;
- hash danych wejściowych;
- model i wersja promptu;
- status;
- surowy wynik AI 1.

Do AI 1 przekazujemy tytuł i pełną treść każdego nowego artykułu, ponieważ sam nagłówek bywa zbyt ogólny. Wynik AI 1 zawiera jednoznaczną, redakcyjną nazwę wątku — szerszą niż pojedynczy nagłówek i pozbawioną clickbaitu — oraz listę artykułów z ich identyfikatorami i tytułami. Ta zasada obowiązuje także dla tematów jednoartykułowych.

### topics

Tematy widoczne w aplikacji:

- stabilny topic_id;
- tytuł polski;
- czas pierwszego i ostatniego artykułu;
- status: NEW, ACTIVE, ARCHIVED;
- pewność grupowania;
- lista artykułów należących do tematu.

### topic_summaries

Wynik AI 2:

- topic_id;
- wersja agregacji;
- hash artykułów wejściowych;
- podsumowanie;
- fakty ze wskazaniem artykułów;
- zgodności i różnice;
- porównanie sposobu przedstawienia tematu;
- sygnały potencjalnej manipulacji;
- kontekst ogólny;
- niewiadome;
- lista źródeł;
- czas wygenerowania.

## Jak nie tworzyć tego samego tematu kilka razy

AI 1 nie dostaje wyłącznie nowych tytułów. Dostaje:

- nowe artykuły wykryte w bieżącym uruchomieniu;
- tematy możliwe do dopasowania z ostatnich 55 godzin (w aplikacji jako
  „Aktualne” są widoczne przez 30 godzin bez nowej aktualizacji);
- poprzedni skrót agregacji każdego z tych tematów.

Dzięki temu nowy artykuł o wydarzeniu z wczoraj może zostać dołączony do istniejącego tematu, zamiast tworzyć drugi prawie identyczny temat.

Po zakończeniu grupowania AI 1 lokalny filtr wyszukuje kandydackie grupy tematów
na podstawie co najmniej trzech wspólnych charakterystycznych rdzeni słów
albo wspólnej frazy z dwóch takich słów. Embeddingi dodają maksymalnie trzech
sąsiadów na temat, przy podobieństwie co najmniej 0.88. Niezależne grupy są
pakowane razem z osobnymi identyfikatorami; wszystkie utworzone paczki
weryfikacji scalania trafiają do AI bez ograniczania ich liczby. Tematy bez lokalnego lub semantycznego podobieństwa
nie trafiają do tego wywołania, a dane każdego kandydata są skrócone do nazwy,
jednozdaniowego opisu i kilku najnowszych nagłówków.

Temat nie powinien być rozumiany jako „wszystko o tej samej osobie”. Grupa oznacza to samo konkretne wydarzenie, decyzję, wypowiedź albo rozwój tej samej sprawy. Osobny materiał o tej samej osobie, ale o innym wydarzeniu, pozostaje osobnym tematem.

Jeżeli AI nie ma wystarczającej pewności, tworzy osobną grupę z oznaczeniem needs_review, zamiast wymuszać połączenie.

AI 1 rozróżnia nowy temat, dalszy ciąg istniejącego tematu oraz materiał
uzupełniający. Przy dalszym ciągu AI 2 dostaje poprzednią agregację i nowe
artykuły, a nie tworzy drugiego niezależnego opracowania. Pierwsze opracowanie
tematu powstaje z pełnych artykułów należących do grupy; kolejne wersje są
aktualizowane przyrostowo i zachowują historię wersji.

## UX na telefonie

### Ekran główny

- nagłówek: „Najnowsze tematy”;
- karty tematów posortowane od najnowszych;
- polski tytuł tematu;
- jednozdaniowe „co się wydarzyło”;
- liczba źródeł i artykułów;
- godzina aktualizacji;
- małe znaczniki perspektyw: lewica, centrum, prawica, inne;
- oznaczenie „trwający temat”, gdy pojawiają się nowe artykuły.

### Widok tematu

Kolejność informacji:

1. krótkie podsumowanie;
2. najważniejsze fakty z linkami do artykułów;
3. o czym źródła są zgodne;
4. gdzie się różnią;
5. jak różnie opisują temat źródła o różnych profilach;
6. oś czasu;
7. sygnały potencjalnie manipulacyjnego języka lub brakującego kontekstu;
8. niewiadome i rzeczy wymagające dodatkowej weryfikacji;
9. pełna lista artykułów z oryginalnymi tytułami i linkami.

„Potencjalna manipulacja” będzie domyślnie zwinięta i opisana jako sygnał do samodzielnego sprawdzenia, a nie jako automatyczny wyrok.

### Filtry

- wszystkie;
- Polska / świat;
- polityka / gospodarka / społeczeństwo / wojna i bezpieczeństwo / technologie / inne;
- nowe od ostatniej wizyty;
- tematy z różnicami między źródłami;
- źródła według profilu redakcyjnego.

### Dostęp offline

PWA może przechować ostatnio otwarte podsumowania i listę tematów. Pełny artykuł pozostaje dostępny przez link do źródła, jeśli użytkowniczka ma do niego dostęp.

## Koszt i ograniczenia

GitHub Actions jest dobrym darmowym schedulerem. Dla prywatnego repozytorium GitHub Free ma miesięczny limit minut, dlatego trzeba mierzyć czas harvestera, zwłaszcza gdy używany jest Playwright. Jeśli okaże się, że trzy uruchomienia są zbyt długie, ograniczymy przeglądarkę do źródeł, które jej rzeczywiście potrzebują, albo przeniesiemy wykonawcę do innego darmowego runnera.

Supabase Free jest wystarczający dla pierwszej wersji, ale ma limity. Dlatego:

- przechowujemy pełne treści tylko raz;
- agregacje są zapisywane i nie są generowane ponownie bez zmiany danych;
- starsze dane można później archiwizować;
- wykonywane są kopie eksportowe bazy.

## Kolejność implementacji

1. Zastąpić lokalne SQLite docelowym zapisem do Supabase.
2. Dodać workflow GitHub Actions uruchamiany trzy razy dziennie.
3. Przenieść regułę deduplikacji do unikalnego indeksu w bazie.
4. Dodać AI 1 i zapis grup.
5. Dodać AI 2 i zapis agregacji.
6. Zbudować PWA z widokiem listy i widokiem tematu.
7. Dodać ręczne uruchomienie workflow oraz ekran diagnostyki źródeł.
8. Dopiero po obejrzeniu kilku pełnych cykli dopracować kategorie i wygląd.
