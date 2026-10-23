// Run with: node test_frontend_resume.js
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('app/app.js', 'utf8').split("document.addEventListener('click'")[0];
const clone = value => JSON.parse(JSON.stringify(value));
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => clone(data) });

function snapshot(generation, text) {
  return { schema: 1, generation, exported_at: new Date().toISOString(),
    topics: [{topic_id:'t1',headline_pl:'[Polska] Reforma transportu',source_count:2,article_count:2,last_seen_at:new Date().toISOString()}],
    articles: [1,2].map(i => ({article_id:`a${i}`,source_id:`s${i}`,source_name:`Źródło ${i}`,source_profile:'CENTER'})),
    links: [1,2].map(i => ({topic_id:'t1',article_id:`a${i}`})),
    summaries: [{topic_id:'t1',version:1,summary:{base_summary:{summary_pl:text,
      topic:{headline_pl:'[Polska] Reforma transportu'}},updates:[]}}] };
}

function fixture() {
  const elements = new Map(), calls = [], storage = new Map();
  const documentEvents = new EventTarget(), windowEvents = new EventTarget();
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {textContent:'',innerHTML:'',hidden:false,disabled:false,
      open:false,querySelectorAll:()=>[],querySelector:()=>null,closest(){return this;},
      setAttribute(){},classList:{add(){},remove(){},toggle(){}},focus(){}});
    return elements.get(selector);
  };
  const window = { GNI_CONFIG:{staticDataUrl:'./data/'},location:{href:'https://gni.test/'},
    addEventListener:windowEvents.addEventListener.bind(windowEvents),
    localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    setTimeout:(fn,ms)=>{const timer=setTimeout(fn,ms<=3000?Math.min(ms,5):ms);if(ms>3000)timer.unref();return timer;},clearTimeout };
  const document = {visibilityState:'visible',querySelector:element,querySelectorAll:()=>[],
    addEventListener:documentEvents.addEventListener.bind(documentEvents)};
  let published = snapshot('one', 'Pierwsza synteza.');
  let implementation = async () => response(published);
  const context = {window,document,URL,AbortController,console:{warn(){}},
    fetch:async (url,options)=>{calls.push({url:String(url),options});return implementation(url,options);}};
  vm.createContext(context);vm.runInContext(source,context);
  const run = code => vm.runInContext(code,context);
  run('installForegroundRefresh()');
  const emit = (target,type,extra={}) => {const event=new Event(type);Object.assign(event,extra);target.dispatchEvent(event);};
  return {calls,run,elements,document,
    publish:(generation,text)=>{published=snapshot(generation,text);},
    setFetch:fn=>{implementation=fn;},
    current:()=>clone(published),
    visibility:value=>{document.visibilityState=value;emit(documentEvents,'visibilitychange');},
    windowEvent:(type,extra)=>emit(windowEvents,type,extra),
    settle:async()=>{await Promise.resolve();const pending=run('refreshPromise || liveLoadPromise');if(pending)await pending;await Promise.resolve();},
  };
}

(async () => {
  // Cold opening always fetches, and initial browser events do not duplicate it.
  {
    const f=fixture();await f.run('init()');
    f.windowEvent('pageshow',{persisted:false});f.windowEvent('focus');
    assert.strictEqual(f.calls.length,1);
    assert.strictEqual(f.run('state.staticGeneration'),'one');
  }
  // A successful connection still refreshes on every return, even immediately.
  {
    const f=fixture();await f.run('init()');
    f.run("state.search='transport';state.categories=['POLITYKA'];state.view='saved';state.hideRead=true");
    f.visibility('hidden');f.publish('two','Nowsza synteza.');f.visibility('visible');
    f.windowEvent('focus');f.windowEvent('pageshow',{persisted:true});await f.settle();
    assert.strictEqual(f.calls.length,2,'visibility/focus/pageshow are one foreground entry');
    assert.strictEqual(f.run('state.staticGeneration'),'two');
    assert.strictEqual(f.run("state.summaries.get('t1').summary.base_summary.summary_pl"),'Nowsza synteza.');
    assert.strictEqual(f.run('state.search'),'transport');assert.strictEqual(f.run('state.view'),'saved');
    assert.strictEqual(f.run('state.hideRead'),true);assert.deepStrictEqual(Array.from(f.run('state.categories')),['POLITYKA']);
    f.visibility('hidden');f.publish('three','Najnowsza synteza.');f.visibility('visible');await f.settle();
    assert.strictEqual(f.calls.length,3,'No minimum absence time or freshness threshold');
    assert.strictEqual(f.run('state.staticGeneration'),'three');
    for(const {url,options} of f.calls) {
      assert(new URL(url).searchParams.has('refresh'),'Manifest bypasses the Pages cache');
      assert.strictEqual(options.cache,'no-store');
    }
  }
  // Window focus provides a fallback when the browser keeps visibility unchanged.
  {
    const f=fixture();await f.run('init()');f.publish('two','Po powrocie do okna.');
    f.windowEvent('blur');f.windowEvent('focus');f.windowEvent('focus');await f.settle();
    assert.strictEqual(f.calls.length,2);assert.strictEqual(f.run('state.staticGeneration'),'two');
  }
  // Restore from the back/forward cache refreshes without a new document load.
  {
    const f=fixture();await f.run('init()');f.windowEvent('pagehide');
    f.publish('two','Po powrocie z innej strony.');f.windowEvent('pageshow',{persisted:true});await f.settle();
    assert.strictEqual(f.calls.length,2);assert.strictEqual(f.run('state.staticGeneration'),'two');
  }
  // Hidden pages do not fetch merely because focus or pageshow was signalled.
  {
    const f=fixture();await f.run('init()');f.visibility('hidden');
    f.windowEvent('focus');f.windowEvent('pageshow',{persisted:true});await f.settle();
    assert.strictEqual(f.calls.length,1);
    f.visibility('visible');await f.settle();assert.strictEqual(f.calls.length,2);
  }
  // An open story stays on screen until full new details arrive, without a short-preview flash.
  {
    const f=fixture();await f.run('init()');f.elements.get('#story-dialog').open=true;
    f.run("openDialogTopicId='t1';fullSummaryTopics.add('t1');var dialogRenders=[],detailLoads=[];renderTopicDialog=(id,status)=>dialogRenders.push(status);fillTopicDialog=async(id)=>detailLoads.push(id)");
    f.visibility('hidden');f.publish('two','Nowa synteza.');f.visibility('visible');await f.settle();
    assert.deepStrictEqual(Array.from(f.run('dialogRenders')),[]);
    assert.deepStrictEqual(Array.from(f.run('detailLoads')),['t1']);
    assert.strictEqual(f.elements.get('#story-dialog').open,true);
  }
  // A pre-background request cannot be the only refresh after returning.
  {
    const f=fixture();await f.run('init()');let release, delayed=true;
    const gate=new Promise(resolve=>release=resolve), old=snapshot('two','Odpowiedź rozpoczęta przed powrotem.');
    f.setFetch(async()=>{if(delayed){delayed=false;await gate;return response(old);}return response(snapshot('three','Opublikowane w tle.'));});
    const earlier=f.run('refreshData()');f.visibility('hidden');f.visibility('visible');f.windowEvent('focus');
    assert.strictEqual(f.calls.length,2,'Wait for the current request instead of duplicating it');
    release();await earlier;await f.settle();
    assert.strictEqual(f.calls.length,3);assert.strictEqual(f.run('state.staticGeneration'),'three');
  }
  // Returning again to the background cancels a queued foreground check.
  {
    const f=fixture();await f.run('init()');let release;
    f.setFetch(()=>new Promise(resolve=>{release=()=>resolve(response(snapshot('two','Zakończone pobranie.')));}));
    const earlier=f.run('refreshData()');f.visibility('hidden');f.visibility('visible');f.visibility('hidden');
    release();await earlier;await f.settle();assert.strictEqual(f.calls.length,2);
    f.setFetch(async()=>response(snapshot('three','Nowy powrót.')));
    f.visibility('visible');await f.settle();assert.strictEqual(f.calls.length,3);
    assert.strictEqual(f.run('state.staticGeneration'),'three');
  }
  // A suspended request past its deadline is aborted and followed by a fresh load.
  {
    const f=fixture();await f.run('init()');let stuck=true;
    f.setFetch((url,{signal})=>{if(!stuck)return Promise.resolve(response(snapshot('two','Po wznowieniu.')));
      stuck=false;return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true}));});
    const earlier=f.run('refreshData()');f.run('liveLoadStartedAt=Date.now()-LOAD_TIMEOUT_MS-1');
    f.visibility('hidden');f.visibility('visible');await earlier;await f.settle();
    assert.strictEqual(f.calls.length,3);assert.strictEqual(f.run('state.staticGeneration'),'two');
  }
  // Even a fetch implementation that resolves after abort cannot commit stale data.
  {
    const f=fixture();await f.run('init()');let release;
    f.setFetch(()=>new Promise(resolve=>{release=()=>resolve(response(snapshot('stale','Przerwane pobranie.')));}));
    const earlier=f.run('loadLiveData()');f.run('liveLoadController.abort()');release();
    await assert.rejects(earlier);
    assert.strictEqual(f.run('state.staticGeneration'),'one');
  }
  // Offline resumes preserve real data and recover on the next foreground entry.
  {
    const f=fixture();await f.run('init()');f.setFetch(async()=>response({},503));
    f.visibility('hidden');f.visibility('visible');await f.settle();
    assert.strictEqual(f.run('state.staticGeneration'),'one');assert.strictEqual(f.run('state.connection'),'cached');
    assert.strictEqual(f.run('state.demo'),false);
    f.setFetch(async()=>response(snapshot('two','Po odzyskaniu sieci.')));
    f.visibility('hidden');f.visibility('visible');await f.settle();
    assert.strictEqual(f.run('state.staticGeneration'),'two');assert.strictEqual(f.run('state.connection'),'live');
  }
  // Demo screens do not start requests when the app returns to the foreground.
  {
    const f=fixture();f.run('state.demo=true');f.visibility('hidden');f.visibility('visible');await f.settle();
    assert.strictEqual(f.calls.length,0);
  }
  console.log('Frontend resume: cold start, every return, focus, bfcache, one request per entry, fresh manifests, in-flight recovery and offline data — OK.');
})().catch(error=>{console.error(error);process.exitCode=1;});
