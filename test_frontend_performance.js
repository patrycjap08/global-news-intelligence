// Run with: node test_frontend_performance.js
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const elements = new Map(), timers = new Map();
let timerId = 0;
const element = (selector) => {
  if (!elements.has(selector)) elements.set(selector, {textContent:'', innerHTML:'', hidden:false, querySelectorAll:()=>[]});
  return elements.get(selector);
};
const context = {
  window:{GNI_CONFIG:{},localStorage:{getItem:()=>null,setItem:()=>{}},
    setTimeout:(callback)=>{timers.set(++timerId,callback);return timerId;},
    clearTimeout:(id)=>timers.delete(id)},
  document:{querySelector:element},console,assert,elements,timers,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('app/app.js','utf8').split("document.addEventListener('click'")[0],context);
vm.runInContext(`
const savedNow = Date.now;
Date.now = () => Date.parse('2026-10-07T12:00:00Z');
assert.strictEqual(topicIsCurrent({last_seen_at:'2026-10-06T11:00:00Z',is_current:true}),false,'older database flag must not extend 24-hour visibility');
assert.strictEqual(topicIsCurrent({last_seen_at:'2026-10-06T13:00:00Z',is_current:false}),true,'last_seen_at determines current visibility');
Date.now = savedNow;
loadDemoData();
const originalTopicModel = topicModel;
let modelBuilds=0;
topicModel=(topic)=>{modelBuilds++;return originalTopicModel(topic);};
const prepared=allTopicModels();
assert.strictEqual(modelBuilds,3);
const map=articleMap();
assert.strictEqual(articleMap(),map);
for(const query of ['p','pr','prz','przy','przyk']){state.search=query;render({searchOnly:true});}
assert.strictEqual(modelBuilds,3,'typing must reuse models/history and article indexes');
assert.strictEqual(modelForTopic('demo-1'),prepared[0]);
assert.strictEqual(modelBuilds,3,'opening one topic must not rebuild every topic');

state.search='BBC';
assert.deepStrictEqual(Array.from(filteredModels(),m=>m.topic_id),['demo-1']);
state.search='';state.profile='RIGHT';state.categories=['GOSPODARKA'];
assert.deepStrictEqual(Array.from(filteredModels(),m=>m.topic_id),['demo-2']);
state.search='';state.profile='ALL';state.categories=[];
markTopicRead(prepared[0]);state.hideRead=true;
assert.deepStrictEqual(Array.from(filteredModels(),m=>m.topic_id),['demo-2']);
state.hideRead=false;state.bookmarkedTopics={'demo-2':{topic_id:'demo-2'}};state.view='saved';
assert.deepStrictEqual(Array.from(filteredModels(),m=>m.topic_id),['demo-2']);
assert.strictEqual(modelBuilds,3,'read/bookmark changes must not rebuild immutable data');
state.view='current';

state.summaries=new Map(state.summaries);
state.summaries.set('demo-1',{summary:{base_summary:{summary_pl:'Nowa synteza po odświeżeniu.'},updates:[]}});
assert.strictEqual(modelForTopic('demo-1').lead,'Nowa synteza po odświeżeniu.');
assert.strictEqual(modelBuilds,6,'new data must invalidate models');
state.articles=state.articles.map(a=>({...a,source_name:a.source_name==='BBC'?'Nowa redakcja':a.source_name}));
assert.notStrictEqual(articleMap(),map);
assert(modelForTopic('demo-1').sources.includes('Nowa redakcja'));
state.links=state.links.filter(link=>!(link.topic_id==='demo-1' && link.article_id==='demo-a4'));
assert.strictEqual(modelForTopic('demo-1').articles.length,3);

// Time-based current/history classification stays fresh even with cached data.
const now=Date.now();
state.topics=state.topics.map(t=>({...t,last_seen_at:new Date(now-23*3600000).toISOString()}));
const clock=Date.now;
allTopicModels();
const buildsBeforeClockChange=modelBuilds;
Date.now=()=>now+2*3600000;
assert.strictEqual(filteredModels().length,0);
state.view='historical';assert.strictEqual(filteredModels().length,2);
assert.strictEqual(modelBuilds,buildsBeforeClockChange);
Date.now=clock;state.view='current';

// A burst schedules one render after the last input and preserves static filters.
state.search='p';scheduleSearchRender();state.search='pr';scheduleSearchRender();state.search='brak wyników';scheduleSearchRender();
assert.strictEqual(timers.size,1);
render();
const profilesBefore=elements.get('#profile-filters').innerHTML;
const callback=Array.from(timers.values())[0];timers.clear();callback();
assert.strictEqual(elements.get('#result-count').textContent,'0 tematów');
assert.strictEqual(elements.get('#empty-state').hidden,false);
assert.strictEqual(elements.get('#profile-filters').innerHTML,profilesBefore);
state.search='';render({searchOnly:true});
assert.strictEqual(elements.get('#empty-state').hidden,true);
console.log('Frontend: modele i indeksy są używane ponownie; odświeżanie, wyszukiwanie, filtry, odczyt, zakładki i upływ czasu — OK.');
`,context);
