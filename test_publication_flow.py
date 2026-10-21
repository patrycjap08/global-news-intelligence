"""End-to-end queue regressions: durable batches, bounded cost and current text."""
import copy
import os
import sqlite3
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import ai_pipeline as ai
import perspective_summaries as p
import editorial_integrity as integrity
from test_editorial_integrity import article, claim, extraction, writer
from test_novelty_decisions_and_resume import decision
from test_topic_titles import FakeMergeClient


class PersistingClient(FakeMergeClient):
    def __init__(self, topics, links, summaries, fail_cache=False):
        super().__init__(topics, links, summaries)
        self.owner = threading.get_ident()
        self.fail_cache = fail_cache

    def upsert(self, table, rows, *, on_conflict):
        assert threading.get_ident() == self.owner, 'Database writes must stay on coordinator'
        if self.fail_cache and any(r.get('stage') == 'ARTICLE_EXTRACTION_CACHE' for r in rows):
            raise RuntimeError('Storage unavailable')
        super().upsert(table, rows, on_conflict=on_conflict)
        keys = on_conflict.split(',')
        existing = self.rows.setdefault(table, [])
        for row in rows:
            old = next((r for r in existing if all(r.get(k) == row.get(k) for k in keys)), None)
            if old is None:
                existing.append(copy.deepcopy(row))
            else:
                old.update(copy.deepcopy(row))


class PublicationFlowTests(unittest.TestCase):
    def setup_queue(self, folder, count=10, fail_cache=False):
        db = Path(folder) / 'articles.sqlite3'
        rows = [article(f'a{i:02}', f'Rada miasta przyjęła projekt inwestycji numer {i}.') for i in range(count)]
        with sqlite3.connect(db) as conn:
            conn.execute('CREATE TABLE articles (article_id TEXT PRIMARY KEY, source_id TEXT, source_profile TEXT)')
            conn.executemany('INSERT INTO articles VALUES(?,?,?)', [(r['article_id'], r['source_id'], 'CENTER') for r in rows])
        client = PersistingClient([{'topic_id': 'topic_perspectives_test', 'headline_pl': '[Polska] Inwestycje miasta',
            'last_seen_at': '2026-10-21T08:00:00Z', 'status': 'ACTIVE'}],
            [{'topic_id': 'topic_perspectives_test', 'article_id': a['article_id']} for a in rows], [], fail_cache)
        def build(base, new_rows, all_rows):
            return {**base, 'all_articles': rows, 'new_article_ids': [a['article_id'] for a in new_rows]}, 0, 'test'
        return db, client, build

    def run_queue(self, db, client, build, request):
        with patch.object(ai, 'build_bounded_summary_input', side_effect=build), \
             patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log'), \
             patch.object(ai, 'now', return_value='2026-10-21T08:00:00Z'):
            return ai.retry_incomplete_summaries(db, 'run', client, model='gpt-5-nano')

    def test_partial_transport_failure_reuses_first_persisted_batch(self):
        with TemporaryDirectory() as folder:
            db, client, build = self.setup_queue(folder)
            reads = []
            def request(instructions, data, model, **settings):
                name = settings['response_schema_name']
                if name == 'perspective_facts':
                    reads.append([a['article_id'] for a in data['all_articles']])
                    if len(reads) == 2:
                        saved = [r for r in client.rows.get('topic_runs', []) if r['stage'] == 'ARTICLE_EXTRACTION_CACHE']
                        self.assertEqual(len(saved), 8, 'First batch must be durable before the second request')
                        raise RuntimeError('Transport failed during second batch')
                    return extraction(data, [claim(a['body_original'], a['article_id']) for a in data['all_articles']])
                if name == 'perspective_novelty_audit':
                    return {'decisions': {f['fact_id']: decision('NEW') for f in data['candidate_facts']}}
                return writer(data)
            first = self.run_queue(db, client, build, request)
            self.assertEqual(first, {'summaries': 0, 'failed_summaries': 1})
            second = self.run_queue(db, client, build, request)
            self.assertEqual(second, {'summaries': 1, 'failed_summaries': 0})
            self.assertEqual(reads[2], ['a08', 'a09'])
            stored = client.rows['topic_summaries'][0]['summary']
            self.assertEqual(stored['current_summary']['quality_report']['cached_articles'], 8)
            self.assertEqual(stored['current_summary']['quality_report']['read_articles'], 2)
            self.assertEqual(len(stored['perspective_state']['perspective_facts']), 10)
            self.assertEqual(len(stored['processed_article_ids']), 10)
            self.assertEqual(self.run_queue(db, client, build, request)['summaries'], 0)
            self.assertEqual(len(reads), 3, 'A completed topic must not read articles again')

    def test_failed_cache_write_stops_before_next_paid_request(self):
        with TemporaryDirectory() as folder:
            db, client, build = self.setup_queue(folder, fail_cache=True)
            calls = []
            def request(instructions, data, model, **settings):
                calls.append(settings['response_schema_name'])
                return extraction(data, [claim(a['body_original'], a['article_id']) for a in data['all_articles']])
            self.assertEqual(self.run_queue(db, client, build, request), {'summaries': 0, 'failed_summaries': 1})
            self.assertEqual(calls, ['perspective_facts'])
            self.assertEqual(client.rows['topic_summaries'], [])

    def test_budget_reserves_audit_and_writing_without_unbounded_extraction(self):
        rows = [article(str(i), f'Rada miasta przyjęła projekt inwestycji numer {i}.') for i in range(30)]
        calls = []
        def request(instructions, data, model, **settings):
            name = settings['response_schema_name']; calls.append(name)
            self.assertEqual(settings['retry_limit'], 1)
            self.assertEqual(settings['max_output_tokens'], 16000)
            if name == 'perspective_facts':
                return extraction(data, [claim(a['body_original'], a['article_id']) for a in data['all_articles']])
            if name == 'perspective_novelty_audit':
                return {'decisions': {f['fact_id']: decision('NEW') for f in data['candidate_facts']}}
            return writer(data)
        with patch.dict(os.environ, {'AI_TOPIC_MAX_CALLS': '3'}), patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log'):
            result = ai.generate_summary_response({'topic': {}, 'all_articles': rows}, 'gpt-5-nano')
        self.assertEqual(calls, ['perspective_facts', 'perspective_novelty_audit', 'perspective_summary'])
        self.assertEqual(result['quality_report']['read_articles'], 8)
        self.assertEqual(len(result['perspective_facts']), 8)
        self.assertTrue(result['quality_report']['budget_skipped_stages'])
        self.assertTrue(result['summary_pl'])

    def test_changed_article_retracts_old_unsupported_claim_and_refreshes_current_text(self):
        old = article('a', 'Policja zatrzymała 8 osób w Marsylii.')
        new = {**old, 'body_original': 'Policja zatrzymała 10 osób w Marsylii.', 'content_hash': 'changed'}
        other = article('b', 'Rzecznik policji odmówił komentarza.')
        _, known = p.route_facts({'facts': [claim(old['body_original'], 'a')]}, [old, other], [], ai.normalize_generated_text)
        payload = {'topic': {}, 'all_articles': [new, other], 'new_article_ids': [], 'previous_aggregation': {
            'base_summary': {'perspective_version': 1, 'summary_pl': old['body_original'], 'perspective_facts': known},
            'processed_article_ids': ['a', 'b'], 'article_content_hashes': {'a': 'old'}}}
        def call(instructions, data, schema, name):
            if name == 'perspective_facts': return extraction(data, [claim(new['body_original'], 'a')])
            return writer(data)
        result = p.generate(payload, call, ai.normalize_generated_text, allow_omissions=True)
        self.assertIn('10 osób', result['summary_pl'])
        self.assertNotIn('8 osób', result['summary_pl'])
        self.assertEqual(len(result['perspective_facts']), 1)

    def test_only_opinions_require_no_narrative_request(self):
        a = article('a', 'Le Monde ocenia decyzję rady jako ryzykowną.', 'LEFT')
        stages = []
        def call(instructions, data, schema, name):
            stages.append(name)
            return extraction(data, [claim(a['body_original'], 'a', 'EDITORIAL', 'Le Monde')])
        result = p.generate({'topic': {}, 'all_articles': [a]}, call, ai.normalize_generated_text, allow_omissions=True)
        self.assertEqual(stages, ['perspective_facts'])
        self.assertEqual(result['summary_pl'], '')
        self.assertEqual(len(result['perspective_sections']['EDITORIAL']), 1)

    def test_invalid_writer_is_not_retried_and_does_not_erase_usable_claims(self):
        a = article('a', 'Policja zatrzymała 8 osób w Marsylii.')
        stages = []
        def call(instructions, data, schema, name):
            stages.append(name)
            if name == 'perspective_facts': return extraction(data, [claim(a['body_original'], 'a')])
            return {}
        result = p.generate({'topic': {}, 'all_articles': [a]}, call, ai.normalize_generated_text, allow_omissions=True)
        self.assertEqual(stages, ['perspective_facts', 'perspective_summary'])
        self.assertIn(a['body_original'], result['summary_pl'])
        self.assertEqual(len(result['facts']), 1)

    def test_article_cache_is_scoped_to_event_model_and_body(self):
        a = article('a', 'Opis dwóch różnych wydarzeń.')
        baseline = integrity.cache_key(a, 'model', 'event1')
        for changed, model, topic in [(a, 'other', 'event1'), (a, 'model', 'event2'),
                                      ({**a, 'body_original': 'Inna treść.'}, 'model', 'event1')]:
            self.assertNotEqual(baseline, integrity.cache_key(changed, model, topic))

    def test_old_quotes_do_not_force_unnecessary_single_article_batches(self):
        text = 'Policja zatrzymała 8 osób w Marsylii.'
        rows = [article(str(i), text) for i in range(9)]
        _, known = p.route_facts({'facts': [claim(text, '0')]}, rows, [], ai.normalize_generated_text)
        known[0]['evidence'] = {'0': {'quote': 'Dawny długi fragment. ' * 2000}}
        payload = {'topic': {}, 'all_articles': rows, 'new_article_ids': [str(i) for i in range(1,9)],
                   'previous_aggregation': {'processed_article_ids': ['0'], 'base_summary': {
                       'perspective_version': 1, 'summary_pl': text, 'perspective_facts': known}}}
        calls = []
        def call(instructions, data, schema, name):
            calls.append(name)
            self.assertEqual(len(data['all_articles']), 8)
            self.assertNotIn('evidence', data['previous_facts'][0])
            return extraction(data, [claim(text, a['article_id']) for a in data['all_articles']])
        p.generate(payload, call, ai.normalize_generated_text, allow_omissions=True, max_payload_chars=8000)
        self.assertEqual(calls, ['perspective_facts'])

    def test_legacy_publication_keeps_full_facts_in_base(self):
        client = PersistingClient([], [], [])
        ai.persist_summary(client, topic_id='legacy', run_id='run', model='fake', summary={
            'summary_pl': 'Synteza starego formatu.', 'facts': [{'text_pl': 'Rada miasta przyjęła budżet.', 'article_ids': ['a']}]},
            summary_hash='hash', previous_row=None, new_article_ids=['a'])
        stored = client.rows['topic_summaries'][0]['summary']
        self.assertNotIn('current_summary', stored)
        self.assertEqual(len(stored['base_summary']['facts']), 1)

if __name__ == '__main__': unittest.main()
