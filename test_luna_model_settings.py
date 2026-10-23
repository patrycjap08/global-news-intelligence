"""Luna requests preserve stage-specific reasoning and existing output budgets."""
import os
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch, MagicMock

import ai_pipeline as ai
import test_editorial_integrity as fixtures


class LunaModelSettingsTests(unittest.TestCase):
    def test_fact_audit_and_writer_requests_all_use_luna_with_low_low_medium(self):
        text = 'Policja zatrzymała 8 osób w Marsylii.'
        opinion = 'Analiza Le Monde wiąże zamieszki z przebudową systemu politycznego.'
        articles = [fixtures.article('left', text, 'LEFT'), fixtures.article('right', text, 'RIGHT')]
        seen = []
        def call(instructions, data, model, **settings):
            seen.append((settings['response_schema_name'], model, settings))
            if settings['response_schema_name'] == 'perspective_facts':
                claims = [fixtures.claim(text, aid) for aid in ('left', 'right')]
                claims += [fixtures.claim(opinion, aid, 'EDITORIAL', 'Le Monde') for aid in ('left', 'right')]
                return fixtures.extraction(data, claims)
            if settings['response_schema_name'] == 'perspective_novelty_audit':
                return {'decisions': {f['fact_id']: {'decision': 'NEW', 'new_detail_pl': '',
                    'covered_fact_ids': [], 'reason_pl': 'Nowe odrębne ustalenie.'}
                    for f in data['candidate_facts']}}
            return fixtures.writer(data)
        with patch.dict(os.environ, {'AI_SUMMARY_REASONING_EFFORT': 'medium',
                                     'OPENAI_EXTRACTION_REASONING_EFFORT': 'low'}), \
             patch.object(ai, 'call_openai', side_effect=call), patch.object(ai, 'log'):
            result = ai.generate_summary_response({'topic': {'working_title_pl': '[Francja] Zatrzymania w Marsylii'},
                                                   'all_articles': articles}, 'gpt-6-luna')
        self.assertEqual([item[0] for item in seen], ['perspective_facts', 'perspective_novelty_audit', 'perspective_summary'])
        self.assertEqual([item[1] for item in seen], ['gpt-6-luna'] * 3)
        self.assertEqual([item[2]['reasoning_effort'] for item in seen], ['low', 'low', 'medium'])
        self.assertTrue(all(item[2]['retry_limit'] == 1 for item in seen))
        self.assertIn(text, result['summary_pl'])
        self.assertEqual(len(result['perspective_sections']['EDITORIAL']), 1)

    def test_simple_luna_requests_disable_reasoning_and_explicit_effort_is_preserved(self):
        response = NS(status='completed', output_text='{"topics": []}', usage=None)
        client = MagicMock()
        client.responses.create.return_value = response
        with patch('openai.OpenAI', return_value=client), patch.object(ai, 'openai_api_key', return_value='test-only'):
            ai.call_openai('Tytuły.', {}, 'gpt-6-luna', retry_limit=1, response_schema_name='topic_titles')
            self.assertEqual(client.responses.create.call_args.kwargs['reasoning'], {'effort': 'none'})
            ai.call_openai('Fakty.', {}, 'gpt-6-luna', retry_limit=1, reasoning_effort='low')
            self.assertEqual(client.responses.create.call_args.kwargs['reasoning'], {'effort': 'low'})
            self.assertEqual(client.responses.create.call_args.kwargs['model'], 'gpt-6-luna')

    def test_summary_and_legacy_matching_effort_support_luna(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ai.summary_reasoning_effort('gpt-6-luna'), 'medium')
            self.assertEqual(ai.merge_reasoning_effort('gpt-6-luna'), 'low')


if __name__ == '__main__':
    unittest.main()
