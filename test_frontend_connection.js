// Run with: node test_frontend_connection.js
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('app/app.js', 'utf8').split("document.addEventListener('click'")[0];
const clone = value => JSON.parse(JSON.stringify(value));
const topics = [1, 2].map(i => ({topic_id: `t${i}`, headline_pl: `Temat ${i}`, source_count: 2, article_count: 2, last_seen_at: new Date().toISOString()}));
const links = topics.flatMap(t => [1, 2].map(i => ({topic_id: t.topic_id, article_id: `${t.topic_id}-a${i}`})));
const articles = links.map((link, index) => ({article_id: link.article_id, source_id: `s${index % 2}`, source_name: `Źródło ${index % 2}`, source_profile: 'CENTER', title: 'Materiał źródłowy'}));
const previews = topics.map(t => ({topic_id: t.topic_id, version: 1, base_topic: {what_happened_one_sentence_pl: 'Krótki opis'}, base_text: 'Synteza', update_status: 'BASE_SUMMARY'}));
const response = (data, status = 200) => ({ok: status < 400, status, headers: {get: () => null}, json: async () => clone(data)});
function fixture() {
  const elements = new Map(), calls = [];
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {textContent:'', innerHTML:'', hidden:false, disabled:false, querySelectorAll:()=>[], classList:{add(){},remove(){}}});
    return elements.get(selector);
  };
  let implementation = async (url) => {
    const table = new URL(url).pathname.split('/').pop();
    return response({app_topics: topics, app_topic_articles: links, app_articles: articles, app_topic_summaries: previews, app_latest_harvest:[{started_at:'2026-10-08T08:03:05Z'}]}[table] || []);
  };
  const context = {
    window:{GNI_CONFIG:{supabaseUrl:'https://db.test', supabasePublishableKey:'public-test'},
      localStorage:{getItem:()=>null,setItem:()=>{}},
      setTimeout:(fn,ms)=>{const timer=setTimeout(fn,ms<=3000 ? Math.min(ms,5) : ms);if(ms>3000)timer.unref();return timer;},clearTimeout},
    document:{querySelector:element}, URL, AbortController, console:{warn(){}},
    fetch:async (...args)=>{calls.push(args[0]);return implementation(...args);},
  };
  vm.createContext(context);vm.runInContext(source,context);
  return {context,calls,elements,run:code=>vm.runInContext(code,context),setFetch:fn=>implementation=fn};
}
(async () => {
  // Pages mode loads only index + requested details, with no Supabase calls.
  {
    const f=fixture();f.run("config.staticDataUrl='./data/'; window.location={href:'https://site.test/app/'}");
    const index={schema:1,generation:'abc123',exported_at:'2026-10-09T08:00:00Z',topics,articles,links,summaries:previews};
    f.setFetch(async url=>{
      assert(!String(url).includes('db.test'));
      if(String(url).endsWith('/index.json'))return response(index);
      assert(String(url).endsWith('/abc123/topics/t1.json'));
      return response({summary:{topic_id:'t1',version:2,summary:{base_summary:{summary_pl:'Pełna synteza',facts:['Fakt']},updates:[]}},history:[]});
    });
    await f.run('loadLiveData()');assert.strictEqual(f.calls.length,1);
    assert.strictEqual(f.run('state.loadedAt'),index.exported_at);
    await f.run("loadTopicDetails('t1')");assert.strictEqual(f.calls.length,2);
    assert.strictEqual(f.run("state.summaries.get('t1').summary.base_summary.facts.length"),1);
    const old=f.run('state.topics');f.setFetch(async()=>response({},503));
    assert.strictEqual(await f.run('refreshData()'),false);assert.strictEqual(f.run('state.topics'),old);
  }
  // Duplicate refreshes share one network pass; no full versions/full summaries on startup.
  {
    const f=fixture();let release;
    const gate=new Promise(resolve=>release=resolve);
    f.setFetch(async url=>{const table=new URL(url).pathname.split('/').pop();if(table==='app_topics')await gate;return response({app_topics:topics,app_topic_articles:links,app_articles:articles,app_topic_summaries:previews,app_latest_harvest:[]}[table]);});
    const first=f.run('loadLiveData()'),second=f.run('loadLiveData()');
    assert.strictEqual(first,second);release();await first;
    assert.strictEqual(f.calls.filter(u=>u.includes('/app_topics?')).length,1);
    assert(!f.calls.some(u=>u.includes('app_topic_summary_versions')));
    assert(f.calls.filter(u=>u.includes('/app_articles?')).every(u=>new URL(u).searchParams.has('article_id')));
    assert(f.calls.filter(u=>u.includes('/app_topic_summaries?')).every(u=>new URL(u).searchParams.get('select').includes('base_topic:')));
    assert.strictEqual(f.run('state.demo'),false);
  }
  // A first failed connection remains retryable, with no fabricated demo data.
  {
    const f=fixture();f.setFetch(async ()=>response([],401));
    assert.strictEqual(await f.run('refreshData()'),false);
    assert.strictEqual(f.calls.length,1,'authentication failure must not be retried');
    assert.strictEqual(f.run('state.demo'),false);assert.strictEqual(f.run('state.topics.length'),0);
    assert.strictEqual(f.run('state.connection'),'error');
    assert.strictEqual(f.elements.get('#refresh-button').disabled,false);
    f.setFetch(async url=>response({app_topics:topics,app_topic_articles:links,app_articles:articles,app_topic_summaries:previews,app_latest_harvest:[]}[new URL(url).pathname.split('/').pop()]));
    assert.strictEqual(await f.run('refreshData()'),true);
    assert.strictEqual(f.run('state.connection'),'live');
  }
  // Failure after partial reads cannot overwrite any last-good containers.
  {
    const f=fixture();await f.run('loadLiveData()');
    const previous=f.run('[state.topics,state.articles,state.links,state.summaries,state.loadedAt]');let failures=0;
    f.setFetch(async url=>{const table=new URL(url).pathname.split('/').pop();if(table==='app_articles'){failures++;return response([],503);}return response({app_topics:[{...topics[0],headline_pl:'Nieukończone odświeżenie'}],app_topic_articles:links,app_topic_summaries:previews,app_latest_harvest:[]}[table]);});
    assert.strictEqual(await f.run('refreshData()'),false);assert.strictEqual(failures,3);
    const after=f.run('[state.topics,state.articles,state.links,state.summaries,state.loadedAt]');
    previous.forEach((v,i)=>assert.strictEqual(after[i],v));
    assert.strictEqual(f.run('state.connection'),'cached');
  }
  // Request timeout aborts a stuck connection and bounded retries terminate.
  {
    const f=fixture();let attempts=0;
    f.setFetch((url,{signal})=>{attempts++;return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'})),{once:true}));});
    await assert.rejects(f.run("fetchTable('app_topics','',{timeoutMs:5,attempts:2})"));
    assert.strictEqual(attempts,2);
    f.setFetch(async()=>response([]));await f.run("fetchTable('app_topics')");
  }
  // Full details are lazy, shared per topic, and modern updates need no archive.
  {
    const f=fixture();await f.run('loadLiveData()');let release;
    const gate=new Promise(resolve=>release=resolve);
    f.setFetch(async url=>{await gate;assert.strictEqual(new URL(url).searchParams.get('topic_id'),'eq.t1');return response([{topic_id:'t1',version:2,summary:{base_summary:{summary_pl:'Pełna synteza',facts:[{text:'Fakt'}]},updates:[]}}]);});
    const a=f.run("loadTopicDetails('t1')"),b=f.run("loadTopicDetails('t1')");assert.strictEqual(a,b);release();await a;
    assert.strictEqual(f.run("state.summaries.get('t1').summary.base_summary.facts.length"),1);
    assert(!f.calls.some(u=>u.includes('app_topic_summary_versions')));
    const count=f.calls.length;await f.run("loadTopicDetails('t1')");assert.strictEqual(f.calls.length,count);
  }
  // Legacy history is fetched only for the opened topic, with compact fields.
  {
    const f=fixture();await f.run('loadLiveData()');
    f.setFetch(async url=>{
      const q=new URL(url);assert.strictEqual(q.searchParams.get('topic_id'),'eq.t2');
      if(q.pathname.endsWith('app_topic_summary_versions')){
        assert(q.searchParams.get('select').includes('updates:summary->updates'));
        return response([{topic_id:'t2',version:1,latest_update:{status:'NEW_INFORMATION',new_information_pl:'Starsze ustalenie',update_id:'u1'}},{topic_id:'t2',version:2,latest_update:{status:'NEW_INFORMATION',new_information_pl:'Nowsze ustalenie',update_id:'u2'}}]);
      }
      return response([{topic_id:'t2',version:2,summary:{summary_pl:'Stara synteza',update:{status:'NEW_INFORMATION',new_information_pl:'Nowsze ustalenie',update_id:'u2'}}}]);
    });
    await f.run("loadTopicDetails('t2')");assert.strictEqual(f.run("modelForTopic('t2').updates.length"),2);
  }
  // A detail response started before refresh cannot replace newer data.
  {
    const f=fixture();await f.run('loadLiveData()');let release;
    const delayed=new Promise(resolve=>release=resolve);
    f.setFetch(async url=>{
      const q=new URL(url),table=q.pathname.split('/').pop();
      if(table==='app_topic_summaries' && q.searchParams.get('topic_id')==='eq.t1')return delayed;
      return response({app_topics:topics,app_topic_articles:links,app_articles:articles,app_topic_summaries:previews.map(x=>({...x,base_text:'Nowsza synteza'})),app_latest_harvest:[]}[table]);
    });
    const old=f.run("loadTopicDetails('t1')");await f.run('loadLiveData()');
    release(response([{topic_id:'t1',summary:{base_summary:{summary_pl:'Przestarzała odpowiedź'},updates:[]}}]));await old;
    assert.strictEqual(f.run("state.summaries.get('t1').summary.base_summary.summary_pl"),'Nowsza synteza');
    assert.strictEqual(f.run("fullSummaryTopics.has('t1')"),false);
  }
  // Last successful data can be restored on reopening and survive offline refresh.
  {
    const cache=new Map();
    const attach=f=>{f.context.cacheStorage=cache;f.run("snapshotStorage=async(mode,value)=>{if(mode==='write'){cacheStorage.set('snapshot',JSON.parse(JSON.stringify(value)));return null;}return cacheStorage.get('snapshot') || null;};");};
    const first=fixture();attach(first);await first.run('loadLiveData()');
    const second=fixture();attach(second);assert.strictEqual(await second.run('restoreSnapshot()'),true);
    assert.strictEqual(second.run('state.connection'),'cached');assert.strictEqual(second.run('state.topics.length'),2);
    second.setFetch(async()=>response([],403));await second.run('refreshData()');
    assert.strictEqual(second.run('state.topics.length'),2);assert.strictEqual(second.run('state.demo'),false);
  }
  console.log('Frontend connection: single-flight, retries, timeouts, atomic refresh, offline cache, lazy details/history and stale-response isolation — OK.');
})().catch(error=>{console.error(error);process.exitCode=1;});
