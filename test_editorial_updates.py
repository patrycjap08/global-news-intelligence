import unittest
from unittest.mock import patch
import ai_pipeline as ai

class EditorialUpdateTests(unittest.TestCase):
    def facts(self):
        return [{'text_pl':text,'article_ids':['new'],'why_new_pl':'Nowe ustalenie'} for text in
                ['Christa Pike ma 50 lat.','Christa Pike zaczęła chodzić po nieudanej egzekucji.','Christa Pike nie pamięta egzekucji.']]
    def verdicts(self):
        return {str(i):{'keep':True,'reason_pl':'Nowa informacja.'} for i in range(3)}
    def payload(self):
        return {'previous_aggregation':{'base_summary':{'summary_pl':'Poprzedni opis.'}},
                'new_articles':[{'article_id':'new','body_original':'Nowe informacje.'}]}

    def test_three_facts_become_one_sentence_in_existing_two_requests(self):
        sentence='50-letnia Christa Pike zaczęła chodzić po nieudanej egzekucji, ale nie pamięta jej przebiegu.'
        response={'verdicts':self.verdicts(),'update_sentences':[{'text_pl':sentence,'fact_indexes':[0,1,2]}]}
        with patch.object(ai,'call_openai',side_effect=[{'facts':self.facts()},response]) as api:
            result=ai.generate_topic_update(self.payload(),'gpt-5-nano')
        self.assertEqual(api.call_count,2)
        self.assertEqual(result['update']['new_information_pl'],sentence)
        self.assertEqual(result['update']['novelty_audit']['update_sentences'],response['update_sentences'])

    def test_edited_text_cannot_reference_rejected_or_missing_facts(self):
        verdicts=[{'fact_index':0,'keep':True},{'fact_index':1,'keep':False}]
        for sentences in [[{'text_pl':'Nie wolno.','fact_indexes':[1]}],[],
                          [{'text_pl':'Powtórzenie.','fact_indexes':[0,0]}],
                          [{'text_pl':'Obcy fakt.','fact_indexes':[99]}]]:
            with self.assertRaises(ValueError):ai.validate_update_sentences({'update_sentences':sentences},verdicts)
        self.assertEqual(ai.validate_update_sentences({'update_sentences':[]},[{'fact_index':0,'keep':False}]),[])

    def test_bad_edited_sentence_retries_audit_without_repeating_fact_selection(self):
        verdicts=self.verdicts();verdicts['2']['keep']=False
        bad={'verdicts':verdicts,'update_sentences':[{'text_pl':'Błędnie zachowany fakt.','fact_indexes':[0,1,2]}]}
        good={'verdicts':verdicts,'update_sentences':[{'text_pl':'50-letnia Christa Pike zaczęła chodzić po nieudanej egzekucji.','fact_indexes':[0,1]}]}
        with patch.object(ai,'call_openai',side_effect=[{'facts':self.facts()},bad,good]) as api:
            result=ai.generate_topic_update(self.payload(),'gpt-5-nano')
        self.assertEqual(api.call_count,3)
        self.assertEqual(result['update']['new_information_pl'],good['update_sentences'][0]['text_pl'])
        self.assertEqual(api.call_args_list[2].kwargs['response_schema_name'],'update_novelty_audit')

    def test_stray_brace_and_lead_semicolon_are_removed(self):
        result=ai.normalize_summary_response({'topic':{'what_happened_one_sentence_pl':'Doszło do ataku; policja zatrzymała sprawcę. }'},'summary_pl':'Opis. }'})
        self.assertNotIn(';',result['topic']['what_happened_one_sentence_pl'])
        self.assertEqual(result['summary_pl'],'Opis.')

if __name__=='__main__':unittest.main()
