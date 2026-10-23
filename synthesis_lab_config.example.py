"""Skopiuj do synthesis_lab_config.py. Edytujesz tylko ten plik i .env.lab.

Python 3.10+. Najpierw --fetch, potem --run. Samo uruchomienie pokazuje plan.
"""

# Możesz wpisać jeden lub kilka tytułów, fragmentów tytułu albo topic_id.
# Gdy pasuje kilka wątków, program pokaże ID i przerwie przed zapytaniami AI.
# Szukanie: python synthesis_lab.py --search "SpaceX"
TOPICS = [
    "Udziały SpaceX dla dzieci obiecane przez Elona Muska",
    # "Godzina policyjna w odpowiedzi na zamieszki",
    # "topic_perspectives_...",
]

SNAPSHOT_PATH = "lab-data/input.json"  # pełne artykuły pobrane raz z bazy
RESULTS_DIR = "lab-data/results"
MAX_CALLS_PER_TOPIC = 16              # ten sam budżet co w obecnym flow
MAX_OUTPUT_TOKENS = 16000            # obejmuje także tokeny rozumowania
MAX_PAYLOAD_CHARS = 300000           # cel paczki; artykuły nie są skracane
TIMEOUT_SECONDS = 300

# Trzy rodzaje zapytań (liczba wywołań zależy od rozmiaru wątku):
# extraction — fakty, wypowiedzi i oceny osobno dla artykułów; paczki do 8.
# audit      — porównanie/deduplikacja ustaleń; paczki do 24, bez pełnych treści.
# writing    — końcowa synteza z kontekstem; jedno zapytanie.
# Podział na lewicowe/centrowe/prawicowe i oceny wykonuje ten sam kod co w produkcji.
# Nie ma osobnego płatnego zapytania dla każdego kafelka lub profilu.
# Nazwy i kategorie nie są generowane. Nie ma scalania ani zapisów do bazy.

# Przykładowe MODELE OpenAI obsługujące tekst i Structured Outputs:
# gpt-5-nano (poprzedni), gpt-5-mini, gpt-4o-mini, gpt-4.1-mini,
# gpt-5.4-nano, gpt-5.4-mini, gpt-5.4, gpt-5.5,
# gpt-6-luna (obecny), gpt-6.1-sol, gpt-6-astra. Działa też dostępny snapshot modelu.
# Dostępność dla klucza: python synthesis_lab.py --list-models
# Starsze 4.x, 5-nano/mini i 5.4-nano mają w dokumentacji oznaczenie deprecated.
# Pełne ceny i mnożniki względem nano: SYNTHESIS_LAB.md (stan 23.10.2026).
# Inni dostawcy (Claude/Gemini) wymagają innego adaptera — tu używamy OpenAI API.
#
# reasoning_effort:
# gpt-5-nano/mini: minimal, low, medium, high.
# gpt-5.4/nano/mini i gpt-5.5: none, low, medium, high, xhigh.
# gpt-6-luna: none, low, medium, high, xhigh, max.
# gpt-6.1-sol/astra: low, medium, high, xhigh, max.
# gpt-4o-mini/4.1-mini: None (program automatycznie pomija parametr).
# Możesz nadpisać też max_output_tokens i timeout_seconds osobno dla etapu.

VARIANTS = [
    {
        "name": "luna-obecny",
        "mode": "full",  # artykuły -> fakty -> audyt -> synteza, od zera
        "stages": {
            "extraction": {"model": "gpt-6-luna", "reasoning_effort": "low"},
            "audit": {"model": "gpt-6-luna", "reasoning_effort": "low"},
            "writing": {"model": "gpt-6-luna", "reasoning_effort": "medium"},
        },
    },
    # Na start jeden wariant, aby nie płacić za identyczne próby tą samą Luną.
    # Odkomentuj dodatkowy wariant i wybierz inny model dopiero do porównania:
    # {
    #     "name": "inny-model-samo-pisanie",
    #     "mode": "writing",  # te same fakty, bez kolejnej ekstrakcji
    #     "facts_from": "luna-obecny",  # wcześniejszy wariant z listy
    #     "stages": {
    #         "writing": {"model": "WYBRANY_MODEL", "reasoning_effort": "medium"},
    #     },
    # },
]

# Opcjonalnie stawki dla innych modeli / aktualizacja cen:
# nazwa: (wejście, wejście z cache, wyjście) w USD / milion tokenów.
# PRICE_OVERRIDES = {"nazwa-modelu": (0.10, 0.01, 0.50)}
