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


def extraction(facts, articles, **metadata):
    return {'headline_pl':'[Polska] Decyzja', 'categories':['POLSKA'], **metadata,
            'facts':facts, 'article_coverage':[
                {'article_id':a['article_id'],
                 'fact_indexes':[i for i,f in enumerate(facts) if a['article_id'] in f['article_ids']],
                 'no_relevant_facts_reason_pl':'' if any(a['article_id'] in f['article_ids'] for f in facts)
                    else 'Materiał spoza wydarzenia testowego.'}
                for a in articles]}


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

    def test_article_coverage_rejects_omissions_and_inconsistent_evidence(self):
        rows=[article('l','LEFT'),article('r','RIGHT')]
        valid=extraction([fact('Wspólne.',['l','r'])],rows)
        p.validate_article_coverage(valid,rows)
        malformed=[]
        missing=copy.deepcopy(valid);missing.pop('article_coverage');malformed.append(missing)
        missing=copy.deepcopy(valid);missing['article_coverage'].pop();malformed.append(missing)
        duplicate=copy.deepcopy(valid);duplicate['article_coverage'].append(duplicate['article_coverage'][0]);malformed.append(duplicate)
        alien=copy.deepcopy(valid);alien['article_coverage'][0]['article_id']='alien';malformed.append(alien)
        for indexes in ([1],[-1],[True],[0,0],[],['0']):
            wrong=copy.deepcopy(valid);wrong['article_coverage'][0]['fact_indexes']=indexes;malformed.append(wrong)
        unsupported=copy.deepcopy(valid);unsupported['facts'][0]['article_ids']=['r'];malformed.append(unsupported)
        excuse=copy.deepcopy(valid);excuse['article_coverage'][0]['no_relevant_facts_reason_pl']='Brak informacji.';malformed.append(excuse)
        for response in malformed:
            with self.subTest(response=response),self.assertRaises(ValueError):
                p.validate_article_coverage(response,rows)

    def test_coverage_allows_real_repetition_and_explained_off_topic_articles(self):
        rows=[article(str(i),'CENTER') for i in range(7)]
        # Seven copies can support one fact: no made-up minimum fact count.
        repeated=extraction([fact('Jedna informacja.',[a['article_id'] for a in rows])],rows)
        p.validate_article_coverage(repeated,rows)
        off_topic=extraction([],rows)
        p.validate_article_coverage(off_topic,rows)
        off_topic['article_coverage'][0]['no_relevant_facts_reason_pl']=''
        with self.assertRaises(ValueError):p.validate_article_coverage(off_topic,rows)

    def test_missing_article_coverage_never_reaches_writer(self):
        calls=[]
        def call(instructions,data,schema,name):
            calls.append(name)
            return {'headline_pl':'[Polska] Decyzja','facts':[fact('Fakt.',['l'])],
                    'article_coverage':[{'article_id':'l','fact_indexes':[0],'no_relevant_facts_reason_pl':''}]}
        with self.assertRaisesRegex(ValueError,'pominęła artykuły'):
            p.generate({'topic':{},'all_articles':[article('l','LEFT'),article('r','RIGHT')]},call,ai.normalize_generated_text)
        self.assertEqual(calls,['perspective_facts'])

    def test_atomic_decisions_and_distinct_count_scopes_keep_their_own_support(self):
        rows=[article('l','LEFT'),article('r','RIGHT'),article('c','CENTER')]
        _,facts=self.route(rows,[
            fact('Minister złożył dymisję.',['l','r']),
            fact('Prezydent odmówił przyjęcia dymisji.',['l','r','c']),
            fact('Minister zapowiedział reformę.',['l']),
            fact('Według agencji zatrzymano osiem osób po ataku na konwój.',['c']),
            fact('Według dziennika zatrzymano dziesięć osób w związku z dwoma atakami.',['r']),
        ])
        self.assertEqual([f['lane'] for f in facts],['COMMON','COMMON','LEFT','COMMON','RIGHT'])
        self.assertEqual([f['article_ids'] for f in facts],[['l','r'],['l','r','c'],['l'],['c'],['r']])

    def test_writer_gets_attribution_metadata_only_for_admitted_facts(self):
        rows=[{**article('l','LEFT'),'source_name':'Lewica'},
              {**article('r','RIGHT'),'source_name':'Prawica'},
              {**article('x','LEFT'),'source_name':'Tylko perspektywa'}]
        calls=[]
        def call(instructions,data,schema,name):
            calls.append(name)
            if name=='perspective_facts':
                return extraction([fact('Wspólne.',['l','r']),fact('Tylko lewica.',['x'])],data['all_articles'])
            self.assertEqual(data['main_sources'],[
                {'article_id':'l','source_name':'Lewica','published_at':None},
                {'article_id':'r','source_name':'Prawica','published_at':None}])
            self.assertNotIn('all_articles',data)
            return {'paragraphs':[{'text_pl':'Wspólne.','fact_ids':[data['main_facts'][0]['fact_id']]}],
                    'general_context':{'text_pl':'Tło.','article_ids':[]},'background_context':[]}
        p.generate({'topic':{},'all_articles':rows},call,ai.normalize_generated_text)
        self.assertEqual(calls,['perspective_facts','perspective_summary'])

    def test_generation_is_two_bounded_calls_and_writer_sees_only_common_facts(self):
        payload={'topic':{},'all_articles':[article('l','LEFT'),article('r','RIGHT')],'new_article_ids':['l','r']}
        calls=[]
        def call(instructions,data,schema,name):
            calls.append((name,data))
            if name=='perspective_facts':return extraction([fact('Wspólne.',['l','r']),fact('Wyłącznie lewica.',['l'])],data['all_articles'])
            self.assertEqual([f['text_pl'] for f in data['main_facts']],['Wspólne.'])
            return {'paragraphs':[{'text_pl':'Wspólne.','fact_ids':[data['main_facts'][0]['fact_id']]}], 'general_context':{'text_pl':'Ogólne tło.','article_ids':[],'needs_verification':True},'background_context':[]}
        result=p.generate(payload,call,ai.normalize_generated_text)
        self.assertEqual(len(calls),2);self.assertEqual(len(result['facts']),1)
        self.assertEqual(result['perspective_sections']['LEFT'][0]['text_pl'],'Wyłącznie lewica.')
        self.assertEqual(ai.normalize_summary_response(result)['perspective_facts'],result['perspective_facts'])

    def test_writer_cannot_cite_exclusive_fact_or_context_source(self):
        payload={'topic':{},'all_articles':[article('l','LEFT'),article('r','RIGHT')]}
        def call(instructions,data,schema,name):
            if name=='perspective_facts':return extraction([fact('Lewica.',['l']),fact('Prawica.',['r'])],data['all_articles'])
            return {'paragraphs':[{'text_pl':'Nie wolno.','fact_ids':['alien']}], 'general_context':{'text_pl':'Tło.','article_ids':[]},'background_context':[]}
        with self.assertRaises(ValueError):p.generate(payload,call,ai.normalize_generated_text)

    def test_persistence_refreshes_current_state_keeps_history_and_no_change(self):
        _,known=self.route([article('l','LEFT'),article('r','RIGHT')],[fact('Znana decyzja.',['l'])])
        _,promoted=self.route([article('l','LEFT'),article('r','RIGHT')],[fact('Znana decyzja.',['r'],known[0]['fact_id'])],known)
        update=p.make_update(promoted,known,True,['r'])
        summary={'perspective_version':1,'coverage_mode':'MIXED','shared_available':True,'perspective_facts':promoted,'perspective_sections':{'LEFT':[],'RIGHT':[],'STATE':[]},'summary_pl':'Znana decyzja.','facts':promoted,'topic':{},'update':update}
        old={'version':1,'summary':{'base_summary':{'perspective_version':1,'coverage_mode':'MIXED','summary_pl':'Pierwotna synteza.','background_context':[{'text_pl':'Pierwotny kontekst.'}],'perspective_facts':known,'facts':[]},'updates':[]}}
        client=FakeMergeClient([],[],[])
        ai.persist_summary(client,topic_id='t',run_id='r',model='fake',summary=summary,summary_hash='h',previous_row=old,new_article_ids=['r'])
        saved=[rows[0] for table,rows,_ in client.upserts if table=='topic_summaries'][-1]
        self.assertEqual(saved['summary']['base_summary'],old['summary']['base_summary'])
        self.assertEqual(saved['summary']['perspective_state']['facts'],promoted)
        self.assertEqual(ai.previous_aggregation_context(saved['summary'])['perspective_state']['perspective_facts'],promoted)
        self.assertEqual(len(saved['summary']['updates']),1)
        self.assertEqual(len(saved['summary']['updates'][0]['promoted_facts']),1)
        # Retry/confirming analysis records progress without another update.
        summary=copy.deepcopy(summary);summary['update']=p.make_update(promoted,promoted,True,['r'])
        ai.persist_summary(client,topic_id='t',run_id='r2',model='fake',summary=summary,summary_hash='h2',previous_row=saved,new_article_ids=['r'])
        self.assertEqual(len([rows[0] for table,rows,_ in client.upserts if table=='topic_summaries'][-1]['summary']['updates']),1)
        self.assertEqual([rows[0] for table,rows,_ in client.upserts if table=='topic_summaries'][-1]['summary']['base_summary'],old['summary']['base_summary'])

    def test_updates_never_call_writer_and_preserve_synthesis_and_context(self):
        rows=[article('l','LEFT'),article('r','RIGHT')]
        _,known=self.route(rows,[fact('Znany fakt.',['l','r'])])
        base={'perspective_version':1,'coverage_mode':'MIXED','summary_pl':'Dokładnie ta pierwotna synteza.','background_context':[{'text_pl':'Dokładnie ten kontekst.','article_ids':[]}],'topic':{'headline_pl':'[Polska] Pierwotny tytuł'},'perspective_facts':known,'facts':known}
        original=copy.deepcopy(base)
        def call(instructions,data,schema,name):
            self.assertEqual(name,'perspective_facts')
            return extraction([fact('Nowy fakt prawicy.',['r'])],data['all_articles'],headline_pl='[Polska] Inny tytuł',categories=[])
        result=p.generate({'topic':{},'all_articles':rows,'previous_aggregation':{'base_summary':base},'new_article_ids':['r']},call,ai.normalize_generated_text)
        self.assertEqual(result['summary_pl'],base['summary_pl'])
        self.assertEqual(result['background_context'],base['background_context'])
        self.assertEqual(result['topic'],base['topic'])
        self.assertEqual(result['update']['status'],'NEW_INFORMATION')
        self.assertEqual(base,original)
        # Carry the latest ledger separately; otherwise the same new fact
        # would be rediscovered on every confirming article.
        latest=result['perspective_state'];calls=[]
        def confirm(instructions,data,schema,name):
            calls.append(name)
            self.assertEqual(data['previous_facts'],latest['perspective_facts'])
            return extraction([fact(f['text_pl'],f['article_ids'],f['fact_id'],reason='') for f in data['previous_facts']],data['all_articles'])
        again=p.generate({'topic':{},'all_articles':rows,'previous_aggregation':{'base_summary':base,'perspective_state':latest}},confirm,ai.normalize_generated_text)
        self.assertEqual(calls,['perspective_facts'])
        self.assertEqual(again['update']['status'],'NO_NEW_INFORMATION')
        self.assertEqual(again['summary_pl'],base['summary_pl'])
        self.assertEqual(again['background_context'],base['background_context'])

    def test_first_empty_synthesis_is_not_written_later_when_fact_is_promoted(self):
        rows=[article('l','LEFT'),article('r','RIGHT')]
        _,known=self.route(rows,[fact('Decyzja.',['l'])])
        base={'perspective_version':1,'coverage_mode':'MIXED','shared_available':False,'summary_pl':'','background_context':[{'text_pl':'Neutralne tło.'}],'perspective_facts':known}
        def promote(instructions,data,schema,name):
            self.assertEqual(name,'perspective_facts')
            return extraction([fact('Decyzja.',['r'],known[0]['fact_id'],reason='')],data['all_articles'])
        result=p.generate({'topic':{},'all_articles':rows,'previous_aggregation':{'base_summary':base}},promote,ai.normalize_generated_text)
        self.assertTrue(result['shared_available'])
        self.assertEqual(result['summary_pl'],'')
        self.assertEqual(len(result['facts']),1)
        self.assertEqual(len(result['update']['promoted_facts']),1)

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
