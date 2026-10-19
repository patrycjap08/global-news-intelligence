import unittest
import ai_pipeline as ai

class TopicPolicyTests(unittest.TestCase):
    def test_ukraine_classifier_and_negative_cases(self):
        for topic in [dict(headline_pl='[Ukraina] Pomoc dla gospodarki'),
                      dict(headline_pl='Ukraine aid'),dict(headline_pl='Україна: переговори'),
                      dict(headline_pl='[Świat] Russian missile attack on Kharkiv'),
                      dict(headline_pl='[Świat] Atak rakietowy na Charków')]:
            self.assertTrue(ai.is_ukraine_topic(topic),topic)
        for title in ['[Rosja] Zmiana podatków','[Świat] Wojna w Gazie','[USA] Pomoc dla NATO','[Świat] Targi w Kijowie']:
            self.assertFalse(ai.is_ukraine_topic(dict(headline_pl=title)),title)
        self.assertTrue(ai.is_ukraine_topic(dict(headline_pl='Nowe wsparcie',recent_article_titles=['Aid for Ukraine'])))

    def test_pair_thresholds_and_diagnostics(self):
        self.assertEqual(ai.TOPIC_MERGE_EMBEDDING_MIN_SIMILARITY, .78)
        for ukraine_ids in (None, {'a'}, {'a', 'b'}):
            for score in (.779999, .78, .80):
                with self.subTest(ukraine_ids=ukraine_ids, score=score):
                    vectors = [[1., 0.], [score, (1-score**2)**.5]]
                    report = {}
                    edges = ai.build_embedding_candidate_edges(
                        ['a', 'b'], vectors, ukraine_ids=ukraine_ids, diagnostics=report)
                    self.assertEqual(set(edges), {('a', 'b')} if score >= .78 else set())
                    sample = report['samples'][0]
                    self.assertEqual(sample['threshold'], .78)
                    self.assertEqual(sample['threshold_policy'], 'UNIFORM')
                    self.assertEqual(sample['bucket'], 'SELECTED_NEAR_THRESHOLD' if score >= .78 else 'BELOW_THRESHOLD')
                    self.assertEqual(report['score_band_samples'][0]['threshold'], .78)
                    self.assertEqual(report['ukraine_threshold'], report['threshold'])

    def test_anchor_groups_use_uniform_threshold_and_keep_fixed_anchors(self):
        edges = {('a','b'):.90, ('a','c'):.78, ('b','d'):.78, ('c','e'):.88, ('b','f'):.779999}
        for ukraine_ids in (None, {'a'}, {'a', 'b', 'c'}):
            with self.subTest(ukraine_ids=ukraine_ids):
                groups = ai.build_anchored_embedding_groups(list('abcdef'), edges, ukraine_ids=ukraine_ids)
                self.assertEqual(groups[0]['topic_ids'], ['a', 'b', 'c', 'd'])
                self.assertNotIn('e', groups[0]['topic_ids'])
                self.assertNotIn('f', groups[0]['topic_ids'])
                self.assertAlmostEqual(groups[0]['minimum_anchor_similarity'], .78)

    def test_diagnostic_simulations_apply_selected_threshold_to_every_topic(self):
        self.assertEqual(ai.embedding_pair_threshold('a', 'b', .85, {'a', 'b'}), .85)
        self.assertEqual(ai.embedding_pair_threshold('a', 'b', .75, {'a', 'b'}), .75)

    def test_background_entity_type_controls_label_with_legacy_compatibility(self):
        row=ai.normalize_summary_response({'background_context':[{'entity_type':'PERSON','text_pl':'Organizacja — Donald Trump: polityk.','article_ids':[],'needs_verification':True}]})
        self.assertEqual(row['background_context'][0]['text_pl'],'Osoba — Donald Trump: polityk.')
        legacy=ai.normalize_summary_response({'background_context':[{'text_pl':'Dawny wpis','article_ids':[]}]})
        self.assertEqual(legacy['background_context'][0]['text_pl'],'Dawny wpis')
        schema=ai.SUMMARY_RESPONSE_SCHEMA['properties']['background_context']['items']
        self.assertIn('entity_type',schema['required'])

if __name__=='__main__':unittest.main()
