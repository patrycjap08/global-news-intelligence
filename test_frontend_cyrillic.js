const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
const element=selector=>{
 if(!elements.has(selector))elements.set(selector,{innerHTML:'',textContent:'',hidden:false,querySelectorAll:()=>[],classList:{add(){},remove(){}}});
 return elements.get(selector);
};
const context={window:{GNI_CONFIG:{},localStorage:{getItem:()=>null,setItem:()=>{}},setTimeout,clearTimeout},document:{querySelector:element},console};
vm.createContext(context);vm.runInContext(fs.readFileSync('app/app.js','utf8').split("document.addEventListener('click'")[0],context);
const run=code=>vm.runInContext(code,context);
for(const title of ['[Świat] Російські війська','[Polska] Jedna оbca litera','[Świat] Ґрунт','[Świat] \u052f','[Świat] \ua641'])assert(run(`hasCyrillicTitle(${JSON.stringify(title)})`),title);
for(const title of ['[Polska] Zażółć gęślą jaźń','[Ukraina] Atak na Kijów','[Świat] BBC i MI5','[Polska] Poznan\u0301'])assert(!run(`hasCyrillicTitle(${JSON.stringify(title)})`),title);
run(`
const current=new Date().toISOString(),historical=new Date(Date.now()-72*3600000).toISOString();
state.topics=[
 {topic_id:'good',headline_pl:'[Świat] Polski tytuł',last_seen_at:current},
 {topic_id:'bad',headline_pl:'[Świat] Російські війська',last_seen_at:current},
 {topic_id:'old-good',headline_pl:'[Polska] Polski historyczny tytuł',last_seen_at:historical},
 {topic_id:'old-bad',headline_pl:'[Świat] Jedna оbca litera',last_seen_at:historical},
];
state.links=state.topics.flatMap(t=>[0,1].map(i=>({topic_id:t.topic_id,article_id:t.topic_id+i})));
state.articles=state.links.map((l,i)=>({article_id:l.article_id,source_id:'source'+i,source_name:l.topic_id.includes('bad')?'Ukryte źródło':'Źródło '+i,source_profile:'CENTER',title:'Оryginalny nagłówek źródła',fetched_at:current}));
state.summaries=new Map(state.topics.map(t=>[t.topic_id,{topic_id:t.topic_id,version:1,summary:{base_summary:{topic:{what_happened_one_sentence_pl:'Krótki opis.'},summary_pl:'Treść syntezy.'},updates:[]}}]));
state.bookmarkedTopics={good:true,bad:true};
`);
assert.deepStrictEqual(Array.from(run('allTopicModels()'),m=>m.topic_id),['good','old-good']);
assert.strictEqual(run("modelForTopic('bad')"),undefined);
run('render()');
assert.strictEqual(elements.get('#stat-current-topics').textContent,1);
assert.strictEqual(elements.get('#stat-historical-topics').textContent,1);
assert.strictEqual(elements.get('#stat-current-articles').textContent,2);
assert.strictEqual(elements.get('#stat-historical-articles').textContent,2);
assert(!elements.get('#topic-grid').innerHTML.includes('data-topic-id="bad"'));
assert(!elements.get('#source-list').innerHTML.includes('Ukryte źródło'));
run("state.view='historical';render()");assert.deepStrictEqual(Array.from(run('filteredModels()'),m=>m.topic_id),['old-good']);
run("state.view='saved';render()");assert.deepStrictEqual(Array.from(run('filteredModels()'),m=>m.topic_id),['good']);
run("state.view='current';state.search='Російські';render()");assert.strictEqual(run('filteredModels().length'),0);
run("openTopic('bad')");assert(!elements.has('#story-dialog'),'hidden topic cannot be opened');
console.log('Frontend Cyrillic titles: Unicode detection, mixed titles, current/historical/saved, search, counters and dialog guard — OK.');
