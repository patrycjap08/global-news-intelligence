import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonschema

import ai_pipeline as ai
import perspective_summaries as p
from test_perspective_summaries import article, extraction, fact
from test_topic_titles import FakeMergeClient


def decision(choice, covered=(), detail='', reason='Sprawdzona decyzja testowa.'):
    return {'decision': choice, 'new_detail_pl': detail, 'covered_fact_ids': list(covered), 'reason_pl': reason}


class ExplicitNoveltyAndResumeTests(unittest.TestCase):
    def payload(self):
        rows = [{**article(aid, 'CENTER'), 'body_original': f'Pełny tekst {aid}.'} for aid in ('a', 'b')]
        known = p.route_facts({'facts': [fact('Znany fakt.', ['a'], kind='FACT')]},
                              rows, [], ai.normalize_generated_text)[1]
        return {'topic': {'topic_id': 't'}, 'all_articles': rows, 'new_article_ids': ['b'],
                'previous_aggregation': {'base_summary': {'perspective_version': 1,
                    'summary_pl': 'Pierwotny tekst.', 'perspective_facts': known}}}

    def test_real_ambiguous_empty_new_fact_becomes_unambiguous_new_decision(self):
        fixture = json.loads((Path(__file__).parent / 'test_data/perspective_ambiguous_novelty_20261020.json').read_text())
        cid = 'fact_a684a1747e2279ec98ce091b'
        self.assertEqual(fixture['response']['decisions'][cid]['new_text_pl'], '')
        self.assertEqual(fixture['response']['decisions'][cid]['covered_fact_ids'], [])
        # The original candidate was not logged. This text is synthetic.
        batch = [{'fact_id': cid, 'text_pl': 'Nowe, wcześniej wyciągnięte ustalenie.'}]
        response = {'decisions': {cid: decision('NEW')}}
        jsonschema.validate(response, p.novelty_decision_schema([{'fact_id': 'old'}], batch))
        decoded = p.decode_novelty_decisions(response, batch)
        self.assertEqual(decoded['decisions'][cid]['new_text_pl'], batch[0]['text_pl'])
        self.assertNotIn('new_text_pl', response['decisions'][cid])

    def test_new_keeps_exact_original_while_detail_preserves_only_the_explicit_detail(self):
        payload = self.payload()
        calls = []
        def request(instructions, data, model, **settings):
            calls.append(settings['response_schema_name'])
            if calls[-1] == 'perspective_facts':
                return extraction([fact('Nowa decyzja według ministra.', ['b'], kind='STATEMENT'),
                                   fact('Znany fakt z nowym szczegółem.', ['b'], kind='FACT')], data['all_articles'])
            first, second = data['candidate_facts']
            reply = {'decisions': {
                first['fact_id']: decision('NEW', detail='Tego nie należy użyć zamiast oryginalnej wypowiedzi.'),
                second['fact_id']: decision('DETAIL', [data['previous_facts'][0]['fact_id']], 'Nowy szczegół.'),
            }}
            jsonschema.validate(reply, settings['response_schema'])
            return reply
        with patch.object(ai, 'call_openai', side_effect=request):
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        self.assertEqual(calls, ['perspective_facts', 'perspective_novelty_audit'])
        self.assertEqual([f['text_pl'] for f in result['perspective_facts']],
                         ['Znany fakt.', 'Nowa decyzja według ministra.', 'Nowy szczegół.'])
        self.assertEqual(result['perspective_facts'][1]['kind'], 'STATEMENT')
        self.assertEqual(result['summary_pl'], 'Pierwotny tekst.')

    def test_bad_decisions_cannot_infer_references_or_publish_unchecked_information(self):
        for choice, covered, detail in [('DUPLICATE', [], ''), ('DETAIL', [], 'Szczegół.'),
                                        ('NEW', ['alien'], ''), ('DETAIL', ['self'], 'Szczegół.')]:
            with self.subTest(choice=choice, covered=covered):
                payload = self.payload()
                calls = []
                def request(instructions, data, model, **settings):
                    calls.append(settings['response_schema_name'])
                    if calls[-1] == 'perspective_facts':
                        return extraction([fact('Nowe.', ['b'], kind='FACT')], data['all_articles'])
                    candidate = data['candidate_facts'][0]
                    refs = [candidate['fact_id'] if i == 'self' else i for i in covered]
                    return {'decisions': {candidate['fact_id']: decision(choice, refs, detail)}}
                with patch.object(ai, 'call_openai', side_effect=request), self.assertRaises(ai.AIResponseParseError):
                    ai.generate_summary_response(payload, 'gpt-5-nano')
                self.assertEqual(calls, ['perspective_facts', 'perspective_novelty_audit', 'perspective_novelty_audit'])

    def test_49_articles_and_59_candidates_finish_all_three_explicit_audit_batches(self):
        payload = self.payload()
        rows = [{**article(f'a{i}', 'CENTER'), 'body_original': f'Cały artykuł {i}. ' * 100}
                for i in range(49)]
        known = p.route_facts({'facts': [fact(f'Zapisane ustalenie {i}.', ['a0'], kind='FACT')
                                       for i in range(17)]}, rows, [], ai.normalize_generated_text)[1]
        payload['all_articles'] = rows
        payload['new_article_ids'] = [a['article_id'] for a in rows[23:]]
        payload['previous_aggregation']['base_summary']['perspective_facts'] = known
        extracted, audits, sent = [], [], []
        def request(instructions, data, model, **settings):
            name = settings['response_schema_name']
            if name == 'perspective_facts':
                current = data['all_articles']
                sent.extend(a['body_original'] for a in current)
                answer = [fact('', [a['article_id'] for a in current], known[0]['fact_id'], reason='', kind='FACT')]
                if not extracted:
                    answer.extend(fact(f'Nowy kandydat {i}.', ['a0'], kind='FACT') for i in range(59))
                extracted.append(name)
                return extraction(answer, current)
            self.assertEqual(name, 'perspective_novelty_audit')
            index = len(audits)
            batch = data['candidate_facts']
            audits.append((len(batch), len(data['previous_facts'])))
            accepted = (14, 12, 5)[index]
            reply = {'decisions': {f['fact_id']: decision('NEW') if i < accepted else
                        decision('DUPLICATE', [known[0]['fact_id']]) for i, f in enumerate(batch)}}
            jsonschema.validate(reply, settings['response_schema'])
            return reply
        with patch.object(ai, 'call_openai', side_effect=request):
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        self.assertEqual(len(extracted), 7)
        self.assertEqual(sent, [a['body_original'] for a in rows])
        self.assertEqual(audits, [(24, 17), (24, 31), (11, 43)])
        self.assertEqual(len(result['perspective_facts']), 48)
        self.assertEqual(result['summary_pl'], 'Pierwotny tekst.')

    def failed_extraction_checkpoint(self):
        payload = self.payload()
        def request(instructions, data, model, **settings):
            if settings['response_schema_name'] == 'perspective_facts':
                return extraction([fact('Nowe ustalenie.', ['b'], kind='FACT')], data['all_articles'])
            raise RuntimeError('Testowy błąd po ekstrakcji.')
        with patch.object(ai, 'call_openai', side_effect=request), self.assertRaises(RuntimeError) as error:
            ai.generate_summary_response(payload, 'gpt-5-nano')
        stored = ai.parse_failure_for_storage(error.exception)
        return payload, stored['extraction_checkpoint']

    def test_failed_audit_preserves_extraction_and_retry_sends_no_article_bodies(self):
        payload, checkpoint = self.failed_extraction_checkpoint()
        calls = []
        def request(instructions, data, model, **settings):
            calls.append(settings['response_schema_name'])
            self.assertNotIn('all_articles', data)
            return {'decisions': {f['fact_id']: decision('NEW') for f in data['candidate_facts']}}
        with patch.object(ai, 'call_openai', side_effect=request):
            result = ai.generate_summary_response({**payload, 'resume_extraction': checkpoint}, 'gpt-5-nano')
        self.assertEqual(calls, ['perspective_novelty_audit'])
        self.assertEqual([f['text_pl'] for f in result['perspective_facts']], ['Znany fakt.', 'Nowe ustalenie.'])
        self.assertEqual(result['summary_pl'], 'Pierwotny tekst.')
        self.assertNotIn('extraction_checkpoint', result)
        self.assertEqual(result['update']['status'], 'NEW_INFORMATION')

    def test_changed_input_or_invalid_checkpoint_requires_complete_extraction(self):
        original, checkpoint = self.failed_extraction_checkpoint()
        cases = []
        changed = copy.deepcopy(original)
        changed['all_articles'][0]['body_original'] += ' Nowa treść.'
        cases.append((changed, checkpoint))
        corrupt = copy.deepcopy(checkpoint)
        corrupt['facts'][-1]['article_ids'] = ['alien']
        cases.append((original, corrupt))
        corrupt = copy.deepcopy(checkpoint)
        corrupt['facts'][0]['kind'] = 'EDITORIAL'
        cases.append((original, corrupt))
        corrupt = copy.deepcopy(checkpoint)
        corrupt['facts'].pop()
        cases.append((original, corrupt))
        for payload, resume in cases:
            calls = []
            def request(instructions, data, model, **settings):
                calls.append(settings['response_schema_name'])
                if calls[-1] == 'perspective_facts':
                    return extraction([fact('', ['a', 'b'], data['previous_facts'][0]['fact_id'], reason='', kind='FACT')], data['all_articles'])
                self.fail('Only confirmations after fresh extraction.')
            with patch.object(ai, 'call_openai', side_effect=request):
                result = ai.generate_summary_response({**payload, 'resume_extraction': resume}, 'gpt-5-nano')
            self.assertEqual(calls, ['perspective_facts'])
            self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')

    def test_incomplete_extraction_never_creates_a_checkpoint(self):
        payload = self.payload()
        bad = extraction([fact('Nieprawidłowe cytowanie.', ['alien'], kind='FACT')], payload['all_articles'])
        with patch.object(ai, 'call_openai', return_value=bad), self.assertRaises(ai.AIResponseParseError) as caught:
            ai.generate_summary_response(payload, 'gpt-5-nano')
        self.assertNotIn('extraction_checkpoint', ai.parse_failure_for_storage(caught.exception))

    def test_history_checkpoint_requires_exact_topic_input_model_and_failed_status(self):
        payload, checkpoint = self.failed_extraction_checkpoint()
        summary_hash = ai.digest(payload)
        history_id = 'topicrun_' + ai.digest({'topic': 't', 'stage': 'SUMMARY', 'input': summary_hash})[:24]
        row = {'topic_run_id': history_id, 'input_hash': summary_hash, 'model': 'gpt-5-nano',
               'status': 'FAILED', 'raw_output': {'extraction_checkpoint': checkpoint}}
        for changes in ({}, {'model': 'other'}, {'input_hash': 'other'}, {'topic_run_id': 'other'}, {'status': 'COMPLETED'}):
            client = FakeMergeClient([], [], [])
            client.rows['topic_runs'] = [{**row, **changes}]
            found = ai.load_extraction_checkpoint(client, 't', summary_hash, 'gpt-5-nano')
            self.assertEqual(found, checkpoint if not changes else None)


if __name__ == '__main__':
    unittest.main()
