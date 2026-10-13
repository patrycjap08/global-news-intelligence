import unittest
import ai_pipeline as ai

class GeneralContextTests(unittest.TestCase):
    def test_schema_requires_nonempty_overview_separate_from_entities(self):
        schema=ai.SUMMARY_RESPONSE_SCHEMA
        self.assertIn('general_context',schema['required'])
        self.assertIn('background_context',schema['required'])
        self.assertEqual(schema['properties']['general_context']['properties']['text_pl']['minLength'],1)

    def test_overview_is_displayed_first_and_people_and_organizations_are_preserved(self):
        row=ai.normalize_summary_response({
            'general_context':{'text_pl':'Projekt ma połączyć dwa regiony i ułatwić transport.',
                               'article_ids':['article'],'needs_verification':False},
            'background_context':[{'entity_type':'PERSON','text_pl':'Osoba — Jan Kowalski: inżynier.',
                                   'article_ids':[],'needs_verification':True},
                                  {'entity_type':'ORGANIZATION','text_pl':'Organizacja — Firma: wykonawca.',
                                   'article_ids':['article'],'needs_verification':False}]})
        context=row['background_context']
        self.assertEqual(len(context),3)
        self.assertEqual(context[0]['text_pl'],'**Ogólny kontekst**\n\nProjekt ma połączyć dwa regiony i ułatwić transport.')
        self.assertEqual(context[0]['article_ids'],['article'])
        self.assertFalse(context[0]['needs_verification'])
        self.assertEqual(context[1]['entity_type'],'PERSON')
        self.assertEqual(context[2]['entity_type'],'ORGANIZATION')

    def test_general_knowledge_keeps_empty_source_ids_and_legacy_context_still_works(self):
        row=ai.normalize_summary_response({'general_context':{'text_pl':'Tło historyczne.',
            'article_ids':[],'needs_verification':True}})
        self.assertEqual(row['background_context'][0]['article_ids'],[])
        self.assertTrue(row['background_context'][0]['needs_verification'])
        legacy=ai.normalize_summary_response({'background_context':[{'text_pl':'Poprzedni kontekst.','article_ids':[]}]})
        self.assertEqual(len(legacy['background_context']),1)
        self.assertEqual(legacy['background_context'][0]['text_pl'],'Poprzedni kontekst.')

if __name__=='__main__':unittest.main()
