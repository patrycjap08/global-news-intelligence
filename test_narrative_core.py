"""Replay the published SpaceX synthesis that lost Musk's actual promise."""
import copy
import json
from pathlib import Path
import unittest

import ai_pipeline as ai
import editorial_integrity as integrity
import perspective_summaries as p
import test_summary_queue as queue_tests
from test_writing_fixtures import article_response


FIXTURE = json.loads(Path(__file__).with_name('test_data').joinpath(
    'curfew_spacex_publication_20261021.json').read_text())


def stored(record, text=None):
    narrative = record['summary_pl'] if text is None else text
    current = {'publication_version': 2, 'perspective_version': 1,
               'summary_pl': narrative, 'topic': {'headline_pl': record['topic']['headline_pl']}}
    return {'base_summary': current, 'current_summary': current,
            'perspective_state': {'perspective_facts': copy.deepcopy(record['facts']),
                                  'facts': copy.deepcopy(record['facts'])},
            'processed_article_ids': [a['article_id'] for a in record['articles']]}


class NarrativeCoreTests(unittest.TestCase):
    def test_real_spacex_omission_is_detected_but_complete_curfew_is_not(self):
        record = FIXTURE['spacex']
        primary = integrity.primary_fact(record['facts'], record['topic']['headline_pl'])
        self.assertEqual(primary['fact_id'], 'fact_ce9b336b54aeddcd921be972')
        self.assertTrue(integrity.narrative_missing_core(
            record['topic']['headline_pl'], record['summary_pl'], record['facts']))
        curfew = FIXTURE['curfew']
        self.assertFalse(integrity.narrative_missing_core(
            curfew['topic']['headline_pl'], curfew['summary_pl'], curfew['facts']))
        complete = 'Elon Musk obiecał przekazać po jednej akcji SpaceX każdemu dziecku w USA.'
        self.assertFalse(integrity.narrative_missing_core(
            record['topic']['headline_pl'], complete, record['facts']))

    def test_valid_remaining_paragraph_must_not_hide_rejected_main_paragraph(self):
        record = FIXTURE['spacex']
        facts = record['facts']
        primary = integrity.primary_fact(facts, record['topic']['headline_pl'])
        calls = []
        def call(instructions, data, schema, name):
            calls.append(name)
            self.assertEqual(name, 'perspective_summary', 'No extraction, novelty audit or repair call')
            self.assertEqual(data['primary_fact_id'], primary['fact_id'])
            return article_response([
                {'text_pl': 'Elon Musk zapowiedział przekazanie w przyszłym roku po jednej akcji SpaceX każdemu dziecku w USA.',
                 'fact_ids': [primary['fact_id']]},
                {'text_pl': record['summary_pl'], 'fact_ids': [facts[1]['fact_id'], facts[2]['fact_id']]},
            ])
        previous = stored(record)
        payload = {'topic': {'topic_id': record['topic']['topic_id'], 'working_title_pl': record['topic']['headline_pl']},
                   'all_articles': record['articles'], 'new_article_ids': [], 'previous_aggregation': previous}
        original = copy.deepcopy(payload)
        result = p.generate(payload, call, ai.normalize_generated_text, allow_omissions=True)
        self.assertEqual(calls, ['perspective_summary'])
        self.assertIn(primary['text_pl'], result['summary_pl'])
        self.assertIn('146', result['summary_pl'])
        self.assertTrue(result['quality_report']['narrative_core_fallback'])
        self.assertEqual(result['quality_report']['read_articles'], 0)
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(len(result['facts']), 5, 'Retain differing valuations and eligibility details')
        self.assertEqual(payload, original, 'No mutation of published evidence')
        self.assertFalse(integrity.narrative_missing_core(
            record['topic']['headline_pl'], result['summary_pl'], result['facts']))

    def test_queue_refreshes_only_missing_core_without_marking_old_articles_new(self):
        record = FIXTURE['spacex']
        topic = {**record['topic'], 'last_seen_at': '2026-10-07T12:00:00Z'}
        tid = topic['topic_id']
        articles = [(a['article_id'], a['source_id'], a['source_profile']) for a in record['articles']]
        links = [{'topic_id': tid, 'article_id': a[0]} for a in articles]
        assignments = [{**link, 'created_at': '2026-10-07T10:00:00Z'} for link in links]
        h = queue_tests.SummaryQueueTests()
        summaries = [{'topic_id': tid, 'version': 1, 'summary': stored(record),
                      'updated_at': '2026-10-07T11:00:00Z'}]
        stats, generate, persist, _ = h.run_queue([topic], articles, links, summaries, assignments)
        self.assertEqual(stats['summaries'], 1)
        generate.assert_called_once()
        self.assertEqual(persist.call_args.kwargs['new_article_ids'], [])
        fixed = record['facts'][0]['text_pl'] + '\n\n' + record['summary_pl']
        summaries[0]['summary'] = stored(record, fixed)
        summaries[0]['summary']['current_summary']['brief_generation_version'] = integrity.BRIEF_GENERATION_VERSION
        stats, generate, persist, _ = h.run_queue([topic], articles, links, summaries, assignments)
        self.assertEqual(stats['summaries'], 0)
        generate.assert_not_called()
        persist.assert_not_called()

    def test_one_headline_anchor_is_not_enough_to_schedule_writing(self):
        self.assertFalse(integrity.narrative_missing_core(
            'Musk', 'Notowania spółki.', FIXTURE['spacex']['facts']))


if __name__ == '__main__':
    unittest.main()
