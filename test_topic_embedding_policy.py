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
        vectors=[[1.,0.],[.80,(1-.80**2)**.5]]
        self.assertEqual(ai.build_embedding_candidate_edges(['a','b'],vectors),{})
        self.assertEqual(ai.build_embedding_candidate_edges(['a','b'],vectors,ukraine_ids={'a'}),{})
        report={}
        edges=ai.build_embedding_candidate_edges(['a','b'],vectors,ukraine_ids={'a','b'},diagnostics=report)
        self.assertEqual(set(edges),{('a','b')})
        sample=report['samples'][0]
        self.assertEqual(sample['threshold'],.78)
        self.assertEqual(sample['threshold_policy'],'UKRAINE')
        self.assertEqual(sample['bucket'],'SELECTED_NEAR_THRESHOLD')
        self.assertEqual(report['score_band_samples'][0]['threshold'],.78)

    def test_anchor_group_uses_same_pair_threshold_not_global_floor(self):
        edges={('a','b'):.90,('a','c'):.80,('b','d'):.80,('c','e'):.90}
        groups=ai.build_anchored_embedding_groups(list('abcde'),edges,ukraine_ids={'a','b','c'})
        self.assertEqual(groups[0]['topic_ids'],['a','b','c'])
        self.assertNotIn('d',groups[0]['topic_ids'])
        self.assertNotIn('e',groups[0]['topic_ids'])
        self.assertAlmostEqual(groups[0]['minimum_anchor_similarity'],.80)

    def test_background_entity_type_controls_label_with_legacy_compatibility(self):
        row=ai.normalize_summary_response({'background_context':[{'entity_type':'PERSON','text_pl':'Organizacja — Donald Trump: polityk.','article_ids':[],'needs_verification':True}]})
        self.assertEqual(row['background_context'][0]['text_pl'],'Osoba — Donald Trump: polityk.')
        legacy=ai.normalize_summary_response({'background_context':[{'text_pl':'Dawny wpis','article_ids':[]}]})
        self.assertEqual(legacy['background_context'][0]['text_pl'],'Dawny wpis')
        schema=ai.SUMMARY_RESPONSE_SCHEMA['properties']['background_context']['items']
        self.assertIn('entity_type',schema['required'])

if __name__=='__main__':unittest.main()
