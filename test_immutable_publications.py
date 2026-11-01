"""First publication stays readable while later facts and views form updates."""
import copy
import unittest
from unittest.mock import patch

import ai_pipeline as ai
import editorial_integrity as integrity
import perspective_summaries as p
from test_editorial_integrity import article, claim, extraction
from test_publication_flow import PersistingClient
from test_two_paragraph_brief import FACTS, BRIEF


class ImmutablePublicationTests(unittest.TestCase):
    def stored(self, rows, specs):
        _, facts = p.route_facts({'facts': specs}, rows, [], ai.normalize_generated_text)
        base = {'perspective_version': 1, 'publication_version': 2,
                'summary_pl': 'Policja zatrzymała 8 osób w Marsylii.',
                'brief_pl': 'Policja zatrzymała 8 osób.\n\nZatrzymania miały miejsce w Marsylii.',
                'facts': [f for f in facts if f['lane'] == 'COMMON'],
                'perspective_facts': facts, 'perspective_sections': p.fact_sections(facts)}
        return {'base_summary': base,
                'current_summary': {**base, 'summary_pl': 'Późniejszy przepisany tekst.',
                                    'brief_pl': 'Nadpisany skrót.\n\nInny tekst.'},
                'perspective_state': copy.deepcopy(base), 'processed_article_ids': [rows[0]['article_id']],
                'updates': [], 'needs_narrative_refresh': True}

    def run_update(self, stored, rows, specs, *, new_ids=('b',), verdict=None):
        calls = []
        def call(instructions, data, schema, name):
            calls.append(name)
            self.assertNotIn(name, ('perspective_summary', 'perspective_brief'))
            if name == 'perspective_facts':
                self.assertEqual([a['article_id'] for a in data['all_articles']], list(new_ids))
                return extraction(data, specs)
            self.assertEqual(name, 'perspective_novelty_audit')
            self.assertNotIn('body_original', str(data))
            return {'decisions': {f['fact_id']: (verdict(f, data) if verdict else {
                'decision': 'NEW', 'new_text_pl': f['text_pl'], 'covered_fact_ids': [],
                'reason_pl': 'Nowa informacja nieobecna w dotychczasowej publikacji.'})
                for f in data['candidate_facts']}}
        result = p.generate({'topic': {'topic_id': 'topic_perspectives_immutable',
                                      'working_title_pl': '[Francja] Protesty w Marsylii'},
                             'all_articles': rows, 'new_article_ids': list(new_ids),
                             'previous_aggregation': stored}, call, ai.normalize_generated_text,
                            allow_omissions=True)
        client = PersistingClient([], [], [])
        with patch.object(ai, 'log'):
            ai.persist_summary(client, topic_id='topic_perspectives_immutable', run_id='test', model='fake',
                               summary=result, summary_hash='immutable',
                               previous_row={'version': 1, 'summary': stored}, new_article_ids=list(new_ids))
        saved = client.rows['topic_summaries'][0]['summary']
        return result, saved, calls

    def test_new_fact_preserves_initial_text_brief_and_input_record(self):
        rows = [article('a', 'Policja zatrzymała 8 osób w Marsylii.'),
                article('b', 'Minister przyjedzie do Marsylii w poniedziałek.')]
        stored = self.stored(rows, [claim(rows[0]['body_original'], 'a')])
        before = copy.deepcopy(stored)
        result, saved, calls = self.run_update(stored, rows, [claim(rows[1]['body_original'], 'b')])
        self.assertEqual(calls, ['perspective_facts', 'perspective_novelty_audit'])
        self.assertEqual(stored, before)
        self.assertEqual(saved['base_summary'], before['base_summary'])
        self.assertEqual(saved['current_summary']['summary_pl'], before['base_summary']['summary_pl'])
        self.assertEqual(saved['current_summary']['brief_pl'], before['base_summary']['brief_pl'])
        self.assertEqual(result['summary_pl'], before['base_summary']['summary_pl'])
        self.assertEqual(len(saved['updates']), 1)
        self.assertIn('Minister przyjedzie', saved['updates'][0]['new_information_pl'])
        self.assertNotIn('8 osób', saved['updates'][0]['new_information_pl'])
        self.assertTrue(saved['updates'][0]['generated_at'])
        self.assertEqual(len(saved['perspective_state']['facts']), 2)

    def test_new_editorial_view_is_an_update_for_every_independent_profile(self):
        for profile in ('LEFT', 'RIGHT', 'CENTER'):
            with self.subTest(profile=profile):
                text = 'Redakcja ocenia działania policji w Marsylii jako nadmiernie surowe.'
                rows = [article('a', 'Policja zatrzymała 8 osób w Marsylii.'), article('b', text, profile)]
                stored = self.stored(rows, [claim(rows[0]['body_original'], 'a')])
                _, saved, _ = self.run_update(stored, rows, [claim(text, 'b', 'EDITORIAL', 'Redakcja')])
                self.assertEqual(saved['base_summary'], stored['base_summary'])
                update = saved['updates'][0]
                self.assertEqual(update['status'], 'NEW_INFORMATION')
                self.assertEqual(update['perspective_sections']['COMMON'], [])
                opinion = update['perspective_sections']['EDITORIAL'][0]
                self.assertEqual(opinion['text_pl'], text)
                self.assertEqual(opinion['editorial_sources'], {profile: ['b']})

    def test_exact_confirmation_preserves_history_without_a_writer_or_new_update(self):
        text = 'Policja zatrzymała 8 osób w Marsylii.'
        rows = [article('a', text), article('b', text, 'RIGHT')]
        stored = self.stored(rows, [claim(text, 'a')])
        result, saved, calls = self.run_update(stored, rows, [claim(text, 'b')])
        self.assertEqual(calls, ['perspective_facts'])
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(saved['updates'], [])
        self.assertEqual(saved['processed_article_ids'], ['a', 'b'])
        self.assertEqual(set(saved['perspective_state']['facts'][0]['article_ids']), {'a', 'b'})
        self.assertEqual(saved['base_summary'], stored['base_summary'])

    def test_merge_publishes_imported_claims_once_without_rereading_articles(self):
        rows = [article('a', 'Policja zatrzymała 8 osób w Marsylii.'),
                article('b', 'Minister przyjedzie do Marsylii w poniedziałek.')]
        canonical = self.stored(rows, [claim(rows[0]['body_original'], 'a')])
        absorbed = self.stored([rows[1]], [claim(rows[1]['body_original'], 'b')])
        merged = integrity.merge_publications(canonical, [('absorbed', absorbed)])
        self.assertEqual(len(merged['pending_publication_fact_ids']), 1)
        _, saved, calls = self.run_update(merged, rows, [], new_ids=())
        self.assertEqual(calls, ['perspective_novelty_audit'])
        self.assertEqual(saved['base_summary'], canonical['base_summary'])
        self.assertEqual(len(saved['updates']), 1)
        self.assertNotIn('pending_publication_fact_ids', saved)
        _, again, calls = self.run_update(saved, rows, [], new_ids=())
        self.assertEqual(calls, [])
        self.assertEqual(again['updates'], saved['updates'])

    def test_three_and_four_supported_brief_paragraphs_are_valid(self):
        extra = [{'fact_id': 'f4', 'text_pl': 'Koszt budowy szkół wynosi 200 milionów złotych.'},
                 {'fact_id': 'f5', 'text_pl': 'Budowa szkół ma zakończyć się w 2028 roku.'}]
        third = {'text_pl': extra[0]['text_pl'], 'fact_ids': ['f4']}
        fourth = {'text_pl': extra[1]['text_pl'], 'fact_ids': ['f5']}
        for paragraphs in (BRIEF + [third], BRIEF + [third, fourth]):
            with self.subTest(count=len(paragraphs)):
                result = p.safe_brief_written({'brief_paragraphs': paragraphs}, FACTS + extra)
                self.assertEqual(result['brief_validation']['status'], 'VALID')
                self.assertEqual(result['brief_validation']['paragraph_count'], len(paragraphs))
        self.assertEqual(p.safe_brief_written({'brief_paragraphs': BRIEF * 3}, FACTS)['brief_pl'], '')

    def test_lab_draft_cannot_be_used_to_overwrite_a_saved_publication(self):
        with self.assertRaisesRegex(ValueError, 'jednocześnie'):
            p.generate({'all_articles': [article('a', 'Tekst')], 'previous_aggregation': {},
                        'draft_publication': {}}, lambda *args: self.fail('No paid calls'), str)


if __name__ == '__main__':
    unittest.main()
