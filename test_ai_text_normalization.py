import unittest

from ai_pipeline import (
    SUMMARY_INSTRUCTIONS,
    normalize_generated_text,
    normalize_summary_response,
    update_needs_repair,
)


class AITextNormalizationTests(unittest.TestCase):
    def test_normalize_generated_text_converts_html_break_variants(self):
        self.assertEqual(
            normalize_generated_text("Pierwszy akapit</br></br>Drugi<br />akapit"),
            "Pierwszy akapit\n\nDrugi\nakapit",
        )
        self.assertEqual(
            normalize_generated_text(r"Pierwszy akapit\n\nDrugi akapit"),
            "Pierwszy akapit\n\nDrugi akapit",
        )

    def test_normalize_summary_response_cleans_visible_text_fields(self):
        response = normalize_summary_response({
            "topic": {
                "headline_pl": "[Świat] Tytuł</br>",
                "what_happened_one_sentence_pl": "Lead<br/>tekst",
            },
            "update": {"new_information_pl": "Nowa informacja</br></br>Druga"},
            "summary_pl": "Synteza</br></br>ciąg dalszy",
            "agreement": [{"text_pl": "Fakt<br>potwierdzony", "article_ids": ["a1"]}],
        })

        self.assertEqual(response["topic"]["headline_pl"], "[Świat] Tytuł")
        self.assertEqual(response["topic"]["what_happened_one_sentence_pl"], "Lead\ntekst")
        self.assertEqual(response["update"]["new_information_pl"], "Nowa informacja\n\nDruga")
        self.assertEqual(response["summary_pl"], "Synteza\n\nciąg dalszy")
        self.assertEqual(response["agreement"][0]["text_pl"], "Fakt\npotwierdzony")

    def test_update_repair_detects_grouping_meta_commentary(self):
        self.assertTrue(update_needs_repair({
            "update": {
                "new_information_pl": (
                    "Najnowszy artykuł PAP dotyczy innego tematu i nic nie wnosi."
                )
            }
        }))

    def test_update_repair_accepts_concrete_facts(self):
        self.assertFalse(update_needs_repair({
            "update": {
                "new_information_pl": (
                    "Dwa badania objęły osoby poszkodowane w wypadkach hulajnóg; "
                    "wyniki wskazały związek używania kasku z mniejszym ryzykiem "
                    "ciężkich obrażeń."
                )
            }
        }))

    def test_summary_prompt_requires_facts_and_forbids_grouping_commentary(self):
        self.assertIn("Zaczynaj od faktów", SUMMARY_INSTRUCTIONS)
        self.assertIn("Nie oceniaj w tekście, czy materiał został dobrze", SUMMARY_INSTRUCTIONS)
        self.assertIn("Nie wpisuj nazw źródeł do", SUMMARY_INSTRUCTIONS)

    def test_summary_prompt_explains_named_people_and_organizations_in_context(self):
        self.assertIn("Po napisaniu summary_pl oraz facts przejrzyj OBA pola", SUMMARY_INSTRUCTIONS)
        self.assertIn("Dla KAŻDEJ osoby dodaj osobny element background_context", SUMMARY_INSTRUCTIONS)
        self.assertIn("Dla KAŻDEJ organizacji dodaj osobny element", SUMMARY_INSTRUCTIONS)
        self.assertIn("Nie traktuj samej nazwy kraju lub", SUMMARY_INSTRUCTIONS)
        self.assertIn("Nie zgaduj tożsamości na podstawie nazwiska", SUMMARY_INSTRUCTIONS)

    def test_summary_prompt_requires_paragraphs_and_bold_markdown(self):
        self.assertIn("Podział na akapity jest obowiązkowy", SUMMARY_INSTRUCTIONS)
        self.assertIn("`**...**`", SUMMARY_INSTRUCTIONS)
        self.assertIn("co\nnajmniej 5 akapitów", SUMMARY_INSTRUCTIONS)

    def test_summary_prompt_keeps_all_facts_in_main_summary(self):
        self.assertIn("kompletnym, samodzielnym opisem wydarzenia", SUMMARY_INSTRUCTIONS)
        self.assertIn("Nie przenoś żadnego ważnego", SUMMARY_INSTRUCTIONS)
        self.assertIn("techniczna lista", SUMMARY_INSTRUCTIONS)

    def test_summary_prompt_requires_polish_facts(self):
        self.assertIn("`facts[].text_pl`", SUMMARY_INSTRUCTIONS)
        self.assertIn("nie kopiuj angielskiego", SUMMARY_INSTRUCTIONS)
        self.assertIn("naturalną polszczyzną", SUMMARY_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
