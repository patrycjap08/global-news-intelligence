"""One finished article replaces separately assembled context and entity prose."""
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
from test_writing_fixtures import article_response
from test_topic_titles import FakeMergeClient


DATA = json.loads(Path(__file__).with_name('test_data').joinpath(
    'olszanski_duplicate_identity_20261023.json').read_text())


def payload():
    facts = copy.deepcopy(DATA['facts'])
    ids = sorted({aid for f in facts for aid in f['article_ids']})
    current = {'summary_pl': DATA['published_summary_pl'], 'publication_version': 2,
               'perspective_version': 1, 'inline_context_version': 2, 'situation_context_version': 1,
               'topic': {'headline_pl': DATA['headline_pl']}}
    previous = {'base_summary': current, 'current_summary': current,
                'perspective_state': {'facts': facts, 'perspective_facts': facts},
                'processed_article_ids': ids, 'needs_narrative_refresh': True}
    return {'topic': {'topic_id': DATA['topic_id'], 'working_title_pl': DATA['headline_pl']},
            'all_articles': [{'article_id': aid, 'source_id': aid, 'source_name': aid,
                              'source_profile': 'CENTER', 'body_original': ''} for aid in ids],
            'new_article_ids': [], 'previous_aggregation': previous}


def finished_article():
    role = '(lidera ruchu Rodacy Kamraci)'
    lead = f'Policja zatrzymała Wojciecha Olszańskiego {role}, znanego jako Jaszczur, i doprowadziła go do aresztu śledczego zgodnie z postanowieniem Sądu Rejonowego dla Warszawy-Śródmieścia.'
    background = 'Postępowanie wiąże się z wypowiedziami podczas marszu w Grudziądzu w 2022 roku. Sąd Apelacyjny w Gdańsku uznał je za nawoływanie do nienawiści wobec Żydów.'
    primary = integrity.primary_fact(DATA['facts'], DATA['headline_pl'])
    return article_response([
        {'text_pl': lead, 'fact_ids': [primary['fact_id'], 'fact_dc03c23104c32331c8d1fc04']},
        {'text_pl': background, 'fact_ids': []}], [
            {'text_pl': role, 'kind': 'ENTITY', 'basis': 'SUPPLIED_MATERIAL'},
            {'text_pl': background, 'kind': 'SITUATION', 'basis': 'SUPPLIED_MATERIAL'}])


class SingleTextSynthesisTests(unittest.TestCase):
    def test_schema_has_only_one_field_that_supplies_display_text(self):
        schema = p.article_writing_schema(DATA['facts'])
        check_response_schema(schema)
        jsonschema.validate(finished_article(), schema)
        self.assertEqual(set(schema['required']), {'summary_pl', 'paragraph_sources', 'context_spans'})
        self.assertEqual(set(schema['properties']['paragraph_sources']['items']['properties']), {'fact_ids'})
        self.assertNotIn('entity_context', schema['properties'])
        self.assertNotIn('situation_context', schema['properties'])

    def test_real_duplicate_identity_example_is_one_writer_and_no_automatic_prose_insertion(self):
        data = payload()
        before = copy.deepcopy(data)
        raw = finished_article()
        with patch.object(ai, 'call_openai', return_value=raw) as request, patch.object(ai, 'log'), \
             patch.object(p, 'insert_entity_context', side_effect=AssertionError('No role insertion')), \
             patch.object(p, 'insert_situation_context', side_effect=AssertionError('No background insertion')):
            result = ai.generate_summary_response(data, 'gpt-6-luna')
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['response_schema_name'], 'perspective_summary')
        self.assertEqual(result['summary_pl'], raw['summary_pl'])
        self.assertEqual(result['summary_pl'].count('Wojciecha Olszańskiego'), 1)
        self.assertEqual(result['summary_pl'].count('Rodacy Kamraci'), 1)
        self.assertEqual(result['summary_pl'].count('postanowieniem Sądu Rejonowego'), 1)
        self.assertNotIn(';', result['summary_pl'])
        self.assertIsNone(result['situation_context'])
        self.assertTrue(result['quality_report']['situation_context_included'])
        self.assertFalse(result['quality_report']['narrative_fallback'])
        self.assertFalse(result['quality_report']['narrative_core_fallback'])
        self.assertEqual(result['quality_report']['api_calls'], 1)
        self.assertEqual(result['quality_report']['read_articles'], 0)
        self.assertEqual(result['perspective_facts'], DATA['facts'])
        self.assertEqual(data, before)

        client = FakeMergeClient([], [], [])
        ai.persist_summary(client, topic_id=DATA['topic_id'], run_id='test', model='fake', summary=result,
                           summary_hash='h', previous_row={'version': 1, 'summary': data['previous_aggregation']}, new_article_ids=[])
        saved = next(rows[0]['summary'] for table, rows, _ in client.upserts if table == 'topic_summaries')
        self.assertEqual(saved['current_summary']['summary_pl'], raw['summary_pl'])
        self.assertEqual(saved['perspective_state']['perspective_facts'], DATA['facts'])
        with patch.object(ai, 'call_openai') as request, patch.object(ai, 'log'):
            ai.generate_summary_response({**data, 'previous_aggregation': saved}, 'gpt-6-luna')
        request.assert_not_called()

    def test_background_can_stay_in_the_lead_or_last_without_being_moved_or_added_twice(self):
        main = [{'fact_id': 'f', 'text_pl': 'Policja zatrzymała 8 osób w Marsylii.', 'article_ids': ['a']}]
        context = 'Marsylia była miejscem wcześniejszych demonstracji związanych z wysokimi kosztami życia.'
        for paragraphs in ([{'text_pl': main[0]['text_pl'] + ' ' + context, 'fact_ids': ['f']}],
                           [{'text_pl': main[0]['text_pl'], 'fact_ids': ['f']}, {'text_pl': context, 'fact_ids': []}]):
            with self.subTest(paragraphs=paragraphs):
                raw = article_response(paragraphs, [{'text_pl': context, 'kind': 'SITUATION', 'basis': 'GENERAL_KNOWLEDGE'}])
                result = p.safe_article_written(raw, main, [])
                self.assertEqual('\n\n'.join(p['text_pl'] for p in result['paragraphs']), raw['summary_pl'])
                self.assertEqual(len(result['narrative_context']), 1)
                self.assertEqual(result['narrative_context'][0]['paragraph_index'], len(paragraphs) - 1)

    def test_current_event_numbers_ids_and_whole_event_masking_are_still_checked(self):
        main = [{'fact_id': 'f', 'text_pl': 'Policja zatrzymała 8 osób w Marsylii.', 'article_ids': ['a']}]
        text = main[0]['text_pl']
        bad = [article_response([{'text_pl': text.replace('8', '300'), 'fact_ids': ['f']}]),
               article_response([{'text_pl': text, 'fact_ids': ['alien']}]),
               article_response([{'text_pl': text, 'fact_ids': []}]),
               article_response([{'text_pl': text, 'fact_ids': ['f']}], [
                   {'text_pl': text, 'basis': 'GENERAL_KNOWLEDGE', 'kind': 'SITUATION'}]),
               article_response([{'text_pl': text.replace('8', '300'), 'fact_ids': ['f']}], [
                   {'text_pl': '300 osób', 'basis': 'GENERAL_KNOWLEDGE', 'kind': 'ENTITY'}])]
        for raw in bad:
            with self.subTest(raw=raw):
                self.assertEqual(p.safe_article_written(raw, main, [])['paragraphs'], [])
        valid = p.safe_article_written(article_response([{'text_pl': text, 'fact_ids': ['f']}]), main, [])
        self.assertEqual(len(valid['paragraphs']), 1)

    def test_partial_invalid_response_keeps_supported_article_paragraphs_without_a_second_call(self):
        raw = finished_article()
        raw['summary_pl'] += '\n\nPolicja zatrzymała go w 2099 roku.'
        raw['paragraph_sources'].append({'fact_ids': ['fact_dc03c23104c32331c8d1fc04']})
        with patch.object(ai, 'call_openai', return_value=raw) as request, patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload(), 'gpt-6-luna')
        request.assert_called_once()
        self.assertEqual(result['summary_pl'], finished_article()['summary_pl'])
        self.assertEqual(result['quality_report']['writing_validation']['rejections'], {'event_not_supported_by_cited_facts': 1})
        self.assertEqual(result['perspective_facts'], DATA['facts'])

    def test_identical_paragraph_is_removed_without_guessing_about_paraphrases(self):
        raw = finished_article()
        lead = raw['summary_pl'].split('\n\n')[0]
        # No duplicate entity metadata: only the existing exact paragraph is redundant.
        raw['context_spans'] = [s for s in raw['context_spans'] if s['kind'] != 'ENTITY']
        raw['summary_pl'] += '\n\n' + lead
        raw['paragraph_sources'].append(copy.deepcopy(raw['paragraph_sources'][0]))
        result = p.safe_article_written(raw, DATA['facts'], [])
        self.assertEqual(len(result['paragraphs']), 2)
        self.assertEqual(result['writing_validation']['rejections'], {'duplicate_paragraph': 1})

    def test_malformed_metadata_is_omitted_locally_instead_of_crashing_the_topic(self):
        for key, value in [('kind', []), ('basis', {}), ('text_pl', None)]:
            with self.subTest(key=key):
                raw = finished_article()
                raw['context_spans'][0][key] = value
                result = p.safe_article_written(raw, DATA['facts'], [])
                self.assertGreater(result['writing_validation']['rejections'].get('invalid_context_span', 0), 0)
        raw = finished_article()
        raw['paragraph_sources'][0]['fact_ids'] = [{}]
        result = p.safe_article_written(raw, DATA['facts'], [])
        self.assertEqual(result['paragraphs'], [])
        self.assertEqual(result['writing_validation']['rejections']['invalid_fields_or_fact_ids'], 1)


if __name__ == '__main__':
    unittest.main()
