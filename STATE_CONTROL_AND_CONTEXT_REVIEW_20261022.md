# Kontrola państwowa i akapit tła — 22 października 2026

## Korekta listy źródeł

Dotychczasowe `STATE_ALIGNED` obejmowało 10 pozycji. To nie jest dowód kontroli
państwa: dwa prywatne tytuły były sklasyfikowane zbyt szeroko. Nie opieramy
blokady pobierania na tej etykiecie, narodowości ani finansowaniu publicznym.

| Źródło | Podstawa oceny | Decyzja |
| --- | --- | --- |
| Xinhua | [Państwowa agencja, instytucja ChRL](https://en.wikipedia.org/wiki/Xinhua_News_Agency) | Wyłączone |
| CGTN | [Kontrola chińskiego aparatu partyjnego](https://en.wikipedia.org/wiki/China_Global_Television_Network) | Wyłączone |
| China Daily | [Właściciel: wydział propagandy KPCh](https://en.wikipedia.org/wiki/China_Daily) | Wyłączone |
| Global Times | [Należy do partyjnego People's Daily](https://en.wikipedia.org/wiki/Global_Times) | Wyłączone |
| TASS | [Federalne przedsiębiorstwo rządu Rosji](https://en.wikipedia.org/wiki/TASS) | Wyłączone |
| RIA Novosti | [Rossiya Segodnya, rząd Rosji](https://en.wikipedia.org/wiki/RIA_Novosti) | Wyłączone |
| RT | [Sieć kontrolowana przez państwo rosyjskie](https://en.wikipedia.org/wiki/RT_(TV_network)) | Wyłączone |
| Ukrinform | [Narodowa agencja działająca na podstawie regulacji Rady Ministrów](https://en.wikipedia.org/wiki/Ukrinform) | Pozostaje wyłączone; było nieaktywne już wcześniej |
| Caixin | [Prywatni udziałowcy; CMC i Tencent, odnotowane powiązania i cenzura](https://mediabiasfactcheck.com/caixin-global/) | Pozostaje aktywne |
| Kommersant | [Prywatna własność Aliszera Usmanowa; powiązania z Kremlem](https://mediabiasfactcheck.com/kommersant/) | Pozostaje aktywne |

Weryfikacja tych 10 pozycji daje **7 nowo wyłączonych aktywnych źródeł**
i jedną pozycję już nieaktywną. Własność prywatna nie oznacza braku presji
politycznej; w przypadku dwóch ostatnich tytułów nie utożsamiamy takich
powiązań ani cenzury z bezpośrednią kontrolą państwowej agencji.

Katalog ma jawne `state_controlled`. Potwierdzone identyfikatory i jawny typ
`STATE_MEDIA` blokują pobieranie niezależnie od `enabled:true`. Sama etykieta
`STATE_ALIGNED` już go nie blokuje. Dotyczy to harmonogramu, pojedynczego
źródła, bezpośredniego harvestera i testera. Nie usuwamy historycznych artykułów.

Caixin i Kommersant otrzymują `CENTER_RIGHT` zgodnie z powyższymi ocenami
MBFC, niezależnie od oceny własności. Stare błędne etykiety są korygowane
przy przygotowaniu danych dla AI i w indeksie przeglądarki, bez mutowania
historycznego eksportu. Nie przebudowujemy automatycznie starego rejestru faktów.

## Tło całej sprawy

Poprzedni format wymagał, aby każdy akapit wskazywał fakty wydarzenia i po
usunięciu dodatków kontekstowych nadal je opisywał. Samodzielny akapit tła
nie mieścił się w tym kontrakcie. Zwiększanie liczby objaśnień osób nie
rozwiązywało tego problemu.

W v80 jedno zapytanie piszące wymaga osobnego, niepustego `situation_context`.
Program wstawia go jako **drugi akapit samej syntezy**, bez kafelka i nagłówka.
Ma wyjaśniać przedmiot sprawy, poprzedzające wydarzenia lub mechanizm,
zamiast powtarzać bieżące doniesienie. Korzysta z zapisanych faktów,
ograniczonych fragmentów pobranych źródeł i dopuszczonej wiedzy ogólnej.
Nie wymaga identycznych liczb ani przypisu do faktu wydarzenia. Nie staje się
nowym faktem źródłowym, aktualizacją ani domniemanym potwierdzeniem artykułu.

Objaśnienia podmiotów mają limit dwóch na syntezę, zwykle po 3–8 słów.
Krajów i oczywistych skrótów nie objaśniamy. Kod blokuje m.in. definicję USA,
a przeglądarka usuwa już zapisane czyste rozwinięcia typu „USA (Stany Zjednoczone)”.
Zachowuje istotne dopiski, np. „USA (po ostatnich wyborach)”.

Aktualne opracowania w nowym formacie bez wersji akapitu tła kwalifikują się
do jednej próby pisania z zachowanych faktów, w istniejącym oknie kolejki.
Nie wysyłamy ponownie pełnych artykułów. Wersja próby zapisuje się także
przy brakującym lub niepoprawnym tle, aby nie tworzyć płatnej pętli napraw.
W takim przypadku błędne tło jest pomijane, a status widoczny w logu.
Kontrola formatu i zgodności tematu nie jest niezależnym sprawdzeniem prawdy
wiedzy ogólnej modelu. Nie uruchamiano płatnego workflow.

Testy obejmują blokadę przed HTTP i otwarciem bazy, zachowanie prywatnych
źródeł, rzeczywiste fakty z wątków Witkoffa i Pegasusa z symulowanym pisaniem,
odrzucenie akapitów wydarzenia, trwałość metadanych i brak ponownego wywołania.
Podgląd na telefonie i komputerze używał faktycznego rejestru Witkoffa
oraz symulowanej odpowiedzi piszącej, nie nowej publikacji w Supabase.
