const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('app/app.js','utf8').split("document.addEventListener('click'")[0];
function fixture(storage=new Map()) {
 const elements=new Map();
 const element=selector=>{if(!elements.has(selector))elements.set(selector,{innerHTML:'',textContent:'',hidden:false,querySelectorAll:()=>[]});return elements.get(selector);};
 const context={window:{GNI_CONFIG:{},localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},setTimeout,clearTimeout},document:{querySelector:element},console:{warn(){}}};
 vm.createContext(context);vm.runInContext(source,context);return {run:code=>vm.runInContext(code,context),storage,elements};
}
const f=fixture();
f.run(`
const when=new Date().toISOString();
const basic={hasAggregation:true,isCurrent:true,last_seen_at:when,newestArticleAt:when,articles:[{source_profile:'CENTER'}],sourceCount:2,searchText:'Opis: unikalnytekst',evidenceIds:[],updates:[],summaryVersion:1,summaryUpdatedAt:when};
const models=[{...basic,topic_id:'p',categories:['POLSKA']},{...basic,topic_id:'s',categories:['SWIAT']},{...basic,topic_id:'ps',categories:['POLSKA','SWIAT']},{...basic,topic_id:'none',categories:[]}];
state.categories=['POLSKA','SWIAT'];state.categoryMatch='ANY';
`);
assert.deepStrictEqual(Array.from(f.run('filteredModels(models)').map(x=>x.topic_id)),['p','s','ps']);
assert.strictEqual(f.run('categoryCounts(models).SWIAT'),2);
f.run("state.categories=['POLSKA']");assert.strictEqual(f.run('categoryCounts(models).SWIAT'),2,'OR counts ignore selected categories');
f.run("state.categoryMatch='ALL'");assert.strictEqual(f.run('categoryCounts(models).SWIAT'),1,'AND counts show intersection with Poland');
f.run("state.categories=['POLSKA','SWIAT']");assert.deepStrictEqual(Array.from(f.run('filteredModels(models)').map(x=>x.topic_id)),['ps']);
assert.strictEqual(f.run('categoryCounts(models).POLSKA'),1);assert.strictEqual(f.run('categoryCounts(models).UNCLASSIFIED'),0);
f.run("state.categories=[];state.search='unikalnytekst'");assert.strictEqual(f.run('filteredModels(models).length'),4,'search matches description independently of title');
f.run("state.search='';state.hideRead=true;state.readTopics={p:'all'}"); // read-state behavior is covered in performance tests
f.run("state.view='historical';state.sort='newest';state.categories=['POLSKA','SWIAT'];state.categoryMatch='ALL';state.profile='CENTER';state.search='tekst';saveFilterPreferences()");
const restored=fixture(f.storage);restored.run('restoreFilterPreferences()');
assert.strictEqual(restored.run('state.sort'),'newest');assert.strictEqual(restored.run('state.categoryMatch'),'ALL');assert.strictEqual(restored.run('state.view'),'historical');assert.strictEqual(restored.run('state.hideRead'),true);assert.deepStrictEqual(Array.from(restored.run('state.categories')),['POLSKA','SWIAT']);
const bad=fixture(new Map([['gni.filters.v1','{bad-json']]));bad.run('restoreFilterPreferences()');assert.strictEqual(bad.run('state.categoryMatch'),'ANY');
assert.strictEqual(f.run("(richTextHtml(synthesisParagraphs('Pierwsze zdanie. Drugie zdanie. Trzecie zdanie.')).match(/<p>/g)||[]).length"),2);
assert.strictEqual(f.run("normalizeDisplayText('Opis. }')"),'Opis.');
assert(!f.run("synthesisParagraphs('Pierwsze zdanie. Drugie zdanie.\\n\\nPodsumowując, to samo zdarzenie.')").includes('Podsumowując'));
console.log('Frontend filters: OR/AND, facet intersections, description search, persisted preferences and legacy paragraphs — OK.');
