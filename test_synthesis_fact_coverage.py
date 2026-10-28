"""The published Tusk/India topic had 57 facts but only two short paragraphs."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonschema
import ai_pipeline as ai
import perspective_summaries as p
from structured_outputs import check_response_schema
from test_topic_titles import FakeMergeClient
from test_writing_fixtures import article_response, paired_article_response


DATA = json.loads(Path(__file__).with_name('test_data').joinpath(
    'tusk_india_incomplete_synthesis_20261023.json').read_text())


def complete_response(facts):
    # Deterministic replay of a long, supported response, not a quality claim
    # about model prose. Several facts may share the same narrative paragraph.
    return article_response([
        {'text_pl': ' '.join(f['text_pl'] for f in facts[offset:offset + 6]),
         'fact_ids': [f['fact_id'] for f in facts[offset:offset + 6]]}
        for offset in range(0, len(facts), 6)])


def refresh_payload():
    facts = copy.deepcopy(DATA['facts'])
    current = {'publication_version': 2, 'perspective_version': 1,
               'inline_context_version': 2, 'situation_context_version': 1,
               'summary_pl': DATA['published_summary_pl'],
               'topic': {'headline_pl': DATA['headline_pl']}}
    previous = {'base_summary': current, 'current_summary': current,
                'perspective_state': {'perspective_facts': facts, 'facts': facts},
                'processed_article_ids': [a['article_id'] for a in DATA['articles']],
                'needs_narrative_refresh': True}
    return {'topic': {'topic_id': DATA['topic_id'], 'working_title_pl': DATA['headline_pl']},
            'all_articles': copy.deepcopy(DATA['articles']), 'new_article_ids': [],
            'previous_aggregation': previous}


class SynthesisFactCoverageTests(unittest.TestCase):
    def test_real_57_fact_article_is_not_limited_to_four_paragraphs_or_6000_characters(self):
        self.assertEqual(len(DATA['facts']), 57)
        raw = complete_response(DATA['facts'])
        self.assertGreater(len(raw['summary_pl']), 6000)
        self.assertGreater(len(raw['paragraph_sources']), 4)
        schema = p.article_writing_schema(DATA['facts'])
        check_response_schema(schema)
        jsonschema.validate(paired_article_response(raw), schema)
        written = p.safe_article_written(paired_article_response(raw), DATA['facts'], [])
        self.assertEqual('\n\n'.join(row['text_pl'] for row in written['paragraphs']), raw['summary_pl'])
        report = written['writing_validation']
        self.assertEqual(report['accepted_paragraphs'], len(raw['paragraph_sources']))
        self.assertEqual(report['fact_coverage'], {
            'expected_count': 57, 'referenced_count': 57, 'missing_fact_ids': [],
            'status': 'COMPLETE_REFERENCES'})

    def test_every_fact_reaches_the_single_writer_and_the_complete_text_survives_normalization(self):
        payload = refresh_payload()
        before = copy.deepcopy(payload)
        requests = []
        def request(instructions, data, model, **settings):
            requests.append(settings['response_schema_name'])
            self.assertEqual(settings['response_schema_name'], 'perspective_summary')
            self.assertEqual({f['fact_id'] for f in data['main_facts']},
                             {f['fact_id'] for f in DATA['facts']})
            self.assertEqual(model, 'gpt-6-luna')
            self.assertEqual(settings['retry_limit'], 1)
            return complete_response(data['main_facts'])
        with patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-6-luna')
        self.assertEqual(requests, ['perspective_summary'])
        self.assertGreater(len(result['summary_pl']), 6000)
        self.assertIn(DATA['facts'][-1]['text_pl'], result['summary_pl'])
        self.assertEqual(result['quality_report']['writing_validation']['fact_coverage']['referenced_count'], 57)
        self.assertEqual(result['quality_report']['read_articles'], 0)
        self.assertFalse(result['quality_report']['narrative_fallback'])
        self.assertEqual(payload, before)
        client = FakeMergeClient([], [], [])
        ai.persist_summary(client, topic_id=DATA['topic_id'], run_id='test', model='gpt-6-luna',
                           summary=result, summary_hash='coverage-test',
                           previous_row={'version': 1, 'summary': before['previous_aggregation']},
                           new_article_ids=[])
        saved = next(rows[0]['summary'] for table, rows, _ in client.upserts if table == 'topic_summaries')
        self.assertEqual(saved['current_summary']['summary_pl'], result['summary_pl'])
        self.assertEqual(saved['current_summary']['quality_report']['writing_validation']['fact_coverage']['referenced_count'], 57)
        with patch.object(ai, 'call_openai') as request, patch.object(ai, 'log'):
            reused = ai.generate_summary_response({**payload, 'previous_aggregation': saved}, 'gpt-6-luna')
        request.assert_not_called()
        self.assertEqual(reused['quality_report']['writing_validation']['fact_coverage']['referenced_count'], 57)

    def test_short_old_response_reports_missing_fact_references_without_another_call(self):
        facts = DATA['facts']
        raw = article_response([
            {'text_pl': facts[0]['text_pl'], 'fact_ids': [facts[0]['fact_id']]},
            {'text_pl': facts[19]['text_pl'], 'fact_ids': [facts[19]['fact_id']]}])
        with patch.object(ai, 'call_openai', return_value=raw) as request, patch.object(ai, 'log') as log:
            result = ai.generate_summary_response(refresh_payload(), 'gpt-6-luna')
        request.assert_called_once()
        report = result['quality_report']['writing_validation']['fact_coverage']
        self.assertEqual(report['status'], 'MISSING_REFERENCES')
        self.assertEqual(report['expected_count'], 57)
        self.assertEqual(report['referenced_count'], 2)
        self.assertEqual(len(report['missing_fact_ids']), 55)
        self.assertTrue(any('Pokrycie syntezy' in str(call) and 'WARN' in str(call) for call in log.call_args_list))

    def test_invalid_late_paragraph_does_not_hide_other_late_facts(self):
        facts = DATA['facts'][:7]
        raw = complete_response(facts[:6])
        raw['summary_pl'] += '\n\nNiepowiązana informacja z roku 2099.'
        raw['paragraph_sources'].append({'fact_ids': [facts[6]['fact_id']]})
        raw['summary_pl'] += '\n\n' + facts[6]['text_pl']
        raw['paragraph_sources'].append({'fact_ids': [facts[6]['fact_id']]})
        written = p.safe_article_written(raw, facts, [])
        self.assertNotIn('2099', '\n'.join(row['text_pl'] for row in written['paragraphs']))
        self.assertEqual(written['writing_validation']['fact_coverage']['referenced_count'], 7)

    def test_one_sentence_may_cover_several_duplicate_fact_ids(self):
        facts = [{'fact_id': 'f1', 'text_pl': 'Rada miasta przyjęła budżet.', 'article_ids': ['a']},
                 {'fact_id': 'f2', 'text_pl': 'Rada miasta przyjęła budżet.', 'article_ids': ['b']}]
        raw = article_response([{'text_pl': facts[0]['text_pl'], 'fact_ids': ['f1', 'f2']}])
        written = p.safe_article_written(raw, facts, [])
        self.assertEqual(len(written['paragraphs']), 1)
        self.assertEqual(written['writing_validation']['fact_coverage']['referenced_count'], 2)
        self.assertEqual(raw['summary_pl'].count('przyjęła budżet'), 1)

    def test_invalid_writer_fallback_keeps_all_accepted_facts_without_paid_repair(self):
        payload = refresh_payload()
        with patch.object(ai, 'call_openai', return_value={}) as request, patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-6-luna')
        request.assert_called_once()
        self.assertTrue(result['quality_report']['narrative_fallback'])
        self.assertLess(len(result['summary_pl'].split('\n\n')), len(DATA['facts']))
        for fact in DATA['facts']:
            self.assertIn(fact['text_pl'], result['summary_pl'])


if __name__ == '__main__':
    unittest.main()
