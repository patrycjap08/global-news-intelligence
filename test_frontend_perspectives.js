const fs = require('fs'), vm = require('vm'), assert = require('assert');
const c = {window:{GNI_CONFIG:{},localStorage:{getItem:()=>null,setItem:()=>{}}},document:{},console,assert};
vm.createContext(c);
vm.runInContext(fs.readFileSync('app/app.js','utf8').split("document.addEventListener('click'")[0],c);
vm.runInContext(`
loadDemoData();
const topic=state.topics[0];
const fact=(text,ids=['demo-a1'])=>({text_pl:text,article_ids:ids});
const base={perspective_version:1,coverage_mode:'MIXED',shared_available:false,summary_pl:'',facts:[],
  perspective_sections:{LEFT:[fact('Ustalenie lewicowe.')],RIGHT:[fact('Ustalenie prawicowe.')],STATE:[fact('Według TASS: doniesienie.')]},
  background_context:[fact('Ogólne tło.')],differences:[fact('REMOVE_DIFFERENCES')],contradictions:[fact('REMOVE_CONTRADICTIONS')],potential_manipulation_signals:[fact('REMOVE_SIGNALS')]};
state.summaries.set(topic.topic_id,{summary:{base_summary:base,updates:[]}});
let model=topicModel(topic),html=dialogHtml(model);
assert(html.includes('Źródła o różnych profilach nie podają wspólnych informacji.'));
assert(!html.includes('data-dialog-tab=') && !html.includes('Brak zapisanej syntezy'));
assert(html.includes('data-perspective-tab="LEFT"') && html.includes('data-perspective-tab="RIGHT"') && html.includes('data-perspective-tab="STATE"'));
assert(html.includes('Ogólne tło.') && html.includes('Materiały źródłowe'));
assert(!html.includes('REMOVE_'));
// In single-profile mode the main tabs return; empty perspective tabs disappear.
base.coverage_mode='SINGLE_LEFT';base.shared_available=true;base.summary_pl='Synteza.';base.facts=[fact('Wszystkie ustalenia lewicowe.')];
base.perspective_sections={LEFT:[],RIGHT:[],STATE:[]};
html=dialogHtml(topicModel(topic));
assert(html.includes('Opracowanie wyłącznie na podstawie źródeł lewicowych.'));
assert(html.indexOf('coverage-notice')<html.indexOf('id="dialog-title"'));
assert(html.includes('data-dialog-tab="summary"') && html.includes('data-dialog-tab="facts"'));
assert(!html.includes('data-perspective-tab='));
base.coverage_mode='SINGLE_CENTER';
assert(dialogHtml(topicModel(topic)).includes('Opracowanie wyłącznie na podstawie źródeł centrowych.'));
base.coverage_mode='STATE_ONLY';base.shared_available=false;
html=dialogHtml(topicModel(topic));
assert(html.includes('wyłącznie doniesienia mediów kontrolowanych przez państwo'));
assert(!html.includes('data-dialog-tab='));
// Count articles, even when they repeat one outlet; exclude state from denominator.
const articles=[...Array.from({length:3},(_,i)=>({source_id:'one',source_profile:'CENTER_LEFT'})),{source_profile:'RIGHT'},{source_profile:'CENTER'},...Array.from({length:5},()=>({source_profile:'STATE_ALIGNED'}))];
const bar=articleProfileBar({articles});
assert(bar.includes('60% (3)') && bar.includes('20% (1)'));
assert(!bar.includes('(5)') && !bar.includes('state'));
assert.strictEqual(articleProfileBar({articles:[{source_profile:'STATE_ALIGNED'}]}),'');
assert.strictEqual(editorialGroup({source_profile:'CENTER',source_type:'GOVERNMENT_AGENCY'}),'CENTER');
// Updates remain split and indicate promotion without repeating it as new news.
const update={status:'NEW_INFORMATION',new_information_pl:'Ustalenie.',generated_at:'2026-10-19T12:00:00Z',perspective_sections:{COMMON:[],LEFT:[fact('Nowe lewicowe.')],RIGHT:[],STATE:[]},promoted_facts:[fact('Znany fakt ma szersze potwierdzenie.')]};
assert(perspectiveUpdateLabel(update).includes('źródłach lewicowych'));
assert(perspectiveUpdateLabel(update).includes('Szersze potwierdzenie'));
html=perspectiveUpdateHtml(update);
assert(html.includes('Nowe lewicowe.') && html.includes('Szersze potwierdzenie'));
assert(!html.includes('Nowe informacje wspólne'));
// Cosmetic shared prose refresh must not undo read marks on no-change analyses.
state.summaries.set(topic.topic_id,{summary:{base_summary:base,updates:[update],latest_update:update}});
markTopicRead(topicModel(topic));base.summary_pl='Przeredagowana ta sama synteza.';
assert(isTopicRead(topicModel(topic)));
const newer={...update,generated_at:'2026-10-19T13:00:00Z',new_information_pl:'Nowy fakt.'};
state.summaries.set(topic.topic_id,{summary:{base_summary:base,updates:[update,newer],latest_update:newer}});
assert(!isTopicRead(topicModel(topic)));
// New state-only analyses stay accessible, with no main synthesis.
state.articles = state.articles.map(a=>({...a,source_profile:'STATE_ALIGNED'}));
invalidateViewCache();
assert.strictEqual(topicModel(topic).hasAggregation,true);
// Preview metadata is preserved in direct-Supabase mode as well.
const preview=summaryPreview({perspective_version:1,coverage_mode:'MIXED',shared_available:false,base_text:''});
assert.strictEqual(preview.summary.base_summary.shared_available,false);
console.log('Perspectives UI: no-common message/no tabs, exceptions, separate state view, article shares, split updates, read state and previews — OK.');
`,c);
