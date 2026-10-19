import copy
import json
import unittest
from unittest.mock import patch
import ai_pipeline as ai
import perspective_summaries as p
from test_ai_input_optimization import article
from test_perspective_summaries import fact, extraction


class FullArticleBatchTests(unittest.TestCase):
    def test_builder_never_removes_or_shortens_bodies_for_large_inputs(self):
        rows=[article('a'),article('b')]
        with patch.object(ai,'SUMMARY_MAX_PAYLOAD_CHARS',100):
            for all_rows in (None,rows):
                with self.subTest(all_rows=bool(all_rows)):
                    payload,size,mode=ai.build_bounded_summary_input({'topic':{}},rows,all_rows)
                    sent=payload['all_articles' if all_rows else 'new_articles']
                    self.assertEqual([a['body_original'] for a in sent],[a['body'] for a in rows])
                    self.assertGreater(size,100)
                    self.assertIn('bez skracania',mode)
                    self.assertTrue(all('body_excerpt_original' not in a for a in sent))

    def test_batching_preserves_order_full_text_and_oversized_single_article(self):
        rows=[{'article_id':'a','body_original':'A'*1000},{'article_id':'b','body_original':'B'*100},{'article_id':'c','body_original':'C'*100}]
        original=copy.deepcopy(rows)
        start=0;batches=[]
        while start<len(rows):
            batch,start=p.take_full_article_batch(rows,start,{},'all_articles',400)
            batches.append(batch)
        self.assertEqual([len(b) for b in batches],[1,2])
        self.assertEqual([r for b in batches for r in b],original)
        self.assertEqual(rows,original)

    def test_new_format_reads_all_full_bodies_and_recognizes_cross_batch_support(self):
        rows=[{**ai.article_for_ai(article(key)),'source_profile':profile} for key,profile in [('a','LEFT'),('b','RIGHT'),('c','CENTER')]]
        payload={'topic':{},'all_articles':rows,'new_article_ids':['a','b','c']}
        original=copy.deepcopy(payload);seen=[];writer=[]
        def call(instructions,data,schema,name):
            if name=='perspective_facts':
                self.assertEqual(len(data['all_articles']),1)
                current=data['all_articles'][0];seen.append(current)
                self.assertEqual(current['body_original'],next(a for a in rows if a['article_id']==current['article_id'])['body_original'])
                known=data['previous_facts']
                return extraction([fact('Ten sam fakt.',[current['article_id']],known[0]['fact_id'] if known else '',reason='' if known else 'Pierwsze ustalenie.')],data['all_articles'])
            writer.append(data)
            self.assertEqual(len(data['main_facts']),1)
            self.assertEqual(data['main_facts'][0]['article_ids'],['a','b','c'])
            return {'paragraphs':[{'text_pl':'Ten sam fakt.','fact_ids':[data['main_facts'][0]['fact_id']]}],'general_context':{'text_pl':'Tło.','article_ids':[]},'background_context':[]}
        result=p.generate(payload,call,ai.normalize_generated_text,max_payload_chars=100)
        self.assertEqual(len(seen),3);self.assertEqual(len(writer),1)
        self.assertEqual(len(result['perspective_facts']),1)
        self.assertTrue(result['shared_available'])
        self.assertEqual(payload,original)

    def test_batch_cannot_add_support_from_an_article_not_yet_sent(self):
        with self.assertRaisesRegex(ValueError,'spoza bieżącej paczki'):
            p.validate_batch_citations({'facts':[fact('Fakt.',['not-sent'])]},[{'article_id':'sent'}],[],ai.normalize_generated_text)

    def test_legacy_batches_get_previous_batch_updates_without_audits(self):
        rows=[ai.article_for_ai(article(key)) for key in ['a','b']]
        original={'topic':{},'new_articles':rows,'previous_aggregation':{'base_summary':{'summary_pl':'Pierwotna synteza.'},'prior_updates':[]}}
        saved=copy.deepcopy(original);calls=[]
        def generate(payload,model):
            calls.append(copy.deepcopy(payload))
            a=payload['new_articles'][0]
            if a['article_id']=='a':
                return ai.normalize_summary_response({'summary_pl':'Pierwotna synteza.','update':{'status':'NEW_INFORMATION','new_information_pl':'Nowy fakt.','new_article_ids':['a'],'novelty_audit':{'dummy':True}}})
            self.assertEqual(payload['previous_aggregation']['prior_updates'][0]['new_information_pl'],'Nowy fakt.')
            self.assertNotIn('novelty_audit',payload['previous_aggregation']['prior_updates'][0])
            return ai.normalize_summary_response({'summary_pl':'Pierwotna synteza.','update':{'status':'NO_NEW_INFORMATION','new_article_ids':['b']}})
        with patch.object(ai,'SUMMARY_MAX_PAYLOAD_CHARS',100),patch.object(ai,'generate_topic_update',side_effect=generate),patch.object(ai,'log'):
            result=ai.generate_summary_response(original,'fake')
        self.assertEqual(len(calls),2)
        self.assertEqual([c['new_articles'][0]['body_original'] for c in calls],[a['body_original'] for a in rows])
        self.assertEqual(result['update']['new_information_pl'],'Nowy fakt.')
        self.assertEqual(result['update']['new_article_ids'],['a','b'])
        self.assertEqual(result['summary_pl'],'Pierwotna synteza.')
        self.assertEqual(original,saved)

    def test_failed_later_batch_does_not_return_a_partial_summary(self):
        payload={'topic':{},'all_articles':[{'article_id':'a','source_profile':'LEFT','body_original':'A'*200},{'article_id':'b','source_profile':'RIGHT','body_original':'B'*200}]}
        calls=[]
        def call(instructions,data,schema,name):
            calls.append(name)
            if len(calls)==2:raise RuntimeError('context limit')
            return extraction([fact('Fakt.',['a'])],data['all_articles'])
        with self.assertRaisesRegex(RuntimeError,'context limit'):
            p.generate(payload,call,ai.normalize_generated_text,max_payload_chars=100)
        self.assertEqual(calls,['perspective_facts','perspective_facts'])


if __name__=='__main__':unittest.main()
