"""Transport savings must not change evidence, stage rules or resumable work."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch

import ai_pipeline as ai
import editorial_integrity as integrity
import perspective_summaries as p
import test_editorial_integrity as fixtures
from test_topic_titles import FakeMergeClient


def payload():
    article = {
        'article_id': 'a', 'title_original': 'Oryginalny nagłówek',
        'body_original': 'Pełna  treść.\n\nNastępny akapit.\tDalszy tekst.',
        'source_id': 'source', 'source_name': 'Nazwa źródła',
        'source_profile': 'CENTER', 'source_type': 'PRIVATE',
        'original_language': 'pl', 'published_at': '2026-11-06T09:00:00Z',
        'content_hash': 'local-hash', 'canonical_url': 'https://example.test/a',
    }
    return {'topic': {'topic_id': 't', 'working_title_pl': '[Polska] Wydarzenie'},
            'all_articles': [article], 'new_article_ids': ['a'],
            'previous_facts': [{'fact_id': 'k', 'text_pl': 'Znana informacja.', 'article_ids': ['old']}]}


class CompactRequestTests(unittest.TestCase):
    def test_wire_request_preserves_full_body_and_evidence_without_mutating_internal_input(self):
        data = payload()
        data['new_articles'] = deepcopy(data['all_articles'])
        original = deepcopy(data)
        checkpoint = p.extraction_checkpoint_key(data, 300000)
        cache_key = integrity.cache_key(data['all_articles'][0], 'gpt-6-luna', 't')
        client = MagicMock()
        client.responses.create.return_value = NS(status='completed', output_text='{}', usage=None)
        with patch('openai.OpenAI', return_value=client), \
             patch.object(ai, 'openai_api_key', return_value='test-only'), patch.object(ai, 'log'):
            ai.call_openai('Instrukcje.', data, 'gpt-6-luna', retry_limit=1)
        client.responses.create.assert_called_once()
        request = client.responses.create.call_args.kwargs
        wire = ai.extract_json(request['input'])
        for field in ('all_articles', 'new_articles'):
            expected = {k: v for k, v in original[field][0].items()
                        if k not in ('content_hash', 'canonical_url')}
            self.assertEqual(wire[field], [expected])
            self.assertEqual(wire[field][0]['body_original'], original[field][0]['body_original'])
        self.assertEqual(wire['previous_facts'], original['previous_facts'])
        self.assertEqual(wire['topic'], original['topic'])
        self.assertEqual(data, original)
        self.assertEqual(p.extraction_checkpoint_key(data, 300000), checkpoint)
        self.assertEqual(integrity.cache_key(data['all_articles'][0], 'gpt-6-luna', 't'), cache_key)
        changed = deepcopy(data)
        changed['all_articles'][0]['body_original'] += ' Uzupełnienie.'
        self.assertNotEqual(p.extraction_checkpoint_key(changed, 300000), checkpoint)
        self.assertNotEqual(integrity.cache_key(changed['all_articles'][0], 'gpt-6-luna', 't'), cache_key)

    def test_compact_json_removes_only_formatting_whitespace(self):
        data = payload()
        text = ai.model_request_input(data)
        wire = ai.model_request_payload(data)
        compact = json.dumps(wire, ensure_ascii=False, separators=(',', ':'))
        self.assertTrue(text.startswith(compact + '\n\n'))
        self.assertEqual(ai.extract_json(text), wire)
        self.assertLess(len(compact), len(json.dumps(wire, ensure_ascii=False)))
        # Do not recursively delete fields with the same names in other data.
        data['previous_aggregation'] = {'article_content_hashes': {'a': 'hash'},
                                      'canonical_url': 'retained-history-field'}
        self.assertEqual(ai.extract_json(ai.model_request_input(data))['previous_aggregation'],
                         data['previous_aggregation'])

    def test_checkpoint_and_article_cache_remain_compatible_with_preoptimization_fixture(self):
        data = {'topic': {'topic_id': 'topic-test'}, 'all_articles': [{
            'article_id': 'a', 'body_original': 'Pełna treść.', 'source_id': 'a',
            'source_profile': 'CENTER', 'content_hash': 'digest',
            'canonical_url': 'https://example.test'}]}
        ai.model_request_input(data)
        # Captured before v90. Deliberate future extractor changes may update
        # these fixtures; request formatting alone must not invalidate them.
        self.assertEqual(p.extraction_checkpoint_key(data, 300000),
                         'ce25818126ec9e021d276f0a2d8e6722bb7b530e27e8d21cae60c082fc19b5f2')
        self.assertEqual(integrity.cache_key(data['all_articles'][0], 'gpt-6-luna', 'topic-test'),
                         '00af9719d71e11f22cae3faafcf1a4a54b0f50a1ada1e323f8ddea4bcc2b7986')

    def test_schema_selects_title_rules_only_when_output_has_a_title(self):
        for schema in (None, {'properties': {'headline_pl': {'type': 'string'}}},
                       {'items': {'properties': {'title_pl': {'type': 'string'}}}}):
            with self.subTest(schema=schema):
                instructions = ai.instructions_for_response('Zasady podstawowe.', schema)
                self.assertIn(ai.POLISH_TITLE_INSTRUCTIONS, instructions)
                self.assertEqual(ai.instructions_for_response(instructions, schema), instructions)
        for base in (p.WRITING_INSTRUCTIONS, p.EXPLICIT_NOVELTY_INSTRUCTIONS, p.BRIEF_INSTRUCTIONS):
            instructions = ai.instructions_for_response(base, {'properties': {'text_pl': {'type': 'string'}}})
            self.assertTrue(instructions.startswith(base + '\n\n'))
            self.assertIn(ai.POLISH_OUTPUT_INSTRUCTIONS, instructions)
            self.assertNotIn(ai.POLISH_TITLE_INSTRUCTIONS, instructions)

    def test_production_stages_keep_complete_core_prompts_and_existing_call_count(self):
        text = 'Policja zatrzymała 8 osób w Marsylii.'
        opinion = 'Analiza Le Monde wiąże zamieszki z przebudową systemu politycznego.'
        articles = [fixtures.article('left', text, 'LEFT'), fixtures.article('right', text, 'RIGHT')]
        stages = []

        def respond(instructions, data, model, **kwargs):
            name = kwargs['response_schema_name']
            stages.append((name, instructions, kwargs['response_schema']))
            if name == 'perspective_facts':
                claims = [fixtures.claim(text, aid) for aid in ('left', 'right')]
                claims += [fixtures.claim(opinion, aid, 'EDITORIAL', 'Le Monde') for aid in ('left', 'right')]
                return fixtures.extraction(data, claims)
            if name == 'perspective_novelty_audit':
                return {'decisions': {f['fact_id']: {'decision': 'NEW', 'new_detail_pl': '',
                    'covered_fact_ids': [], 'reason_pl': 'Nowe, odrębne ustalenie.'}
                    for f in data['candidate_facts']}}
            return fixtures.writer(data)

        with patch.object(ai, 'call_openai', side_effect=respond), patch.object(ai, 'log'):
            result = ai.generate_summary_response({'topic': {'topic_id': 't'}, 'all_articles': articles},
                                                 'gpt-6-luna')
        self.assertEqual([s[0] for s in stages],
                         ['perspective_facts', 'perspective_novelty_audit', 'perspective_summary'])
        for (name, instructions, schema), base in zip(stages, (
                p.ARTICLE_EXTRACTION_INSTRUCTIONS, p.EXPLICIT_NOVELTY_INSTRUCTIONS, p.WRITING_INSTRUCTIONS)):
            with self.subTest(stage=name):
                self.assertEqual(instructions, ai.instructions_for_response(base, schema))
                self.assertTrue(instructions.startswith(base + '\n\n'))
                self.assertEqual(ai.POLISH_TITLE_INSTRUCTIONS in instructions, name == 'perspective_facts')
        self.assertIn(text, result['summary_pl'])
        self.assertEqual(len(result['perspective_sections']['EDITORIAL']), 1)
        self.assertEqual(set(result['perspective_sections']['EDITORIAL'][0]['article_ids']), {'left', 'right'})


class CheaperTitleModelTests(unittest.TestCase):
    def test_title_aliases_switch_at_shutdown_and_other_choices_remain_explicit(self):
        before = datetime(2026, 12, 10, 23, 59, 59, tzinfo=timezone.utc)
        after = datetime(2026, 12, 11, tzinfo=timezone.utc)
        for name in ('gpt-5-nano', 'gpt-5-nano-2025-08-07'):
            self.assertEqual(ai.title_model_for_run(name, before), name)
            self.assertEqual(ai.title_model_for_run(name, after), 'gpt-6-luna')
        for name in ('gpt-6-luna', 'gpt-6.1-sol', 'custom-model'):
            self.assertEqual(ai.title_model_for_run(name, after), name)

    def test_only_simple_nano_titles_default_to_minimal_reasoning(self):
        client = MagicMock()
        client.responses.create.return_value = NS(status='completed', output_text='{}', usage=None)
        with patch('openai.OpenAI', return_value=client), \
             patch.object(ai, 'openai_api_key', return_value='test-only'), patch.object(ai, 'log'):
            for stage in ('topic_labels', 'topic_titles'):
                ai.call_openai('Zasady.', {}, 'gpt-5-nano', response_schema_name=stage, retry_limit=1)
                self.assertEqual(client.responses.create.call_args.kwargs['reasoning'], {'effort': 'minimal'})
            ai.call_openai('Zasady.', {}, 'gpt-5-nano', response_schema_name='topic_titles',
                           reasoning_effort='low', retry_limit=1)
            self.assertEqual(client.responses.create.call_args.kwargs['reasoning'], {'effort': 'low'})
            ai.call_openai('Zasady.', {}, 'gpt-5-nano', response_schema_name='perspective_facts', retry_limit=1)
            self.assertNotIn('reasoning', client.responses.create.call_args.kwargs)

    def test_title_normalization_uses_effective_model_after_shutdown(self):
        client = FakeMergeClient(topics=[{'topic_id': 't', 'headline_pl': 'Błędny tytuł', 'status': 'ACTIVE'}],
                                 links=[{'topic_id': 't', 'article_id': 'a'}], summaries=[],
                                 articles=[{'article_id': 'a', 'title': 'Rząd zmienia zasady finansowania szkół'}])
        clock = MagicMock(wraps=datetime)
        clock.now.return_value = datetime(2026, 12, 11, tzinfo=timezone.utc)
        with patch.object(ai, 'TITLE_MODEL', 'gpt-5-nano'), patch.object(ai, 'datetime', clock), \
             patch.object(ai, 'log'), patch.object(ai, 'call_openai', return_value={
                 'titles': [{'topic_id': 't', 'title_pl': '[Polska] Reforma finansowania szkół'}]}) as request:
            self.assertEqual(ai.normalize_topic_titles(client), 1)
        self.assertEqual(request.call_args.args[2], 'gpt-6-luna')


if __name__ == '__main__':
    unittest.main()
