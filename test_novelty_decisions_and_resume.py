"""Explicit decisions, bounded audits and resume without repeated article reads."""
import copy
import unittest
from unittest.mock import patch
import jsonschema
import ai_pipeline as ai
import perspective_summaries as p
from test_editorial_integrity import article, claim, extraction, writer
from test_topic_titles import FakeMergeClient


def decision(choice, covered=(), detail=''):
    return {'decision': choice, 'new_detail_pl': detail, 'covered_fact_ids': list(covered), 'reason_pl': 'Sprawdzono treść ustalenia.'}


class ExplicitNoveltyAndResumeTests(unittest.TestCase):
    def payload(self):
        rows = [article('a', 'Rada miasta przyjęła budżet na 2026 rok.'),
                article('b', 'Rada miasta przeznaczy 10 mln zł na remont szpitala.')]
        _, known = p.route_facts({'facts': [claim(rows[0]['body_original'], 'a')]}, rows, [], ai.normalize_generated_text)
        return {'topic': {'topic_id': 't'}, 'all_articles': rows, 'new_article_ids': ['b'],
                'previous_aggregation': {'processed_article_ids': ['a'], 'base_summary': {
                    'perspective_version': 1, 'summary_pl': 'Pierwotny tekst.', 'perspective_facts': known}}}

    def test_explicit_new_reuses_original_text(self):
        batch = [{'fact_id': 'C1', 'text_pl': 'Rada przyjęła budżet.'}]
        response = {'decisions': {'C1': decision('NEW', detail='Nie wolno użyć tego zamiast kandydata.')}}
        self.assertEqual(p.decode_novelty_decisions(response, batch)['decisions']['C1']['new_text_pl'], batch[0]['text_pl'])

    def test_bad_decision_omits_only_one_candidate_without_repair(self):
        payload = self.payload(); rows = payload['all_articles']
        known = payload['previous_aggregation']['base_summary']['perspective_facts']
        _, facts = p.route_facts({'facts': [claim(rows[1]['body_original'], 'b'),
                                            claim('Radni przeznaczą 2 mln zł na remont szkoły.', 'b')]}, rows, known, ai.normalize_generated_text)
        for choice, refs in [('DUPLICATE', []), ('DETAIL', []), ('NEW', ['alien']), ('DETAIL', ['C1'])]:
            calls = []
            def call(instructions, data, schema, name):
                calls.append(name)
                return {'decisions': {'C1': decision(choice, refs, 'Nowy szczegół.'), 'C2': decision('NEW')}}
            result, audit, omitted = p.audit_claims_once(facts, known, rows, call, ai.normalize_generated_text, 300000)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(omitted), 1)
            self.assertEqual(result[-1]['text_pl'], facts[-1]['text_pl'])
            self.assertNotIn(facts[1]['fact_id'], [f['fact_id'] for f in result])

    def test_49_article_topic_reads_only_26_new_articles_and_bounds_short_audits(self):
        payload = self.payload()
        rows = [article(f'a{i:02}', f'Rada miasta zrealizuje inwestycję numer {i}.') for i in range(49)]
        _, known = p.route_facts({'facts': [claim(rows[0]['body_original'], 'a00')]}, rows, [], ai.normalize_generated_text)
        payload['all_articles'] = rows
        payload['new_article_ids'] = [a['article_id'] for a in rows[23:]]
        payload['previous_aggregation']['processed_article_ids'] = [a['article_id'] for a in rows[:23]]
        payload['previous_aggregation']['base_summary']['perspective_facts'] = known
        sent, sizes, stages = [], [], []
        def request(instructions, data, model, **settings):
            name = settings['response_schema_name']; stages.append(name)
            if name == 'perspective_facts':
                sent.extend(data['all_articles'])
                result = extraction(data, [claim(a['body_original'], a['article_id']) for a in data['all_articles']])
            elif name == 'perspective_novelty_audit':
                self.assertNotIn('all_articles', data)
                self.assertTrue(all(f['fact_id'].startswith('C') for f in data['candidate_facts']))
                sizes.append(len(data['candidate_facts']))
                result = {'decisions': {f['fact_id']: decision('NEW') for f in data['candidate_facts']}}
            else: result = writer(data)
            jsonschema.validate(result, settings['response_schema'])
            return result
        with patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        self.assertEqual([a['body_original'] for a in sent], [a['body_original'] for a in rows[23:]])
        self.assertEqual(stages.count('perspective_facts'), 4)
        self.assertEqual(sizes, [24, 2])
        self.assertEqual(stages.count('perspective_summary'), 1)
        self.assertEqual(len(result['perspective_facts']), 27)

    def failed_extraction_checkpoint(self):
        payload = self.payload()
        def request(instructions, data, model, **settings):
            if settings['response_schema_name'] == 'perspective_facts':
                return extraction(data, [claim(payload['all_articles'][1]['body_original'], 'b')])
            raise RuntimeError('Transport failed after extraction')
        with patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log'), self.assertRaises(RuntimeError) as error:
            ai.generate_summary_response(payload, 'gpt-5-nano')
        return payload, ai.parse_failure_for_storage(error.exception)['extraction_checkpoint']

    def test_failed_audit_preserves_extraction_and_retry_sends_no_article_bodies(self):
        payload, checkpoint = self.failed_extraction_checkpoint()
        calls = []
        def request(instructions, data, model, **settings):
            calls.append(settings['response_schema_name'])
            self.assertNotIn('all_articles', data)
            if calls[-1] == 'perspective_novelty_audit':
                return {'decisions': {f['fact_id']: decision('NEW') for f in data['candidate_facts']}}
            return writer(data)
        with patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log'):
            result = ai.generate_summary_response({**payload, 'resume_extraction': checkpoint}, 'gpt-5-nano')
        self.assertEqual(calls, ['perspective_novelty_audit', 'perspective_summary'])
        self.assertEqual(result['update']['status'], 'NEW_INFORMATION')

    def test_corrupt_checkpoint_is_not_reused(self):
        payload, checkpoint = self.failed_extraction_checkpoint()
        for mutation in ('kind', 'article_ids'):
            bad = copy.deepcopy(checkpoint)
            bad['facts'][0][mutation] = 'EDITORIAL' if mutation == 'kind' else ['alien']
            self.assertIsNone(p.restore_extraction_checkpoint(bad, p.extraction_checkpoint_key(payload, ai.SUMMARY_MAX_PAYLOAD_CHARS),
                payload['all_articles'], payload['previous_aggregation']['base_summary']['perspective_facts'], ai.normalize_generated_text, allow_omissions=True))

    def test_history_checkpoint_requires_exact_topic_input_model_and_failed_status(self):
        payload, checkpoint = self.failed_extraction_checkpoint()
        summary_hash = ai.digest(payload)
        history_id = 'topicrun_' + ai.digest({'topic': 't', 'stage': 'SUMMARY', 'input': summary_hash})[:24]
        row = {'topic_run_id': history_id, 'input_hash': summary_hash, 'model': 'gpt-5-nano',
               'status': 'FAILED', 'raw_output': {'extraction_checkpoint': checkpoint}}
        for changes in ({}, {'model': 'other'}, {'input_hash': 'other'}, {'topic_run_id': 'other'}, {'status': 'COMPLETED'}):
            client = FakeMergeClient([], [], [])
            client.rows['topic_runs'] = [{**row, **changes}]
            self.assertEqual(ai.load_extraction_checkpoint(client, 't', summary_hash, 'gpt-5-nano'), checkpoint if not changes else None)

if __name__ == '__main__': unittest.main()
