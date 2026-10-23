"""Offline experiments exercise the real pipeline with a deterministic fake API."""
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import synthesis_lab as lab
import test_editorial_integrity as fixtures


TEXT = 'Policja zatrzymała 8 osób w Marsylii.'
OPINION = 'Analiza Le Monde wiąże zamieszki z przebudową systemu politycznego.'


def record():
    return {'topic': {'topic_id': 'topic-test', 'headline_pl': '[Francja] Zatrzymania w Marsylii'},
            'articles': [fixtures.article('left', TEXT, 'LEFT'),
                         fixtures.article('right', TEXT, 'RIGHT')]}


class FakeAPI:
    def __init__(self):
        self.requests, self.client_options = [], []
        self.status = 'completed'
        self.error = None

    def __call__(self, **kwargs):
        self.client_options.append(kwargs)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def responses(self):
        return self

    def create(self, **request):
        self.requests.append(copy.deepcopy(request))
        if self.error:
            raise self.error
        data = lab.ai.extract_json(request['input'])
        name = request['text']['format']['name']
        if name == 'perspective_facts':
            specs = [fixtures.claim(TEXT, aid) for aid in ('left', 'right')]
            specs += [fixtures.claim(OPINION, aid, 'EDITORIAL', 'Le Monde') for aid in ('left', 'right')]
            raw = fixtures.extraction(data, specs)
            raw.pop('headline_pl')
            raw.pop('categories')
        elif name == 'perspective_novelty_audit':
            raw = {'decisions': {f['fact_id']: {'decision': 'NEW', 'new_detail_pl': '',
                'covered_fact_ids': [], 'reason_pl': 'Nowe, odrębne ustalenie.'} for f in data['candidate_facts']}}
        else:
            facts = data['main_facts']
            raw = {'entity_context': [], 'situation_context': {
                'text_pl': 'W Marsylii protesty wiążą się z wysokimi kosztami życia i niezadowoleniem z polityki rządu.',
                'basis': 'GENERAL_KNOWLEDGE'}, 'paragraphs': [
                    {'text_pl': f['text_pl'], 'fact_ids': [f['fact_id']], 'context_spans': []} for f in facts[:2]]}
        return NS(status=self.status, output_text=json.dumps(raw, ensure_ascii=False), id='response-test',
                  model=request['model'], usage=NS(input_tokens=1000, output_tokens=500,
                    input_tokens_details=NS(cached_tokens=200), output_tokens_details=NS(reasoning_tokens=400)))


def config():
    return {'MAX_CALLS_PER_TOPIC': 16, 'VARIANTS': [
        {'name': 'baseline', 'mode': 'full', 'stages': {
            'extraction': {'model': 'gpt-5-nano', 'reasoning_effort': 'low'},
            'audit': {'model': 'gpt-5-mini', 'reasoning_effort': 'low'},
            'writing': {'model': 'gpt-5.4-mini', 'reasoning_effort': 'medium'}}},
        {'name': 'writer', 'mode': 'writing', 'facts_from': 'baseline',
         'stages': {'writing': {'model': 'gpt-4.1-mini', 'reasoning_effort': None}}}]}


class LabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = FakeAPI()
        self.key = patch.object(lab.ai, 'openai_api_key', return_value='sk-test-only')
        self.key.start()
        self.addCleanup(self.key.stop)

    def test_readonly_client_blocks_every_write_before_network(self):
        client = lab.ReadOnlySupabase('https://example.invalid', 'test-only')
        with patch.object(lab.SupabaseRestClient, 'request', return_value=[]) as request:
            for method in ('POST', 'PATCH', 'DELETE', 'PUT'):
                with self.assertRaisesRegex(RuntimeError, 'GET'):
                    client.request(method, 'topics', payload={})
            request.assert_not_called()
            client.select('topics')
            self.assertEqual(request.call_args.args[0], 'GET')

    def test_snapshot_reads_all_linked_full_bodies_once_and_no_publication(self):
        class DB:
            def select(self, table, **kwargs):
                self.assert_table(table)
                return [{'topic_id': 't', 'headline_pl': 'SpaceX', 'merged_into_topic_id': None}]
            def assert_table(self, table):
                if table != 'topics':
                    raise AssertionError(table)
            def select_all(self, table, **kwargs):
                if table == 'topic_articles':
                    return [{'article_id': str(i)} for i in range(105)]
                if table != 'articles':
                    raise AssertionError('Unexpected table: ' + table)
                ids = json.loads('[' + kwargs['filters'][0][1][4:-1] + ']')
                return [{'article_id': aid, 'source_id': aid, 'source_name': aid, 'title': 'Tytuł',
                         'body': 'Pełny tekst. ' * 1000, 'canonical_url': 'https://example.com/' + aid,
                         'original_language': 'pl'} for aid in ids]
        with patch('sys.stdout', new=io.StringIO()):
            snapshot = lab.fetch_snapshot(DB(), ['t', 't'])
        self.assertEqual(len(snapshot['topics']), 1)
        self.assertEqual(len(snapshot['topics'][0]['articles']), 105)
        self.assertTrue(all(len(a['body_original']) > 10000 for a in snapshot['topics'][0]['articles']))
        lab.validate_snapshot(snapshot)

    def test_ambiguous_selector_does_not_choose_first_or_start_generation(self):
        db = NS(select=lambda *args, **kwargs: [] if kwargs['filters'][0][0] == 'topic_id' else [
            {'topic_id': 'a', 'headline_pl': 'SpaceX jeden'}, {'topic_id': 'b', 'headline_pl': 'SpaceX dwa'}])
        with self.assertRaisesRegex(ValueError, 'znaleziono 2'):
            lab.resolve_topic(db, 'SpaceX')
        self.assertFalse(self.fake.requests)

    def test_full_flow_uses_stage_models_preserves_one_opinion_and_omits_names_categories(self):
        result = lab.run_topic(record(), config()['VARIANTS'][0], config(), self.root, client_factory=self.fake)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual([r['model'] for r in self.fake.requests], ['gpt-5-nano', 'gpt-5-mini', 'gpt-5.4-mini'])
        self.assertTrue(all(opts['max_retries'] == 0 for opts in self.fake.client_options))
        self.assertEqual([c['stage'] for c in result['calls']], ['extraction', 'audit', 'writing'])
        self.assertIn(TEXT, result['result']['summary_pl'])
        self.assertTrue(result['result']['quality_report']['situation_context_included'])
        self.assertEqual(result['result']['summary_pl'].count('wysokimi kosztami życia'), 1)
        self.assertEqual(len(result['result']['perspective_sections']['EDITORIAL']), 1)
        self.assertEqual(set(result['result']['perspective_sections']['EDITORIAL'][0]['article_ids']), {'left', 'right'})
        extraction_schema = self.fake.requests[0]['text']['format']['schema']
        self.assertEqual(extraction_schema['required'], ['article_results'])
        self.assertEqual(result['result']['topic']['headline_pl'], record()['topic']['headline_pl'])
        self.assertEqual(result['result']['topic']['categories'], [])
        self.assertTrue(all(r['store'] is False for r in self.fake.requests))
        self.assertTrue(all(r['service_tier'] == 'default' for r in self.fake.requests))
        self.assertNotIn('sk-test-only', ''.join(path.read_text() for path in self.root.glob('*.json')))

    def test_writing_only_has_exactly_one_request_on_unchanged_facts(self):
        original = record()
        before = copy.deepcopy(original)
        base = lab.run_topic(original, config()['VARIANTS'][0], config(), self.root / 'base', client_factory=self.fake)
        self.fake.requests.clear()
        result = lab.run_topic(original, config()['VARIANTS'][1], config(), self.root / 'writer', base, self.fake)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(self.fake.requests[0]['model'], 'gpt-4.1-mini')
        self.assertNotIn('reasoning', self.fake.requests[0])
        self.assertEqual(result['result']['perspective_facts'], base['result']['perspective_facts'])
        self.assertEqual(result['result']['perspective_sections'], base['result']['perspective_sections'])
        self.assertEqual(result['result']['quality_report']['read_articles'], 0)
        self.assertEqual(original, before)

    def test_completed_runs_are_reused_and_writer_change_does_not_buy_extraction_again(self):
        snapshot = {'schema_version': 1, 'topics': [record()]}
        first = lab.run_experiments(snapshot, config(), self.root / 'results', self.fake)
        self.assertEqual(len(self.fake.requests), 4)
        again = lab.run_experiments(snapshot, config(), self.root / 'results', self.fake)
        self.assertEqual(again, first)
        self.assertEqual(len(self.fake.requests), 4)
        changed = config()
        changed['VARIANTS'][1]['stages']['writing']['model'] = 'gpt-6-luna'
        changed['VARIANTS'][1]['stages']['writing']['reasoning_effort'] = 'medium'
        lab.run_experiments(snapshot, changed, self.root / 'results', self.fake)
        self.assertEqual(len(self.fake.requests), 5)
        self.assertEqual(self.fake.requests[-1]['model'], 'gpt-6-luna')
        self.assertEqual(self.fake.requests[-1]['reasoning'], {'effort': 'medium'})

    def test_incomplete_outputs_and_api_errors_are_not_retried_and_cost_is_retained(self):
        self.fake.status = 'incomplete'
        result = lab.run_topic(record(), config()['VARIANTS'][0], config(), self.root / 'incomplete', client_factory=self.fake)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(result['calls'][0]['status'], 'omitted')
        self.assertGreater(result['known_cost_usd'], 0)
        self.fake.requests.clear()
        self.fake.error = RuntimeError('invalid key sk-test-only')
        result = lab.run_topic(record(), config()['VARIANTS'][0], config(), self.root / 'error', client_factory=self.fake)
        self.assertEqual(len(self.fake.requests), 1)
        self.assertEqual(result['status'], 'error')
        self.assertFalse(result['cost_complete'])
        self.assertNotIn('sk-test-only', json.dumps(result))
        self.assertNotIn('sk-test-only', (self.root / 'error' / 'call-01-extraction.json').read_text())

    def test_cost_counts_reasoning_once_and_separates_cached_input(self):
        usage = {'input': 1000, 'cached_input': 200, 'output': 1000, 'reasoning': 900}
        expected = (800 * .05 + 200 * .005 + 1000 * .40) / 1_000_000
        self.assertAlmostEqual(lab.cost_of('gpt-5-nano-2025-08-07', usage, lab.PRICES), expected)
        self.assertIsNone(lab.cost_of('unknown-model', usage, lab.PRICES))
        self.assertIsNone(lab.cost_of('gpt-5-nano', {**usage, 'available': False}, lab.PRICES))

    def test_report_escapes_generated_text_and_lists_input_sources(self):
        row = lab.run_topic(record(), config()['VARIANTS'][0], config(), self.root, client_factory=self.fake)
        row['result']['summary_pl'] = '<script>alert(1)</script>'
        row['variant']['name'] = '<img src=x onerror=alert(2)>'
        path = self.root / 'report.html'
        lab.write_report([row], path, [record()])
        text = path.read_text()
        self.assertNotIn('<script>', text)
        self.assertNotIn('<img ', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertIn('Materiały wejściowe (2)', text)
        self.assertIn('Oceny i interpretacje', text)

    def test_invalid_dependencies_and_settings_fail_before_any_api_call(self):
        bad = config()
        bad['VARIANTS'].reverse()
        with self.assertRaisesRegex(ValueError, 'wcześniejszy'):
            lab.validate_variants(bad)
        bad = config()
        bad['VARIANTS'][0]['stages']['writing'] = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'none'}
        with self.assertRaisesRegex(ValueError, 'none/minimal'):
            lab.validate_variants(bad)
        bad['VARIANTS'][0]['stages']['writing'] = {'model': 'gpt-5.4-mini', 'reasoning_effort': 'max'}
        with self.assertRaisesRegex(ValueError, 'xhigh'):
            lab.validate_variants(bad)
        self.assertFalse(self.fake.requests)

    def test_budget_keeps_writing_slot_and_saves_traces_without_repair_calls(self):
        conf = {**config(), 'MAX_CALLS_PER_TOPIC': 3}
        result = lab.run_topic(record(), conf['VARIANTS'][0], conf, self.root, client_factory=self.fake)
        self.assertLessEqual(len(self.fake.requests), 3)
        self.assertEqual(result['calls'][-1]['stage'], 'writing')
        self.assertEqual(len(list(self.root.glob('call-*.json'))), len(self.fake.requests))


if __name__ == '__main__':
    unittest.main()
