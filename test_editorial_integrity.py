"""Regression tests from the France, sanctions and Ukraine publication audit."""
import copy
import unittest
from unittest.mock import patch
import jsonschema
import ai_pipeline as ai
import perspective_summaries as p
import editorial_integrity as q
from test_topic_titles import FakeMergeClient


def article(aid, body, profile='CENTER'):
    return {'article_id': aid, 'source_id': aid, 'source_name': aid,
            'source_profile': profile, 'body_original': body, 'title_original': body,
            'published_at': '2026-10-21T04:00:00Z'}


def claim(text, aid, kind='FACT', attribution=''):
    return {'known_fact_id': '', 'text_pl': text, 'kind': kind, 'article_ids': [aid],
            'why_new_pl': 'Nowy szczegół z tego materiału.', 'evidence_quote': text,
            'attribution': attribution}


def extraction(data, specs):
    results = {}
    for a in data['all_articles']:
        aid = a['article_id']
        results[aid] = {'facts': [{k: v for k, v in f.items() if k != 'article_ids'}
                                 for f in specs if aid in f['article_ids']],
                        'no_relevant_facts_reason_pl': ''}
    return {'headline_pl': '[Francja] Protesty w Marsylii', 'categories': ['SWIAT'], 'article_results': results}


def writer(data):
    return {'paragraphs': [{'text_pl': f['text_pl'], 'fact_ids': [f['fact_id']], 'context_spans': []}
                           for f in data['main_facts'][:3]]}


class EditorialIntegrityTests(unittest.TestCase):
    def test_real_placeholder_fragments_and_uncertain_dates_are_not_publishable(self):
        for text in ['(Brak dodatkowych ustaleń)', 'i były ukierunkowane na zabezpieczenie polskiej przestrzeni powietrznej.',
                     'Atak nastąpił o 5:30 i 6:??.', 'Do lipca 202? trwały walki.', 'Dodał, że nastąpi zmiana.', 'Podkreśla, że nastąpi zmiana.']:
            self.assertFalse(q.usable_claim(text), text)
        self.assertTrue(q.usable_claim('Policja zatrzymała 8 osób w Marsylii.'))

    def test_foreign_quote_is_omitted_without_reading_article_again(self):
        rows = [article('a', 'Policja zatrzymała 8 osób w Marsylii.')]
        raw = extraction({'all_articles': rows}, [claim('Policja zatrzymała 10 osób w Marsylii.', 'a')])
        result, report = p.usable_extraction(raw, rows, rows, [], ai.normalize_generated_text, {})
        self.assertEqual(result['facts'], [])
        self.assertEqual(report['discarded_fact_count'], 1)

    def test_one_assessment_carried_by_left_and_right_is_one_card(self):
        rows = [article('l', 'Tekst', 'LEFT'), article('r', 'Tekst', 'RIGHT')]
        text = 'Analiza Le Monde wiąże zamieszki z przebudową systemu politycznego.'
        _, facts = p.route_facts({'facts': [claim(text, 'l', 'EDITORIAL', 'Le Monde'),
                                           claim(text, 'r', 'EDITORIAL', 'Le Monde')]}, rows, [], ai.normalize_generated_text)
        self.assertEqual(len(p.fact_sections(facts)['EDITORIAL']), 1)
        self.assertEqual(facts[0]['attribution'], 'Le Monde')
        self.assertEqual(set(facts[0]['article_ids']), {'l', 'r'})
        self.assertEqual(p.fact_sections(facts)['LEFT'], [])
        self.assertEqual(p.fact_sections(facts)['RIGHT'], [])

    def test_center_alone_is_not_multiple_sources(self):
        rows = {'a': article('a', 'Tekst')}
        self.assertFalse(p.shared_support({'article_ids': ['a']}, rows))

    def test_technical_merge_retains_originals_ledger_history_and_processed_ids(self):
        def stored(aid, text, uid):
            f = {'fact_id': aid, 'text_pl': text, 'kind': 'FACT', 'lane': 'COMMON', 'article_ids': [aid]}
            return {'base_summary': {'perspective_version': 1, 'summary_pl': text, 'perspective_facts': [f]},
                    'processed_article_ids': [aid], 'updates': [{'update_id': uid, 'generated_at': uid}],
                    'first_published_at': uid}
        left = stored('a', 'Policja zatrzymała 8 osób.', '2026-10-19')
        right = stored('b', 'Minister przyjedzie do Marsylii.', '2026-10-20')
        original = copy.deepcopy((left, right))
        merged = q.merge_publications(left, [('right', right)])
        self.assertEqual(len(merged['perspective_state']['perspective_facts']), 2)
        self.assertEqual(len(merged['updates']), 2)
        self.assertEqual(merged['processed_article_ids'], ['a', 'b'])
        self.assertTrue(merged['needs_narrative_refresh'])
        self.assertEqual(merged['base_summary'], left['base_summary'])
        self.assertEqual(q.merge_publications(merged, [('right', right)]), merged)
        self.assertEqual((left, right), original)

    def test_canonical_uses_first_publication_not_last_completed_request(self):
        topics = {'large': {'first_seen_at': '2026-10-19', 'article_count': 71},
                  'small': {'first_seen_at': '2026-10-21', 'article_count': 2}}
        rows = {'large': {'generated_at': '2026-10-21T04:27:58Z'}, 'small': {'generated_at': '2026-10-21T04:21:50Z'}}
        self.assertEqual(ai.choose_merge_canonical_topic_id(list(topics), topics,
            {t: {} for t in topics}, rows, True), 'large')

    def test_new_bridge_cannot_collapse_two_old_topics(self):
        groups = ai.build_anchored_embedding_groups(['old_a', 'new', 'old_b'],
            {('new', 'old_a'): .85, ('new', 'old_b'): .84}, focus_topic_ids={'new'})
        self.assertEqual(groups[0]['topic_ids'], ['new', 'old_a'])

    def test_broad_person_or_country_is_not_event_identity(self):
        topic = lambda title: {'headline_pl': title}
        self.assertFalse(ai.same_event_anchor(topic('[Świat] Trump wstrzymuje sankcje wobec Rosji'),
                                             topic('[Świat] Putin proponuje Trumpowi spotkanie z Xi')))
        self.assertFalse(ai.same_event_anchor(topic('[Ukraina] Rosyjski atak na Kijów'),
                                             topic('[Rosja] Ukraiński atak na Petersburg')))
        self.assertTrue(ai.same_event_anchor(topic('[Francja] Zakaz demonstracji w Marsylii'),
                                            topic('[Francja] Policja wprowadza zakaz demonstracji w Marsylii')))

    def test_new_article_only_and_durable_cache_avoid_second_full_read(self):
        text = 'Policja zatrzymała 8 osób w Marsylii.'
        rows = [article('old', text), article('new', text)]
        _, known = p.route_facts({'facts': [claim(text, 'old')]}, rows, [], ai.normalize_generated_text)
        base = {'perspective_version': 1, 'summary_pl': text, 'perspective_facts': known}
        payload = {'topic': {'topic_id': 't'}, 'all_articles': rows, 'new_article_ids': ['new'],
                   'extraction_model': 'fake', 'previous_aggregation': {'base_summary': base, 'processed_article_ids': ['old']}}
        sent, entries = [], []
        def call(instructions, data, schema, name):
            self.assertEqual(name, 'perspective_facts')
            sent.extend(a['article_id'] for a in data['all_articles'])
            return extraction(data, [claim(text, 'new')])
        result = p.generate(payload, call, ai.normalize_generated_text, allow_omissions=True, on_article_cache=entries.extend)
        self.assertEqual(sent, ['new'])
        self.assertEqual(result['update']['status'], 'NO_NEW_INFORMATION')
        result2 = p.generate({**payload, 'article_cache': {e['key']: e for e in entries}},
            lambda *args: self.fail('Cached article must not trigger a model call'), ai.normalize_generated_text, allow_omissions=True)
        self.assertEqual(result2['perspective_facts'], result['perspective_facts'])
        self.assertEqual(result2['quality_report']['cached_articles'], 1)
        changed = {**rows[1], 'body_original': text + ' Nowa treść.'}
        self.assertNotEqual(q.cache_key(changed, 'fake'), entries[0]['key'])

    def test_unrelated_duplicate_reference_cannot_erase_intelligence_claim(self):
        rows = [article('a', 'Tekst'), article('b', 'Tekst')]
        _, known = p.route_facts({'facts': [claim('Maszyna trafiła w obiekt energetyczny w obwodzie lwowskim.', 'a')]}, rows, [], ai.normalize_generated_text)
        _, facts = p.route_facts({'facts': [claim('Rubio zaprzeczył wstrzymaniu informacji wywiadowczych dla Ukrainy.', 'b')]}, rows, known, ai.normalize_generated_text)
        calls = []
        def call(instructions, data, schema, name):
            calls.append(name)
            return {'decisions': {'C1': {'decision': 'DUPLICATE', 'new_text_pl': '',
                'covered_fact_ids': ['K1'], 'reason_pl': 'Powtórzenie wcześniejszego faktu.'}}}
        result, audits, omitted = p.audit_claims_once(facts, known, rows, call, ai.normalize_generated_text, 300000)
        self.assertEqual(result, known)
        self.assertEqual(len(omitted), 1)
        self.assertEqual(audits[0]['decisions'][facts[-1]['fact_id']]['status'], 'OMITTED')
        self.assertEqual(len(calls), 1)

    def test_valid_duplicate_unions_evidence_without_new_timeline_item(self):
        rows = [article('a', 'Tekst', 'LEFT'), article('b', 'Tekst', 'RIGHT')]
        _, known = p.route_facts({'facts': [claim('Policja zatrzymała 8 osób w Marsylii.', 'a')]}, rows, [], ai.normalize_generated_text)
        _, facts = p.route_facts({'facts': [claim('W Marsylii policja zatrzymała 8 osób.', 'b')]}, rows, known, ai.normalize_generated_text)
        def call(*args):
            return {'decisions': {'C1': {'decision': 'DUPLICATE', 'new_text_pl': '', 'covered_fact_ids': ['K1'], 'reason_pl': 'Ta sama liczba, miejsce i czynność.'}}}
        result, _, omitted = p.audit_claims_once(facts, known, rows, call, ai.normalize_generated_text, 300000)
        self.assertFalse(omitted)
        self.assertEqual(result[0]['article_ids'], ['a', 'b'])
        self.assertEqual(p.make_update(result, known, True, ['b'], {a['article_id']: a for a in rows})['status'], 'NO_NEW_INFORMATION')
        self.assertFalse(q.compatible_duplicate('Zatrzymano 8 osób w Marsylii.', 'Zatrzymano 10 osób w Marsylii.'))

    def test_current_narrative_updates_once_and_context_can_be_empty(self):
        old = 'Policja zatrzymała 8 osób w Marsylii.'
        new = 'Minister przyjedzie do Marsylii w poniedziałek.'
        rows = [article('a', old), article('b', new)]
        _, known = p.route_facts({'facts': [claim(old, 'a')]}, rows, [], ai.normalize_generated_text)
        base = {'perspective_version': 1, 'summary_pl': old, 'perspective_facts': known}
        payload = {'topic': {'working_title_pl': '[Francja] Protesty w Marsylii'}, 'all_articles': rows, 'new_article_ids': ['b'],
                   'previous_aggregation': {'base_summary': base, 'processed_article_ids': ['a']}}
        calls = []
        def request(instructions, data, model, **settings):
            name = settings['response_schema_name']; calls.append(name)
            if name == 'perspective_facts': result = extraction(data, [claim(new, 'b')])
            elif name == 'perspective_novelty_audit':
                result = {'decisions': {f['fact_id']: {'decision': 'NEW', 'new_detail_pl': '', 'covered_fact_ids': [], 'reason_pl': 'Nowa wizyta ministra.'} for f in data['candidate_facts']}}
            else: result = writer(data)
            jsonschema.validate(result, settings['response_schema'])
            self.assertEqual(settings['retry_limit'], 1)
            return result
        with patch.object(ai, 'call_openai', side_effect=request), patch.object(ai, 'log'):
            result = ai.generate_summary_response(payload, 'gpt-5-nano')
        self.assertEqual(calls.count('perspective_summary'), 1)
        self.assertIn(new, result['summary_pl'])
        self.assertEqual(result['background_context'], [])
        client = FakeMergeClient([], [], [])
        ai.persist_summary(client, topic_id='t', run_id='r', model='fake', summary=result,
                           summary_hash='h', previous_row={'version': 1, 'summary': {'base_summary': base}}, new_article_ids=['b'])
        saved = next(rows[0]['summary'] for table, rows, _ in client.upserts if table == 'topic_summaries')
        self.assertEqual(saved['base_summary'], base)
        self.assertIn(new, saved['current_summary']['summary_pl'])
        self.assertEqual(len(saved['updates']), 1)

    def test_wrong_paragraph_and_unverified_context_are_omitted_locally(self):
        main = [{'fact_id': 'f', 'text_pl': 'Policja zatrzymała 8 osób w Marsylii.', 'article_ids': ['a']}]
        result = p.safe_written({'paragraphs': [{'text_pl': 'Rubio zaprzeczył wstrzymaniu informacji wywiadowczych.', 'fact_ids': ['f']}],
            'general_context': {'text_pl': 'Minister był prefektem policji.', 'article_ids': ['a'], 'needs_verification': True}}, main)
        self.assertEqual(result['paragraphs'], [])
        self.assertEqual(result['background_context'], [])

    def test_normalization_preserves_quotes_and_attribution(self):
        item = {'text_pl': 'Le Monde ocenia decyzję jako ryzykowną.', 'kind': 'EDITORIAL',
                'article_ids': ['a'], 'attribution': 'Le Monde', 'evidence': {'a': {'quote': 'Texte original'}}}
        normalized = ai.normalize_summary_response({'facts': [item]})['facts'][0]
        self.assertEqual(normalized['evidence'], item['evidence'])
        self.assertEqual(normalized['attribution'], 'Le Monde')

if __name__ == '__main__':
    unittest.main()
