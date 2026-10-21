import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonschema

import ai_pipeline as ai
import perspective_summaries as p
from test_perspective_summaries import article, extraction, fact
from test_topic_titles import FakeMergeClient


def verdict(text, covered=(), reason='Odrębna nowa informacja.'):
    return {'new_text_pl': text, 'covered_fact_ids': list(covered), 'reason_pl': reason}


class PerspectiveNoveltyTests(unittest.TestCase):
    def route(self, rows, raw, known=()):
        return p.route_facts({'facts': raw}, rows, list(known), ai.normalize_generated_text)[1]

    def test_real_putin_record_rejects_compound_and_paraphrases_before_ledger_and_timeline(self):
        fixture = json.loads((Path(__file__).parent / 'test_data/perspective_novelty_regression.json').read_text())
        base = fixture['base_summary']
        known = base['perspective_facts']
        known_ids = {f['fact_id'] for f in known}
        candidates = [f for f in fixture['extracted_facts'] if f['fact_id'] not in known_ids]
        # Explicit semantic judgments for the unambiguous screenshot duplicates.
        # The test verifies application/validation of judgments, not AI quality.
        rejected = {
            'fact_aa87dac380cff645812c2061': ['fact_01187d8296c911b77ed727be', 'fact_1741bab1f31c1c872f0718f7'],
            'fact_96b07eb111b2b7b88f18aa56': ['fact_7f5b7357e7a64786d7f18020'],
            'fact_158a5bff90d134a776a5fe71': ['fact_3c60268000c435e0c3c3e6e0'],
        }
        mixed_id = 'fact_85abc069dda3ddbaff66f913'
        minimal = 'Według The Wall Street Journal propozycja Putina byłaby próbą wykorzystania ocieplenia relacji między Trumpem a Rosją.'
        payload = {'topic': {}, 'all_articles': fixture['articles'],
                   'new_article_ids': fixture['update']['new_article_ids'],
                   'previous_aggregation': {'base_summary': copy.deepcopy(base)}}
        original = copy.deepcopy(payload)
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_facts':
                return extraction([fact(f['text_pl'], f['article_ids'], kind=f['kind']) for f in candidates], data['all_articles'])
            self.assertEqual(name, 'perspective_novelty_audit')
            self.assertEqual({f['fact_id'] for f in data['previous_facts']}, known_ids)
            self.assertNotIn('all_articles', data)
            self.assertNotIn('summary_pl', json.dumps(data))
            decisions = {f['fact_id']: verdict(f['text_pl']) for f in data['candidate_facts']}
            decisions.update({fid: verdict('', ids, 'Ta treść była już opisana wcześniej.') for fid, ids in rejected.items()})
            decisions[mixed_id] = verdict(minimal, ['fact_3c60268000c435e0c3c3e6e0'],
                                          'Nowe jest przypisanie motywu ocieplenia relacji; obawy już opisano.')
            result = {'decisions': decisions}
            jsonschema.validate(result, schema)
            return result

        # Replay one historical fixed response as its original request. The
        # bounded production batching is exercised separately with live mocks.
        with patch.object(p, 'EXTRACTION_BATCH_ARTICLES', len(payload['all_articles'])):
            result = p.generate(payload, call, ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_novelty_audit'])
        self.assertEqual(result['summary_pl'], base['summary_pl'])
        self.assertEqual(payload, original)
        current_ids = {f['fact_id'] for f in result['perspective_facts']}
        self.assertTrue(known_ids <= current_ids)
        self.assertFalse(set(rejected) & current_ids)
        self.assertNotIn(mixed_id, current_ids)
        self.assertEqual(len(result['perspective_facts']), 14)
        self.assertEqual(result['update']['status'], 'NEW_INFORMATION')
        self.assertEqual(len(result['update']['perspective_sections']['COMMON']), 4)
        self.assertEqual(len(result['update']['perspective_sections']['EDITORIAL']), 1)
        for fid in rejected:
            self.assertNotIn(fid, json.dumps(result['update']['perspective_sections']))
        trimmed = next(f for f in result['facts'] if f['text_pl'] == minimal)
        original_candidate = next(f for f in candidates if f['fact_id'] == mixed_id)
        self.assertEqual(trimmed['article_ids'], original_candidate['article_ids'])
        self.assertEqual(trimmed['kind'], original_candidate['kind'])
        for old in known:
            self.assertEqual(next(f for f in result['perspective_facts'] if f['fact_id'] == old['fact_id']), old)
        self.assertIn('novelty_audit', result['update'])

    def test_only_duplicates_publish_no_update_and_keep_processed_articles(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        known = self.route(rows, [fact('Trump nie przyjął propozycji.', ['l', 'r'], kind='FACT')])
        base = {'perspective_version': 1, 'summary_pl': 'Pierwotny artykuł.', 'topic': {},
                'perspective_facts': known, 'facts': known, 'background_context': []}
        calls = []

        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_facts':
                return extraction([fact('Trump dotąd nie zaakceptował dotąd propozycji.', ['r'], kind='FACT')], rows)
            candidate = data['candidate_facts'][0]
            return {'decisions': {candidate['fact_id']: verdict('', [known[0]['fact_id']], 'Parafraza znanego stanu.')}}

        result = p.generate({'topic': {}, 'all_articles': rows, 'new_article_ids': ['r'],
                             'previous_aggregation': {'base_summary': base}}, call, ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_novelty_audit'])
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        self.assertFalse(result['update']['is_update'])
        self.assertFalse(any(result['update']['perspective_sections'].values()))
        self.assertEqual(result['perspective_facts'], known)
        client = FakeMergeClient([], [], [])
        old = {'version': 1, 'summary': {'base_summary': base, 'updates': [], 'processed_article_ids': ['l']}}
        ai.persist_summary(client, topic_id='t', run_id='r', model='fake', summary=result,
                           summary_hash='h', previous_row=old, new_article_ids=['r'])
        saved = next(items[0]['summary'] for table, items, _ in client.upserts if table == 'topic_summaries')
        self.assertEqual(saved['base_summary'], base)
        self.assertEqual(saved['updates'], [])
        self.assertEqual(saved['processed_article_ids'], ['l', 'r'])
        self.assertEqual(saved['last_analysis']['status'], 'NO_NEW_INFORMATION')

    def test_true_changes_details_and_editorials_remain_and_are_not_compared_by_word_overlap(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT'), article('s', 'STATE_ALIGNED')]
        known = self.route(rows, [fact('Zatrzymano 8 osób.', ['l'], kind='FACT')])
        candidates = [fact('Według policji zatrzymano 10 osób.', ['r'], kind='STATEMENT'),
                      fact('Autor krytykuje zatrzymania.', ['r'], kind='EDITORIAL'),
                      fact('Według agencji państwowej zatrzymano 12 osób.', ['s'], kind='STATEMENT')]
        facts = self.route(rows, candidates, known)

        def call(instructions, data, schema, name):
            response = {'decisions': {f['fact_id']: verdict(f['text_pl']) for f in data['candidate_facts']}}
            jsonschema.validate(response, schema)
            return response

        audited, _ = p.audit_new_facts(facts, known, rows, call, ai.normalize_generated_text, 300000, None)
        self.assertEqual([f['text_pl'] for f in audited], [*map(lambda f: f['text_pl'], known), *[f['text_pl'] for f in candidates]])
        update = p.make_update(audited, known, True, ['r', 's'])
        self.assertEqual(len(update['perspective_sections']['COMMON']), 1)
        self.assertEqual(len(update['perspective_sections']['EDITORIAL']), 1)
        self.assertEqual(len(update['perspective_sections']['STATE']), 1)

    def test_no_audit_for_first_publication_confirmations_or_reclassification(self):
        rows = [article('l', 'LEFT'), article('r', 'RIGHT')]
        known = self.route(rows, [fact('Znany fakt.', ['l'])])
        confirmed = self.route(rows, [fact('', ['r'], known[0]['fact_id'], kind='FACT')], known)
        def call(*args):
            self.fail('No request is needed without proposed new content.')
        for facts, previous in [(confirmed, known), (confirmed, [])]:
            result, audits = p.audit_new_facts(facts, previous, rows, call, ai.normalize_generated_text, 300000, None)
            self.assertEqual(result, facts)
            self.assertEqual(audits, [])

    def test_invalid_or_missing_decisions_fail_after_one_correction(self):
        rows = [article('l', 'LEFT')]
        known = self.route(rows, [fact('Stare.', ['l'], kind='FACT')])
        facts = self.route(rows, [fact('Nowe.', ['l'], kind='FACT')], known)
        candidate = facts[-1]
        bad_responses = [
            {'decisions': {}},
            {'decisions': {candidate['fact_id']: verdict('')}},
            {'decisions': {candidate['fact_id']: verdict('', ['alien'])}},
            {'decisions': {candidate['fact_id']: verdict('', [candidate['fact_id']])}},
            {'decisions': {candidate['fact_id']: verdict(known[0]['text_pl'], [known[0]['fact_id']])}},
            {'decisions': {candidate['fact_id']: verdict('Nowe.', reason='')}},
        ]
        original = copy.deepcopy(facts)
        for bad in bad_responses:
            with self.subTest(response=bad):
                calls, retries = [], []
                def call(instructions, data, schema, name):
                    calls.append(name)
                    return copy.deepcopy(bad)
                with self.assertRaises(ValueError):
                    p.audit_new_facts(facts, known, rows, call, ai.normalize_generated_text, 300000,
                                      lambda *args: retries.append(args))
                self.assertEqual(calls, ['perspective_novelty_audit'] * 2)
                self.assertEqual(len(retries), 1)
                self.assertEqual(facts, original)

    def test_compact_audit_batches_reuse_accepted_details_and_preserve_full_texts(self):
        rows = [article('l', 'LEFT')]
        known = self.route(rows, [fact('Stare.', ['l'], kind='FACT')])
        facts = self.route(rows, [fact('Nowe A. ' * 100, ['l'], kind='FACT'),
                                 fact('Nowe B. ' * 100, ['l'], kind='FACT')], known)
        sent = []
        def call(instructions, data, schema, name):
            sent.append(copy.deepcopy(data))
            self.assertEqual(len(data['candidate_facts']), 1)
            return {'decisions': {f['fact_id']: verdict(f['text_pl']) for f in data['candidate_facts']}}
        audited, audits = p.audit_new_facts(facts, known, rows, call, ai.normalize_generated_text, 1, None)
        self.assertEqual(len(sent), 2)
        self.assertEqual(len(audits), 2)
        self.assertEqual(sent[0]['candidate_facts'][0]['text_pl'], facts[1]['text_pl'])
        self.assertEqual(sent[1]['candidate_facts'][0]['text_pl'], facts[2]['text_pl'])
        self.assertEqual(len(sent[1]['previous_facts']), 2)
        self.assertEqual([f['text_pl'] for f in audited], [f['text_pl'] for f in facts])

    def test_audit_checks_latest_ledger_and_duplicates_within_new_candidates(self):
        rows = [article('l', 'LEFT')]
        old = self.route(rows, [fact('Pierwotne.', ['l'], kind='FACT')])
        latest = self.route(rows, [fact('Fakt z wcześniejszej aktualizacji.', ['l'], kind='FACT')], old)
        responses = [fact('Parafraza poprzedniej aktualizacji.', ['l'], kind='FACT'),
                     fact('Nowy samodzielny szczegół.', ['l'], kind='FACT'),
                     fact('Inne brzmienie nowego szczegółu.', ['l'], kind='FACT')]
        calls = []
        def call(instructions, data, schema, name):
            calls.append(name)
            if name == 'perspective_facts':
                return extraction(responses, rows)
            self.assertEqual({f['fact_id'] for f in data['previous_facts']}, {f['fact_id'] for f in latest})
            a, b, c = data['candidate_facts']
            answer = {'decisions': {
                a['fact_id']: verdict('', [latest[-1]['fact_id']], 'Informacja z wcześniejszej aktualizacji.'),
                b['fact_id']: verdict(b['text_pl']),
                c['fact_id']: verdict('', [b['fact_id']], 'Duplikat wcześniejszego kandydata.'),
            }}
            jsonschema.validate(answer, schema)
            return answer
        base = {'perspective_version': 1, 'summary_pl': 'Pierwotny tekst.', 'perspective_facts': old}
        result = p.generate({'topic': {}, 'all_articles': rows, 'previous_aggregation': {
            'base_summary': base, 'perspective_state': {'perspective_facts': latest}}}, call, ai.normalize_generated_text)
        self.assertEqual(calls, ['perspective_facts', 'perspective_novelty_audit'])
        self.assertEqual(len(result['perspective_facts']), 3)
        self.assertEqual([f['text_pl'] for f in result['update']['perspective_sections']['COMMON']],
                         ['Nowy samodzielny szczegół.'])

    def test_pipeline_uses_summary_settings_and_keeps_audit_diagnostics(self):
        rows = [article('l', 'LEFT')]
        known = self.route(rows, [fact('Rada przyjęła budżet miasta.', ['l'], kind='FACT')])
        payload = {'topic': {}, 'all_articles': rows, 'previous_aggregation': {'base_summary': {
            'perspective_version': 1, 'summary_pl': 'Zachowany artykuł.', 'perspective_facts': known}}}
        calls = []
        def request(instructions, data, model, **settings):
            calls.append(settings)
            self.assertEqual(settings['reasoning_effort'], 'low')
            self.assertEqual(settings['timeout_seconds'], ai.SUMMARY_REQUEST_TIMEOUT_SECONDS)
            self.assertEqual(settings['retry_limit'], 1)
            if settings['response_schema_name'] == 'perspective_facts':
                return extraction([fact('Rada miasta sfinansuje remont szpitala.', ['l'], kind='FACT')], rows)
            self.assertNotIn('all_articles', data)
            return {'decisions': {}}
        with patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        self.assertEqual([c['response_schema_name'] for c in calls], ['perspective_facts', 'perspective_novelty_audit'])
        self.assertEqual(result['perspective_facts'], known)
        self.assertEqual(len(result['quality_report']['novelty_omissions']), 1)
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')

    def test_large_ledger_id_enum_is_shared_instead_of_repeated_per_candidate(self):
        rows = [article('l', 'LEFT')]
        known = self.route(rows, [fact(f'Znane ustalenie {i}.', ['l'], kind='FACT') for i in range(100)])
        facts = self.route(rows, [fact(f'Nowe ustalenie {i}.', ['l'], kind='FACT') for i in range(30)], known)
        requests = []
        def call(instructions, data, schema, name):
            requests.append(data)
            jsonschema.Draft202012Validator.check_schema(schema)
            ids = schema['$defs']['prior_fact_id']['enum']
            self.assertEqual(set(ids), {f['fact_id'] for f in data['previous_facts']})
            self.assertLessEqual(len(data['candidate_facts']), p.NOVELTY_BATCH_FACTS)
            def enum_count(node):
                if isinstance(node, dict):
                    return len(node.get('enum', [])) + sum(enum_count(v) for k, v in node.items() if k != 'enum')
                return sum(enum_count(v) for v in node) if isinstance(node, list) else 0
            self.assertLess(enum_count(schema), 1000)
            response = {'decisions': {f['fact_id']: verdict(f['text_pl']) for f in data['candidate_facts']}}
            jsonschema.validate(response, schema)
            return response
        audited, _ = p.audit_new_facts(facts, known, rows, call, ai.normalize_generated_text, 300000, None)
        self.assertEqual(len(audited), 130)
        self.assertEqual(len(requests), 2)

    def test_schema_excludes_self_future_cycles_and_reasonless_rewrites_from_real_runs(self):
        fixtures = json.loads((Path(__file__).parent / 'test_data/perspective_audit_failures_20261020.json').read_text())
        for fixture in fixtures:
            with self.subTest(case=fixture['case']):
                observed = fixture['response']['decisions']
                order = list(observed)
                prior_ids = {fid for d in observed.values() for fid in d['covered_fact_ids']} - set(order)
                # Synthetic ledger content: only structural ID validity is
                # tested here; these assertions do not simulate AI judgment.
                prior = [{'fact_id': fid, 'text_pl': 'Wcześniejsze ustalenie.'} for fid in sorted(prior_ids)]
                batch = [{'fact_id': fid, 'text_pl': d['new_text_pl'] or f'Kandydat {i}.'}
                         for i, (fid, d) in enumerate(observed.items())]
                schema = p.novelty_schema(prior, batch)
                good = {'decisions': {f['fact_id']: verdict(f['text_pl']) for f in batch}}
                jsonschema.validate(good, schema)
                failures = 0
                for index, cid in enumerate(order):
                    if any(fid in order[index:] for fid in observed[cid]['covered_fact_ids']):
                        bad = copy.deepcopy(good)
                        bad['decisions'][cid] = observed[cid]
                        with self.assertRaises(jsonschema.ValidationError):
                            jsonschema.validate(bad, schema)
                        failures += 1
                self.assertGreater(failures, 0)

    def test_wholly_new_text_is_copied_and_only_a_supported_detail_may_be_rewritten(self):
        prior = [{'fact_id': 'known', 'text_pl': 'Minister przyjedzie.'}]
        batch = [{'fact_id': 'new', 'text_pl': 'Minister przyjedzie w poniedziałek.'}]
        schema = p.novelty_schema(prior, batch)
        jsonschema.validate({'decisions': {'new': verdict(batch[0]['text_pl'])}}, schema)
        # The API grammar describes structure and admissible IDs. The
        # existing semantic validator enforces cross-field copy/detail rules.
        changed = {'decisions': {'new': verdict('Przyjazd ministra zaplanowano na poniedziałek.')}}
        jsonschema.validate(changed, schema)
        row = {'article_id': 'a', 'source_profile': 'CENTER'}
        ledger = [{**f, 'kind': 'FACT', 'lane': 'COMMON', 'article_ids': ['a']}
                  for f in [*prior, *batch]]
        with self.assertRaisesRegex(ValueError, 'wymaga wskazania'):
            p.audit_new_facts(ledger, ledger[:1], [row], lambda *args: copy.deepcopy(changed),
                              ai.normalize_generated_text, 300000, None)
        jsonschema.validate({'decisions': {'new': verdict('Przyjazd ministra zaplanowano na poniedziałek.', ['known'])}}, schema)

    def test_actual_duplicate_reference_failure_is_normalized_without_retrying_decisions(self):
        fixture = json.loads((Path(__file__).parent / 'test_data/perspective_duplicate_references_20261020.json').read_text())
        observed = fixture['response']
        cids = set(observed['decisions'])
        prior_ids = {fid for d in observed['decisions'].values() for fid in d['covered_fact_ids']} - cids
        # The exact request was not logged. Reconstruct only the structural
        # ID relationships, keeping the real verdicts and duplicate unchanged.
        known = [{'fact_id': fid, 'text_pl': f'Wcześniejsze ustalenie {i}.',
                  'kind': 'FACT', 'article_ids': ['source'], 'lane': 'COMMON'}
                 for i, fid in enumerate(sorted(prior_ids))]
        candidates = [{'fact_id': cid, 'text_pl': d['new_text_pl'] or f'Kandydat {i}.',
                       'kind': 'FACT', 'article_ids': ['source'], 'lane': 'COMMON'}
                      for i, (cid, d) in enumerate(observed['decisions'].items())]
        rows = [article('source', 'CENTER')]
        retries, calls = [], []
        original = copy.deepcopy(observed)

        def call(instructions, data, schema, name):
            calls.append(name)
            jsonschema.validate(observed, schema)
            return copy.deepcopy(observed)

        audited, audits = p.audit_new_facts([*known, *candidates], known, rows, call,
            ai.normalize_generated_text, 300000, lambda *args: retries.append(args))
        self.assertEqual(calls, ['perspective_novelty_audit'])
        self.assertEqual(retries, [])
        self.assertEqual(len(audited), len(known) + 2)
        verdicts = audits[0]['decisions']
        cid = 'fact_5e06893a906c8d5a2dda41ce'
        self.assertEqual(len(observed['decisions'][cid]['covered_fact_ids']), 39)
        self.assertEqual(len(verdicts[cid]['covered_fact_ids']), 38)
        self.assertEqual(verdicts[cid]['covered_fact_ids'],
                         list(dict.fromkeys(observed['decisions'][cid]['covered_fact_ids'])))
        self.assertEqual(audits[0]['raw_decisions'], observed['decisions'])
        self.assertEqual(observed, original)

    def test_repeated_valid_references_do_not_create_news_or_infer_citations(self):
        rows = [article('l', 'CENTER'), article('r', 'CENTER')]
        known = self.route(rows, [fact('Minister złożył dymisję.', ['l'], kind='FACT')])
        facts = self.route(rows, [fact('Minister podał się do dymisji.', ['r'], kind='FACT')], known)
        cid = facts[-1]['fact_id']
        response = {'decisions': {cid: verdict('', [known[0]['fact_id']] * 3, 'Parafraza znanego faktu.')}}
        calls, retries = [], []
        def call(*args):
            calls.append(args[-1])
            return copy.deepcopy(response)
        audited, _ = p.audit_new_facts(facts, known, rows, call, ai.normalize_generated_text,
                                       300000, lambda *args: retries.append(args))
        self.assertEqual(audited, known)
        self.assertEqual(audited[0]['article_ids'], ['l'])
        self.assertEqual(p.make_update(audited, known, True, ['r'])['status'], 'NO_NEW_INFORMATION')
        self.assertEqual(calls, ['perspective_novelty_audit'])
        self.assertEqual(retries, [])

    def test_deduplication_does_not_admit_foreign_self_or_future_references(self):
        rows = [article('l', 'CENTER')]
        known = self.route(rows, [fact('Stare.', ['l'], kind='FACT')])
        facts = self.route(rows, [fact('Nowe A.', ['l'], kind='FACT'), fact('Nowe B.', ['l'], kind='FACT')], known)
        a, b = facts[-2:]
        for invalid in ('alien', a['fact_id'], b['fact_id']):
            with self.subTest(invalid=invalid):
                response = {'decisions': {
                    a['fact_id']: verdict('', [known[0]['fact_id'], known[0]['fact_id'], invalid]),
                    b['fact_id']: verdict(b['text_pl']),
                }}
                calls = []
                def call(*args):
                    calls.append(args[-1])
                    return copy.deepcopy(response)
                with self.assertRaisesRegex(ValueError, 'tylko previous_facts'):
                    p.audit_new_facts(facts, known, rows, call, ai.normalize_generated_text, 300000, None)
                self.assertEqual(calls, ['perspective_novelty_audit'] * 2)


if __name__ == '__main__':
    unittest.main()
