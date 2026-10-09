import os
import unittest
from unittest.mock import patch
import ai_pipeline as ai

class SummaryRequestSettingsTests(unittest.TestCase):
    def test_low_reasoning_only_for_supported_models(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ai.summary_reasoning_effort('gpt-5-nano'), 'low')
            self.assertEqual(ai.summary_reasoning_effort('gpt-5.2'), 'low')
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
            return {'summary_pl':'Synteza'}
        with patch.dict(os.environ, {'AI_SUMMARY_REASONING_EFFORT':'low'}), patch.object(ai,'call_openai',side_effect=response):
            ai.generate_summary_response({}, 'gpt-5-nano')
            ai.generate_summary_response({'previous_aggregation':{'base_summary':{}},'new_articles':[{'article_id':'a1'}]},'gpt-5-nano')
        self.assertEqual(len(seen),3)
        for settings in seen:
            self.assertEqual(settings['reasoning_effort'],'low')
            self.assertEqual(settings['timeout_seconds'],ai.SUMMARY_REQUEST_TIMEOUT_SECONDS)

if __name__=='__main__':unittest.main()
