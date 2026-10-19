import copy
import unittest
from unittest.mock import patch
import ai_pipeline as ai
import perspective_summaries as p
from test_topic_titles import FakeMergeClient


def article(key, group):
    return {'article_id': key, 'source_id': key, 'source_profile': group}


def fact(text, ids, known='', reason='Nowa decyzja.'):
    return {'text_pl':text, 'article_ids':ids, 'known_fact_id':known, 'why_new_pl':reason}


class PerspectiveTests(unittest.TestCase):
    def route(self, rows, facts, known=()):
        return p.route_facts({'facts':facts},rows,list(known),ai.normalize_generated_text)

    def test_profiles_and_public_agencies(self):
        self.assertEqual(p.article_group({**article('pap','CENTER'),'source_type':'GOVERNMENT_AGENCY'}),'CENTER')
        self.assertEqual(p.article_group(article('tv','CENTER_LEFT')),'LEFT')
        self.assertEqual(p.article_group(article('tv','CENTER_RIGHT')),'RIGHT')
        self.assertEqual(p.article_group({**article('x','CENTER'),'source_type':'STATE_MEDIA'}),'STATE')
        with self.assertRaises(ValueError):p.article_group(article('x','UNCLASSIFIED'))

    def test_mixed_routing_center_always_common_and_state_not_confirmation(self):
        rows=[article('l','LEFT'),article('r','RIGHT'),article('c','CENTER'),article('s','STATE_ALIGNED')]
        mode, facts=self.route(rows,[fact('Obie strony.',['l','r']),fact('Centrum.',['c']),fact('Tylko lewica.',['l','s']),fact('Tylko prawica.',['r']),fact('Według TASS: komunikat.',['s'])])
        self.assertEqual(mode,'MIXED')
        self.assertEqual([f['lane'] for f in facts],['COMMON','COMMON','LEFT','RIGHT','STATE'])

    def test_single_profile_exception_even_with_state_sources(self):
        for profile in ['LEFT','RIGHT','CENTER']:
            mode,facts=self.route([article('a',profile),article('s','STATE_ALIGNED')],[fact('Informacja.',['a']),fact('Według TASS: komunikat.',['s'])])
            self.assertEqual(mode,'SINGLE_'+profile)
            self.assertEqual([f['lane'] for f in facts],['COMMON','STATE'])

    def test_state_only_and_no_common(self):
        mode,facts=self.route([article('s','STATE_ALIGNED')],[fact('Według TASS: komunikat.',['s'])])
        self.assertEqual(mode,'STATE_ONLY');self.assertEqual(facts[0]['lane'],'STATE')
        _,facts=self.route([article('l','LEFT'),article('r','RIGHT')],[fact('A.',['l']),fact('B.',['r'])])
        self.assertFalse(any(f['lane']=='COMMON' for f in facts))

    def test_confirmations_promotions_and_new_perspective_updates(self):
        rows=[article('l','LEFT'),article('r','RIGHT')]
        _,known=self.route(rows,[fact('Znana decyzja.',['l'])])
        fid=known[0]['fact_id']
        # Omitted old facts remain; no-change response never deletes knowledge.
        _,same=self.route(rows,[],known)
        self.assertEqual(p.make_update(same,known,True,['r'])['status'],'NO_NEW_INFORMATION')
        _,promoted=self.route(rows,[fact('Znana decyzja.',['r'],fid,reason='')],known)
        update=p.make_update(promoted,known,True,['r'])
        self.assertEqual(update['status'],'NEW_INFORMATION')
        self.assertEqual(len(update['promoted_facts']),1)
        self.assertFalse(any(update['perspective_sections'].values()))
        _,again=self.route(rows,[fact('Znana decyzja.',['r'],fid,reason='')],promoted)
        self.assertEqual(p.make_update(again,promoted,True,['r'])['status'],'NO_NEW_INFORMATION')
        _,new=self.route(rows,[fact('Nowa decyzja.',['r'])],promoted)
        self.assertEqual(len(p.make_update(new,promoted,True,['r'])['perspective_sections']['RIGHT']),1)

    def test_invalid_evidence_known_id_or_changed_known_text_fail(self):
        rows=[article('l','LEFT'),article('r','RIGHT')]
        _,known=self.route(rows,[fact('Znany fakt.',['l'])])
        for raw in [fact('A.',['alien']),fact('A.',[]),fact('Zmieniony.',['l'],known[0]['fact_id']),fact('Znany fakt.',['r'],'alien'),fact('Nowy.',['r'],reason='')]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):self.route(rows,[raw],known)

    def test_generation_is_two_bounded_calls_and_writer_sees_only_common_facts(self):
        payload={'topic':{},'all_articles':[article('l','LEFT'),article('r','RIGHT')],'new_article_ids':['l','r']}
        calls=[]
        def call(instructions,data,schema,name):
            calls.append((name,data))
            if name=='perspective_facts':return {'headline_pl':'[Polska] Decyzja','categories':['POLSKA'],'facts':[fact('Wspólne.',['l','r']),fact('Wyłącznie lewica.',['l'])]}
            self.assertEqual([f['text_pl'] for f in data['main_facts']],['Wspólne.'])
            return {'paragraphs':[{'text_pl':'Wspólne.','fact_ids':[data['main_facts'][0]['fact_id']]}], 'general_context':{'text_pl':'Ogólne tło.','article_ids':[],'needs_verification':True},'background_context':[]}
        result=p.generate(payload,call,ai.normalize_generated_text)
        self.assertEqual(len(calls),2);self.assertEqual(len(result['facts']),1)
        self.assertEqual(result['perspective_sections']['LEFT'][0]['text_pl'],'Wyłącznie lewica.')
        self.assertEqual(ai.normalize_summary_response(result)['perspective_facts'],result['perspective_facts'])

    def test_writer_cannot_cite_exclusive_fact_or_context_source(self):
        payload={'topic':{},'all_articles':[article('l','LEFT'),article('r','RIGHT')]}
        def call(instructions,data,schema,name):
            if name=='perspective_facts':return {'headline_pl':'[Polska] Decyzja','facts':[fact('Lewica.',['l']),fact('Prawica.',['r'])]}
            return {'paragraphs':[{'text_pl':'Nie wolno.','fact_ids':['alien']}], 'general_context':{'text_pl':'Tło.','article_ids':[]},'background_context':[]}
        with self.assertRaises(ValueError):p.generate(payload,call,ai.normalize_generated_text)

    def test_persistence_refreshes_current_state_keeps_history_and_no_change(self):
        _,known=self.route([article('l','LEFT'),article('r','RIGHT')],[fact('Znana decyzja.',['l'])])
        _,promoted=self.route([article('l','LEFT'),article('r','RIGHT')],[fact('Znana decyzja.',['r'],known[0]['fact_id'])],known)
        update=p.make_update(promoted,known,True,['r'])
        summary={'perspective_version':1,'coverage_mode':'MIXED','shared_available':True,'perspective_facts':promoted,'perspective_sections':{'LEFT':[],'RIGHT':[],'STATE':[]},'summary_pl':'Znana decyzja.','facts':promoted,'topic':{},'update':update}
        old={'version':1,'summary':{'base_summary':{'perspective_version':1,'perspective_facts':known},'updates':[]}}
        client=FakeMergeClient([],[],[])
        ai.persist_summary(client,topic_id='t',run_id='r',model='fake',summary=summary,summary_hash='h',previous_row=old,new_article_ids=['r'])
        saved=[rows[0] for table,rows,_ in client.upserts if table=='topic_summaries'][-1]
        self.assertEqual(saved['summary']['base_summary']['facts'],promoted)
        self.assertEqual(len(saved['summary']['updates']),1)
        self.assertEqual(len(saved['summary']['updates'][0]['promoted_facts']),1)
        # Retry/confirming analysis records progress without another update.
        summary=copy.deepcopy(summary);summary['update']=p.make_update(promoted,promoted,True,['r'])
        ai.persist_summary(client,topic_id='t',run_id='r2',model='fake',summary=summary,summary_hash='h2',previous_row=saved,new_article_ids=['r'])
        self.assertEqual(len([rows[0] for table,rows,_ in client.upserts if table=='topic_summaries'][-1]['summary']['updates']),1)

    def test_matching_pool_excludes_all_legacy_topics_including_candidates(self):
        new_id=ai.stable_topic_id(['a'],'Tytuł')
        self.assertTrue(new_id.startswith('topic_perspectives_'))
        client=FakeMergeClient([{'topic_id':'legacy'},{'topic_id':'legacy_candidate'},{'topic_id':new_id}],[],[{'topic_id':'legacy','summary':{'base_summary':{'summary_pl':'Stara synteza'}}}])
        payload,_,_=ai.active_topic_payload(client,new_generation_only=True)
        self.assertEqual([t['topic_id'] for t in payload],[new_id])

    def test_final_merge_checks_all_synthesized_topics_but_never_crosses_versions(self):
        import os
        from pathlib import Path
        from tempfile import TemporaryDirectory
        ids=['legacy_a','legacy_b',ai.stable_topic_id(['a'],'Nowy'),ai.stable_topic_id(['b'],'Nowy'),ai.stable_topic_id(['c'],'Kandydat')]
        topics=[{'topic_id':tid,'headline_pl':'[Polska] Ten sam protest','status':'ACTIVE','first_seen_at':'2026-10-19T00:00:00Z','last_seen_at':'2026-10-19T12:00:00Z'} for tid in ids]
        summaries=[{'topic_id':tid,'summary':{'base_summary':{'summary_pl':'Protest.',**({'perspective_version':1} if index>1 else {})}}} for index,tid in enumerate(ids[:4])]
        client=FakeMergeClient(topics,[{'topic_id':tid,'article_id':str(index)} for index,tid in enumerate(ids)],summaries)
        seen=[]
        def embeddings(topics,**kwargs):
            seen.extend(t['topic_id'] for t in topics)
            # The strongest possible edge deliberately crosses generations.
            return {(ids[0],ids[2]):.999,(ids[0],ids[1]):.90,(ids[2],ids[3]):.91}
        with TemporaryDirectory() as folder,patch.dict(os.environ,{'OPENAI_API_KEY':'test'}),patch.object(ai,'local_articles',side_effect=lambda conn,keys:[{'article_id':key,'source_id':key,'source_profile':'CENTER','title':'Nagłówek'} for key in keys]),patch.object(ai,'build_topic_embedding_candidate_edges',side_effect=embeddings),patch.object(ai,'call_openai',side_effect=AssertionError('No AI merge approval')),patch.object(ai,'log'):
            stats=ai.merge_active_topics(Path(folder)/'db','r',client,prefer_embeddings=True,existing_summaries_only=True)
        self.assertEqual(set(seen),set(ids[:4]))
        self.assertEqual(stats['semantic_candidate_edges'],2)
        saved_topics=[rows[0] for table,rows,_ in client.upserts if table=='topics']
        self.assertEqual(len(saved_topics),2)
        self.assertEqual({ai.topic_generation(t['topic_id']) for t in saved_topics},{'legacy','perspectives'})


if __name__=='__main__':unittest.main()
