import os
import unittest
from unittest.mock import patch
import ai_pipeline as ai
from test_perspective_summaries import extraction, fact

class SummaryRequestSettingsTests(unittest.TestCase):
    def test_medium_reasoning_only_for_supported_models(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ai.summary_reasoning_effort('gpt-5-nano'), 'medium')
            self.assertEqual(ai.summary_reasoning_effort('gpt-5.2'), 'medium')
            self.assertIsNone(ai.summary_reasoning_effort('gpt-4o-mini'))
            self.assertIsNone(ai.summary_reasoning_effort('gpt-5-pro'))
        with patch.dict(os.environ, {'AI_SUMMARY_REASONING_EFFORT': 'medium'}):
            self.assertEqual(ai.summary_reasoning_effort('gpt-5-nano'), 'medium')

    def test_base_and_both_update_requests_get_reasoning_and_timeout(self):
        seen=[]
        def response(instructions, payload, model, **kwargs):
            seen.append(kwargs)
            if kwargs['response_schema_name']=='update_candidate_facts':
                return {'facts':[{'text_pl':'Nowy fakt','why_new_pl':'Nowa decyzja','article_ids':['a1']}]}
            if kwargs['response_schema_name']=='update_novelty_audit':
                return {'verdicts':{'0':{'keep':True,'reason_pl':'Nowa decyzja'}}}
            if kwargs['response_schema_name']=='perspective_facts':
                return extraction([fact('Minister ogłosił decyzję.',['a1'],reason='')],payload['all_articles'])
            if kwargs['response_schema_name']=='perspective_summary':
                return {'paragraphs':[{'text_pl':'Minister ogłosił decyzję.', 'fact_ids':[payload['main_facts'][0]['fact_id']]}], 'general_context':{'text_pl':'Tło.', 'article_ids':[], 'needs_verification':True}, 'background_context':[]}
            return {'summary_pl':'Synteza'}
        with patch.dict(os.environ, {'AI_SUMMARY_REASONING_EFFORT':'low'}), patch.object(ai,'call_openai',side_effect=response):
            ai.generate_summary_response({'topic':{}, 'all_articles':[{'article_id':'a1','source_profile':'CENTER'}]}, 'gpt-5-nano')
            ai.generate_summary_response({'previous_aggregation':{'base_summary':{}},'new_articles':[{'article_id':'a1'}]},'gpt-5-nano')
        self.assertEqual(len(seen),4)
        for settings in seen:
            self.assertEqual(settings['reasoning_effort'],'low')
            self.assertEqual(settings['timeout_seconds'],ai.SUMMARY_REQUEST_TIMEOUT_SECONDS)

    def test_bad_fact_is_logged_and_skipped_without_a_paid_correction(self):
        bad=extraction([fact('Decyzja.',['a1'],known='invented')],[{'article_id':'a1'}])
        with patch.object(ai,'call_openai',return_value=bad) as request,patch.object(ai,'log') as logger:
            result=ai.generate_summary_response({'topic':{},'all_articles':[{'article_id':'a1','source_profile':'CENTER'}]},'gpt-5-nano')
        self.assertEqual(result['perspective_facts'],[])
        self.assertEqual(result['summary_pl'],'')
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['retry_limit'],1)
        self.assertNotIn('validation_feedback',request.call_args.args[1])
        self.assertTrue(any('odrzuconych błędnych ustaleń: 1' in str(call) for call in logger.call_args_list))

    def test_context_validation_still_rejects_exclusive_sources_and_keeps_diagnostics(self):
        import perspective_summaries as p
        main = [{'fact_id': 'main', 'text_pl': 'Minister ogłosił decyzję.', 'article_ids': ['l', 'r']}]
        response = {'paragraphs': [{'text_pl': main[0]['text_pl'], 'fact_ids': ['main']}],
                    'general_context': {'text_pl': 'Minister kieruje resortem.', 'article_ids': ['x']}}
        checked = p.safe_written(response, main)
        self.assertEqual(len(checked['paragraphs']), 1)
        self.assertEqual(checked['background_context'], [])

if __name__=='__main__':unittest.main()
