"""Real Italy omission diagnostics; facts without copied source quotations."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonschema
import ai_pipeline as ai
import editorial_integrity as integrity
import perspective_summaries as p
from structured_outputs import check_response_schema
from test_editorial_integrity import writer
import test_summary_queue as queue_tests
from test_topic_titles import FakeMergeClient

DATA = json.loads(Path(__file__).with_name('test_data').joinpath('italy_empty_extraction_20261021.json').read_text())


def articles():
    # These bodies are synthetic Italian text for contract/cost tests.
    # The public export does not contain the original rejected model response.
    return [{**a, 'title_original': a['title'],
             'body_original': 'Gli autotrasportatori protestano in Italia contro il caro carburanti. ' * 20}
            for a in DATA['articles']]


class FactExtractionWithoutQuotesTests(unittest.TestCase):
    def test_real_failure_is_all_rejected_quotes_despite_six_center_articles(self):
        stored = DATA['summary']['summary']
        self.assertEqual(sum(a['source_profile'] == 'CENTER' for a in DATA['articles']), 6)
        self.assertEqual(len(DATA['articles']), 7)
        self.assertEqual(stored['perspective_state']['perspective_facts'], [])
        self.assertEqual(stored['current_summary']['quality_report']['omissions'][0]['discarded_fact_count'], 7)
        self.assertTrue(integrity.needs_fact_rebuild(stored))
        for key, value in [('summary_pl', 'Poprawna synteza.'), ('fact_extraction_version', 2)]:
            updated = copy.deepcopy(stored); updated['current_summary'][key] = value
            self.assertFalse(integrity.needs_fact_rebuild(updated))
        updated = copy.deepcopy(stored); updated['perspective_state']['perspective_facts'] = [{'text_pl': 'Znane ustalenie.'}]
        self.assertFalse(integrity.needs_fact_rebuild(updated))

    def test_schema_requires_source_ownership_and_classification_without_quotes(self):
        schema = p.article_coverage_schema([], ['it'], allow_omissions=True)
        check_response_schema(schema)
        text = json.dumps(schema)
        self.assertNotIn('evidence_quote', text)
        self.assertNotIn('block_id', text)
        self.assertIn('attribution', text)
        answer = {'headline_pl': '[Włochy] Protesty przewoźników', 'categories': ['SWIAT'], 'article_results': {
            'it': {'facts': [{'known_fact_id': '', 'text_pl': 'Przewoźnicy protestują we Włoszech.',
                'kind': 'FACT', 'why_new_pl': '', 'attribution': ''}], 'no_relevant_facts_reason_pl': ''}}}
        jsonschema.validate(answer, schema)
        answer['article_results']['it']['facts'][0]['article_ids'] = ['foreign']
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(answer, schema)

    def test_quote_removal_keeps_subject_kind_attribution_and_foreign_id_checks(self):
        rows = [{'article_id': 'it', 'source_profile': 'CENTER', 'body_original': 'Testo italiano completo.'}]
        valid = {'known_fact_id': '', 'text_pl': 'Przewoźnicy protestują we Włoszech.', 'kind': 'FACT', 'why_new_pl': '', 'attribution': ''}
        invalid = [
            {**valid, 'kind': 'INVENTED'},
            {**valid, 'text_pl': 'Dodał, że nastąpi zmiana.'},
            {**valid, 'kind': 'STATEMENT', 'attribution': ''},
            {**valid, 'kind': 'EDITORIAL', 'attribution': ''},
        ]
        raw = {'article_results': {'it': {'facts': [valid, *invalid], 'no_relevant_facts_reason_pl': ''},
                                  'alien': {'facts': [valid], 'no_relevant_facts_reason_pl': ''}}}
        result, report = p.usable_extraction(raw, rows, rows, [], ai.normalize_generated_text, {})
        self.assertEqual(result['facts'], [{**valid, 'article_ids': ['it']}])
        self.assertEqual(report['discarded_fact_count'], 4)
        self.assertEqual(report['ignored_article_ids'], ['alien'])

    def test_existing_italy_record_gets_one_extraction_one_writer_and_no_repair_or_quote_request(self):
        previous = copy.deepcopy(DATA['summary']['summary'])
        payload = {'topic': {'topic_id': DATA['topic']['topic_id'], 'working_title_pl': DATA['topic']['headline_pl']},
                   'all_articles': articles(), 'new_article_ids': [], 'previous_aggregation': previous}
        calls, saved_cache = [], []
        def request(instructions, data, model, **settings):
            name = settings['response_schema_name']; calls.append(name)
            self.assertEqual(settings['retry_limit'], 1)
            if name == 'perspective_facts':
                self.assertIn('Nie zwracaj dosłownych cytatów', instructions)
                self.assertNotIn('evidence_quote', json.dumps(settings['response_schema']))
                self.assertEqual(len(data['all_articles']), 7)
                self.assertTrue(all(a['body_original'] == articles()[0]['body_original'] for a in data['all_articles']))
                self.assertTrue(all('evidence_index' not in a for a in data['all_articles']))
                response = {'headline_pl': DATA['topic']['headline_pl'], 'categories': ['SWIAT'], 'article_results': {
                    a['article_id']: {'facts': [{'known_fact_id': '', 'text_pl': 'Przewoźnicy protestują we Włoszech przeciwko wysokim cenom paliwa.',
                        'why_new_pl': '', 'kind': 'FACT', 'attribution': ''}],
                        'no_relevant_facts_reason_pl': ''} for a in data['all_articles']}}
            else:
                self.assertEqual(name, 'perspective_summary', 'No repair or redundant audit call')
                response = writer(data)
            jsonschema.validate(response, settings['response_schema'])
            return response
        with patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-5-nano', on_article_cache=saved_cache.extend)
        self.assertEqual(calls, ['perspective_facts', 'perspective_summary'])
        self.assertEqual(result['fact_extraction_version'], 2)
        self.assertTrue(result['summary_pl'])
        self.assertTrue(result['shared_available'])
        self.assertEqual(len(result['perspective_facts']), 1)
        self.assertEqual(len(result['facts'][0]['article_ids']), 7)
        self.assertNotIn('evidence', result['facts'][0])
        self.assertEqual(len(saved_cache), 7)
        self.assertTrue(all(e['status'] == 'EXTRACTED' for e in saved_cache))
        self.assertTrue(all('evidence_quote' not in f for e in saved_cache for f in e['facts']))
        client = FakeMergeClient([], [], [])
        ai.persist_summary(client, topic_id=DATA['topic']['topic_id'], run_id='test', model='fake', summary=result,
            summary_hash='h', previous_row=DATA['summary'], new_article_ids=[a['article_id'] for a in articles()])
        saved = next(rows[0]['summary'] for table, rows, _ in client.upserts if table == 'topic_summaries')
        self.assertEqual(saved['current_summary']['fact_extraction_version'], 2)
        self.assertFalse(integrity.needs_fact_rebuild(saved))
        payload['previous_aggregation'] = saved
        with patch.object(ai, 'call_openai') as request, patch.object(ai, 'log'):
            ai.generate_summary_response(payload, 'gpt-5-nano')
        request.assert_not_called()

    def test_still_empty_attempt_is_recorded_and_not_paid_again(self):
        previous = copy.deepcopy(DATA['summary']['summary'])
        payload = {'topic': DATA['topic'], 'all_articles': articles(), 'new_article_ids': [], 'previous_aggregation': previous}
        with patch.object(ai, 'call_openai', return_value={}) as request, patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        request.assert_called_once()
        self.assertEqual(result['fact_extraction_version'], 2)
        previous['current_summary'] = result
        previous['perspective_state'] = result['perspective_state']
        self.assertFalse(integrity.needs_fact_rebuild(previous))
        with patch.object(ai, 'call_openai') as request, patch.object(ai, 'log'):
            ai.generate_summary_response(payload, 'gpt-5-nano')
        request.assert_not_called()

    def test_queue_reschedules_only_the_old_wholly_rejected_publication_once(self):
        topic = {**DATA['topic'], 'last_seen_at': '2026-10-07T12:00:00Z'}
        summary = {**copy.deepcopy(DATA['summary']), 'updated_at': '2026-10-07T11:00:00Z'}
        summary['summary']['article_content_hashes'] = {}  # Minimal queue DB has metadata only.
        links = DATA['links']
        rows = [(a['article_id'], a['source_id'], a['source_profile']) for a in articles()]
        assignments = [{**l, 'created_at': '2026-10-07T10:00:00Z'} for l in links]
        h = queue_tests.SummaryQueueTests()
        stats, generate, persist, _ = h.run_queue([topic], rows, links, [summary], assignments)
        self.assertEqual(stats['summaries'], 1)
        generate.assert_called_once()
        self.assertEqual(set(persist.call_args.kwargs['new_article_ids']), {a[0] for a in rows})
        summary['summary']['current_summary']['fact_extraction_version'] = 2
        stats, generate, persist, _ = h.run_queue([topic], rows, links, [summary], assignments)
        self.assertEqual(stats['summaries'], 0)
        generate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
