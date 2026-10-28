"""Provider policy blocks must not retry content or discard unrelated work."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from openai import AuthenticationError, BadRequestError

import ai_pipeline as ai
import news_pipeline
from supabase_sync import ARTICLE_COLUMNS, pull_state


def api_error(code='invalid_prompt', message=None, *, nested=True, status=400):
    message = message or 'Invalid prompt: your prompt was flagged as potentially violating our usage policy.'
    body = {'message': message, 'type': 'invalid_request_error', 'code': code}
    if nested:
        body = {'error': body}
    cls = AuthenticationError if status == 401 else BadRequestError
    return cls(message, response=httpx.Response(status, headers={'x-request-id': 'req-policy-test'},
        request=httpx.Request('POST', 'https://api.openai.com/v1/responses')), body=body)


class ReviewClient:
    def __init__(self, articles):
        self.articles = copy.deepcopy(articles)
        self.writes, self.updates = [], []
        self.assignments = []

    def select_all(self, table, **kwargs):
        if table == 'articles':
            return copy.deepcopy(self.articles)
        return copy.deepcopy(self.assignments) if table == 'article_topic_assignments' else []

    def upsert(self, table, rows, *, on_conflict):
        self.writes.append((table, copy.deepcopy(rows)))
        if table == 'article_topic_assignments':
            self.assignments.extend(copy.deepcopy(rows))

    def update(self, table, values, *, filters):
        self.updates.append((table, copy.deepcopy(values), filters))
        if table == 'articles':
            ids = filters[0][1].removeprefix('in.(').removesuffix(')').split(',')
            for row in self.articles:
                if row['article_id'] in ids:
                    row.update(copy.deepcopy(values))


class LabelingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / 'articles.db'
        timestamp = datetime.now(timezone.utc).isoformat()
        self.articles = [dict.fromkeys(ARTICLE_COLUMNS.split(','), '') | dict(
            article_id=f'a{i:02}', source_id='source', source_name='Source', canonical_url=f'https://example.test/{i}',
            original_url=f'https://example.test/{i}', item_kind='ARTICLE', fetch_method='HTTP',
            title=f'Informacja numer {i}', original_language='pl', body='Artykuł źródłowy ' * 100,
            topic_hint=f'original-{i}', content_status='COMPLETE', word_count=300, fetched_at=timestamp,
            first_seen_at=timestamp, last_seen_on_homepage_at=timestamp) for i in range(30)]
        self.client = ReviewClient(self.articles)
        pull_state(self.db, self.client)

    def call(self):
        return ai.call_openai('Test.', {'articles': []}, 'gpt-6-luna', retry_limit=3,
            response_schema={'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
            response_schema_name='topic_labels')

    def test_policy_400_is_recognized_once_for_nested_and_direct_api_bodies(self):
        for nested in (True, False):
            with self.subTest(nested=nested), patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), \
                 patch('openai.OpenAI') as sdk, patch.object(ai, 'wait_before_openai_retry') as wait:
                sdk.return_value.responses.create.side_effect = api_error(nested=nested)
                with self.assertRaises(ai.AIContentPolicyError) as caught:
                    self.call()
                sdk.return_value.responses.create.assert_called_once()
                wait.assert_not_called()
                self.assertEqual(caught.exception.response_details['code'], 'invalid_prompt')
                self.assertEqual(caught.exception.response_details['request_id'], 'req-policy-test')
                self.assertFalse(ai.is_retryable_openai_error(caught.exception))
                self.assertTrue(ai.parse_failure_for_storage(caught.exception)['policy_rejection'])

    def test_refusal_and_content_filter_are_not_treated_as_malformed_json(self):
        responses = [
            SimpleNamespace(status='completed', usage=None, output_text='{}', id='resp-test',
                output=[SimpleNamespace(content=[SimpleNamespace(type='refusal', refusal='Refused')])]),
            SimpleNamespace(status='completed', usage=None, output_text='', id='resp-test',
                output=[{'content': [{'type': 'refusal', 'refusal': 'Refused'}]}]),
            SimpleNamespace(status='incomplete', usage=None, output_text='', output=[],
                incomplete_details=SimpleNamespace(reason='content_filter')),
            SimpleNamespace(status='failed', usage=None, output_text='', output=[],
                error=SimpleNamespace(code='content_policy_violation')),
        ]
        for response in responses:
            with self.subTest(response=response), patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), \
                 patch('openai.OpenAI') as sdk, patch.object(ai, 'log'):
                sdk.return_value.responses.create.return_value = response
                with self.assertRaises(ai.AIContentPolicyError):
                    self.call()
                sdk.return_value.responses.create.assert_called_once()

    def test_rejected_batch_is_retained_with_audit_and_never_requeued_after_remote_pull(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('openai.OpenAI') as sdk, patch.object(ai, 'log'):
            sdk.return_value.responses.create.side_effect = api_error()
            stats = ai._label_pending_batch('harvest-test', self.client, self.articles,
                db_path=self.db, batch_index=26)
            sdk.return_value.responses.create.assert_called_once()
        self.assertEqual(stats['label_policy_blocked'], 30)
        self.assertEqual(stats['label_needs_review'], 30)
        self.assertEqual(stats['excluded'], 0)
        self.assertEqual(stats['candidate_topics'], 0)
        self.assertEqual({table for table, rows in self.client.writes}, {'topic_runs'})
        audit = self.client.writes[0][1][0]
        self.assertEqual(audit['status'], 'FAILED')
        self.assertEqual(audit['raw_output']['article_ids'], [a['article_id'] for a in self.articles])
        self.assertEqual(audit['raw_output']['disposition'], 'NEEDS_REVIEW_NO_AUTOMATIC_RETRY')
        self.assertEqual(audit['raw_output']['original_topic_hints']['a00'], 'original-0')
        marker = f"AI_REVIEW:OPENAI_CONTENT_POLICY:{audit['topic_run_id']}"
        for old, row in zip(self.articles, self.client.articles):
            self.assertEqual(row, {**old, 'topic_hint': marker})
        for path in (self.db, Path(self.folder.name) / 'fresh-run.db'):
            if path != self.db:
                pull_state(path, self.client)
            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                self.assertEqual(ai.pending_articles(conn, self.client, 0), [])
                self.assertEqual(conn.execute('SELECT count(*) FROM articles').fetchone()[0], 30)

    def test_entire_flow_continues_after_blocked_batch_without_split_or_repeat_on_ai_only(self):
        def response(**request):
            # The first 25 articles are blocked, the last 5 accepted. No child
            # request may contain rejected content, including on the next run.
            data = json.loads(request['input'].split('\n\nReturn only valid JSON.')[0])
            ids = [a['article_id'] for a in data['articles']]
            if ids == [a['article_id'] for a in self.articles[:25]]:
                raise api_error()
            self.assertEqual(set(ids), {a['article_id'] for a in self.articles[25:]})
            decisions = {aid: {'category': 'KEEP', 'working_title_pl': '[Polska] Budowa nowych szkół w mieście',
                               'reason': ''} for aid in ids}
            return SimpleNamespace(status='completed', usage=None, output_text=json.dumps({'decisions': decisions}), output=[])
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch('openai.OpenAI') as sdk, \
             patch.object(ai, 'merge_active_topics', return_value={
                 'merge_candidates': 0, 'topics_merged': 0, 'merge_failed': 0,
                 'local_candidate_groups': 0, 'local_candidate_topics': 0, 'largest_candidate_group': 0,
                 'merge_requests': 0}) as merge, patch.object(ai, 'normalize_topic_titles', return_value=0) as titles, \
             patch.object(ai, 'classify_topic_categories', return_value=0) as categories, \
             patch.object(ai, 'retry_incomplete_summaries', return_value={'summaries': 0, 'failed_summaries': 0}) as summaries, \
             patch.object(ai, 'log'):
            sdk.return_value.responses.create.side_effect = response
            stats = ai.analyze_run(self.db, 'harvest-test', self.client, batch_size=25)
            self.assertEqual(stats['label_policy_blocked'], 25)
            self.assertEqual(stats['labeled_articles'], 5)
            self.assertIn('artykuły odłożone po odrzuceniu przez OpenAI: 25', news_pipeline.ai_summary(stats))
            for next_stage in (merge, titles, categories, summaries):
                next_stage.assert_called_once()
            self.assertEqual(sdk.return_value.responses.create.call_count, 2)
            stats = ai.analyze_run(self.db, 'harvest-test', self.client, batch_size=25)
            self.assertEqual(stats['pending_articles'], 0)
            self.assertEqual(sdk.return_value.responses.create.call_count, 2)
        candidates = [row for table, rows in self.client.writes if table == 'topic_articles' for row in rows]
        self.assertEqual({r['article_id'] for r in candidates}, {a['article_id'] for a in self.articles[25:]})

    def test_auth_and_configuration_errors_still_abort_without_quarantining_articles(self):
        for error in (api_error('expired_secret_key', 'Your API key has expired.', status=401),
                      api_error('invalid_prompt', 'Unknown model configuration.')):
            with self.subTest(code=error.code), patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), \
                 patch('openai.OpenAI') as sdk, patch.object(ai, 'log'):
                sdk.return_value.responses.create.side_effect = error
                with self.assertRaises(type(error)):
                    ai._label_pending_batch('harvest-test', self.client, self.articles, db_path=self.db)
                sdk.return_value.responses.create.assert_called_once()
        self.assertEqual(self.client.updates, [])
        with sqlite3.connect(self.db) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(len(ai.pending_articles(conn, self.client, 0)), 30)

    def test_failed_remote_review_write_is_not_reported_as_a_successful_skip(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), \
             patch.object(ai, 'call_openai', side_effect=ai.AIContentPolicyError('topic_labels')), \
             patch.object(self.client, 'update', side_effect=RuntimeError('Storage unavailable')), \
             patch.object(ai, 'log'):
            with self.assertRaisesRegex(RuntimeError, 'Storage unavailable'):
                ai._label_pending_batch('harvest-test', self.client, self.articles, db_path=self.db)
        with sqlite3.connect(self.db) as conn:
            conn.row_factory = sqlite3.Row
            self.assertEqual(len(ai.pending_articles(conn, self.client, 0)), 30)


if __name__ == '__main__':
    unittest.main()
