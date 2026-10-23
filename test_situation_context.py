"""Situation background is a paragraph, not a glossary or a paid repair."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import ai_pipeline as ai
import editorial_integrity as integrity
import perspective_summaries as p
import test_entity_context as witkoff
import test_summary_queue as queue
from test_writing_fixtures import article_response


class SituationContextTests(unittest.TestCase):
    def test_background_can_explain_pegasus_without_repeating_any_event_fact(self):
        record = json.loads(Path('test_data/pegasus_display_20261021.json').read_text())
        state = copy.deepcopy(record['summary']['summary']['perspective_state'])
        facts = [{**fact, 'lane': 'COMMON'} for fact in state['facts']]
        previous = {**record['summary']['summary'],
                    'perspective_state': {'facts': facts, 'perspective_facts': facts},
                    'processed_article_ids': [a['article_id'] for a in record['articles']]}
        previous['current_summary']['inline_context_version'] = 2
        context = 'Pegasus jest oprogramowaniem umożliwiającym dostęp do danych na telefonach. Komisja śledcza bada legalność jego wykorzystania przez polskie służby, a raport końcowy podsumowuje jej ustalenia i wnioski.'
        primary = integrity.primary_fact(facts, record['topic']['headline_pl'])
        raw = article_response([
            {'text_pl': primary['text_pl'], 'fact_ids': [primary['fact_id']]},
            {'text_pl': context, 'fact_ids': []}],
            [{'text_pl': context, 'basis': 'GENERAL_KNOWLEDGE', 'kind': 'SITUATION'}])
        calls = []
        result = p.generate({'topic': {'topic_id': record['topic']['topic_id'],
                                      'working_title_pl': record['topic']['headline_pl']},
                             'all_articles': record['articles'], 'new_article_ids': [],
                             'previous_aggregation': previous},
                            lambda *args: calls.append(args[-1]) or raw, ai.normalize_generated_text,
                            allow_omissions=True)
        self.assertEqual(calls, ['perspective_summary'])
        self.assertEqual(result['summary_pl'].split('\n\n')[1], context)
        self.assertFalse(any('oprogramowaniem' in f['text_pl'] for f in result['facts']))

    def test_real_story_keeps_written_background_but_does_not_append_it_to_a_fact_fallback(self):
        for rejected in (False, True):
            with self.subTest(rejected=rejected):
                raw = witkoff.response(reject=rejected)
                # Background dates need not occur in the admitted event facts.
                context = 'Wojna w Ukrainie trwa od pełnoskalowej rosyjskiej inwazji w 2022 roku. Negocjacje dotyczą zarówno możliwości zakończenia walk, jak i warunków przyszłego bezpieczeństwa Ukrainy.'
                span = next(s for s in raw['context_spans'] if s['kind'] == 'SITUATION')
                raw['summary_pl'] = raw['summary_pl'].replace(span['text_pl'], context)
                span.update(text_pl=context, basis='GENERAL_KNOWLEDGE')
                previous = witkoff.previous()
                previous['current_summary']['inline_context_version'] = 2
                payload = witkoff.EntityContextTests().payload(previous)
                with patch.object(ai, 'call_openai', return_value=raw) as request, patch.object(ai, 'log'):
                    result = ai.generate_summary_response(payload, 'gpt-5-nano')
                request.assert_called_once()
                self.assertEqual(request.call_args.kwargs['retry_limit'], 1)
                paragraphs = result['summary_pl'].split('\n\n')
                self.assertEqual(sum('pełnoskalowej' in text for text in paragraphs), 0 if rejected else 1)
                if not rejected:
                    self.assertEqual(paragraphs[1], context)
                self.assertEqual(result['perspective_facts'], witkoff.DATA['facts'])
                self.assertEqual(result['background_context'], [])
                self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
                self.assertEqual(result['quality_report']['situation_context_included'], not rejected)
                self.assertEqual(result['situation_context_version'], integrity.SITUATION_CONTEXT_VERSION)
                previous['current_summary'] = result
                with patch.object(ai, 'call_openai') as request, patch.object(ai, 'log'):
                    ai.generate_summary_response(payload, 'gpt-5-nano')
                request.assert_not_called()

    def test_obvious_country_definition_and_excess_roles_are_blocked_locally(self):
        facts = copy.deepcopy(witkoff.DATA['facts'])
        facts[0]['text_pl'] += ' USA i UE komentują rozmowy.'
        raw = witkoff.legacy_response(reject=True)
        raw['entity_context'].insert(0, {'mentions': ['USA'], 'description_pl': 'Stany Zjednoczone Ameryki', 'basis': 'GENERAL_KNOWLEDGE'})
        raw['entity_context'].insert(1, {'mentions': ['UE'], 'description_pl': 'Unia Europejska', 'basis': 'GENERAL_KNOWLEDGE'})
        written = {'paragraphs': [{'text_pl': facts[0]['text_pl'], 'fact_ids': [facts[0]['fact_id']]},
                                  {'text_pl': facts[2]['text_pl'], 'fact_ids': [facts[2]['fact_id']]}],
                   'entity_context': raw['entity_context']}
        p.insert_entity_context(written, facts)
        text = ' '.join(p['text_pl'] for p in written['paragraphs'])
        self.assertNotIn('USA (', text)
        self.assertNotIn('UE (', text)
        self.assertLessEqual(len(written['narrative_context']), 2)
        self.assertEqual(integrity.without_obvious_definitions(
            'USA (Stany Zjednoczone Ameryki) i UE (Unia Europejska) prowadzą rozmowy. USA (po ostatnich wyborach) zmieniły stanowisko.'),
            'USA i UE prowadzą rozmowy. USA (po ostatnich wyborach) zmieniły stanowisko.')

    def test_invalid_missing_or_unrelated_background_does_not_trigger_a_repair_loop(self):
        for context in (None, {'text_pl': '', 'basis': 'GENERAL_KNOWLEDGE'},
                        {'text_pl': 'Jowisz posiada liczne księżyce badane za pomocą sond wysyłanych przez astronomów.', 'basis': 'GENERAL_KNOWLEDGE'}):
            with self.subTest(context=context):
                raw = witkoff.response()
                span = next(s for s in raw['context_spans'] if s['kind'] == 'SITUATION')
                raw['summary_pl'] = raw['summary_pl'].replace('\n\n' + span['text_pl'], '')
                raw['paragraph_sources'].pop(1)
                raw['context_spans'].remove(span)
                if context and context.get('text_pl'):
                    raw['summary_pl'] += '\n\n' + context['text_pl']
                    raw['paragraph_sources'].append({'fact_ids': []})
                    raw['context_spans'].append({**context, 'kind': 'SITUATION'})
                previous = witkoff.previous()
                payload = witkoff.EntityContextTests().payload(previous)
                calls = []
                result = p.generate(payload, lambda *args: calls.append(args[-1]) or raw,
                                    ai.normalize_generated_text, allow_omissions=True)
                self.assertEqual(calls, ['perspective_summary'])
                self.assertIsNone(result['situation_context'])
                previous['current_summary'] = result
                p.generate(payload, lambda *args: self.fail('Do not pay for a repair'), ai.normalize_generated_text, allow_omissions=True)

    def test_existing_inline_publication_gets_one_writer_without_reextracting_articles(self):
        topic = {**witkoff.DATA['topic'], 'last_seen_at': '2026-10-07T12:00:00Z'}
        tid = topic['topic_id']
        articles = [(a['article_id'], a['source_id'], a['source_profile']) for a in witkoff.DATA['articles']]
        links = [{'topic_id': tid, 'article_id': a[0]} for a in articles]
        stored = witkoff.previous()
        stored['current_summary']['inline_context_version'] = 2
        rows = [{'topic_id': tid, 'version': 1, 'summary': stored, 'updated_at': '2026-10-07T11:00:00Z'}]
        stats, generate, persist, _ = queue.SummaryQueueTests().run_queue([topic], articles, links, rows)
        self.assertEqual(stats['summaries'], 1)
        generate.assert_called_once()
        self.assertEqual(persist.call_args.kwargs['new_article_ids'], [])
        stored['current_summary']['situation_context_version'] = integrity.SITUATION_CONTEXT_VERSION
        stats, generate, _, _ = queue.SummaryQueueTests().run_queue([topic], articles, links, rows)
        self.assertEqual(stats['summaries'], 0)
        generate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
