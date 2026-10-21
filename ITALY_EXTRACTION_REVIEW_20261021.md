# Pusty wątek protestów przewoźników we Włoszech

Wątek `topic_perspectives_d87167e2aade98914ada6c99`, publiczny eksport
`9de77afe249dab55c087` z 21 października 2026, 11:12 UTC.

Zapis zawiera siedem artykułów: sześć z centrowego Corriere della Sera i jeden
z La Repubblica. To dwa portale, nie sześć niezależnych źródeł centrowych.
Profil polityczny sam w sobie nie rozstrzyga prawdziwości ani typu treści.

## Przyczyna pustego widoku

Raport zapisanej analizy pokazuje odczyt wszystkich siedmiu artykułów,
jedno zapytanie AI i siedem odrzuconych ustaleń. Każde odrzucono z powodu
braku dosłownego fragmentu potwierdzającego ustalenie. Nie zachowano żadnego
faktu ani oceny, więc etap pisania nie został uruchomiony.

Publiczny eksport nie zawiera surowej odpowiedzi ekstraktora. Nie można
z niego ustalić, czy cytaty były tłumaczeniami, parafrazami, miały inną
typografię czy nie odpowiadały treści. Można ustalić, że o pustym wyniku
zdecydowała walidacja cytatów, a nie nieobecność centrowych artykułów.

Interfejs opisał ten stan jako brak neutralnych ustaleń i dostępność
perspektyw. Druga część była nieprawdziwa — żadnych perspektyw nie zapisano.

## Zmiana v77

Zgodnie z decyzją użytkowniczki usunięto rozwijane cytaty i wymóg podawania
`evidence_quote` przez ekstraktor. Pełne artykuły nadal są odczytywane;
ustalenie wskazuje konkretny artykuł przez klucz w `article_results`.
Pozostały kontrole struktury, typu, jednoznacznego podmiotu, przypisania
do artykułu, autora wypowiedzi/oceny i odwołań do znanych faktów.
Zgodność znaczenia z artykułem pozostaje zadaniem modelu.

Nie dodano identyfikatorów bloków, indeksów tekstu, dodatkowej weryfikacji AI
ani ponownych prób poprawy odpowiedzi. Cache używa nowej wersji ekstraktora.
Historyczne cytaty pozostają w danych, lecz nie są wyświetlane ani wymagane
przy nowej ekstrakcji.

Całkowicie puste publikacje odrzucone przez dawny wymóg cytatów kwalifikują
się do jednej próby nowym protokołem w kolejnym AI-only. Jej zakończenie
zapisuje się także przy pustym wyniku, aby nie powtarzać kosztu. Nie obejmuje
to masowej regeneracji poprawnych publikacji. Nie uruchamiano płatnego
workflow ani nie zmieniano bezpośrednio zapisanej syntezy tego wątku.

## Weryfikacja

Fixture przechowuje rzeczywiste publiczne metadane i raport pustej analizy.
Testy odpowiedzi modelu używają tekstu syntetycznego. Sprawdzają jedną
ekstrakcję i jedno pisanie bez cytatów/napraw, zachowanie źródeł, blokowanie
obcych ID i brak ponowienia po poprawnym albo pustym wyniku. Frontendowy
test rzeczywistego pustego zapisu sprawdza komunikat i wszystkie linki źródeł.
