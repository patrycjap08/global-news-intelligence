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
assert(html.includes('Brak ustaleń spełniających kryteria tej syntezy. Dodatkowe informacje ze źródeł są poniżej.'));
assert(!html.includes('data-dialog-tab=') && !html.includes('Brak zapisanej syntezy'));
assert(html.includes('Ustalenie lewicowe.') && html.includes('Ustalenie prawicowe.') && html.includes('Media kontrolowane przez państwo'));
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
const oneProfile=articleProfileBar({articles:[{source_profile:'LEFT'},{source_profile:'CENTER_LEFT'}]});
assert(oneProfile.includes('Lewicowe <strong>100% (2)</strong>'));
assert(oneProfile.includes('Centrum <strong>0% (0)</strong>') && oneProfile.includes('Prawicowe <strong>0% (0)</strong>'));
for(const group of ['left','center','right']) assert(oneProfile.includes('class="profile-share-'+group+'" style='),
  'all three colors remain visible, including groups with no articles');
assert.strictEqual((oneProfile.match(/flex:0 1 0%;min-width:4px/g)||[]).length,2);
const twoProfiles=articleProfileBar({articles:[{source_profile:'CENTER'},{source_profile:'RIGHT'}]});
assert(twoProfiles.includes('Centrum <strong>50% (1)</strong>') && twoProfiles.includes('Prawicowe <strong>50% (1)</strong>'));
assert(twoProfiles.includes('Lewicowe <strong>0% (0)</strong>'));
assert(twoProfiles.includes('class="profile-share-left" style="flex:0 1 0%;min-width:4px"'));
// A small share rounded to zero still shows its actual article count.
const roundedZero=articleProfileBar({articles:[...Array.from({length:200},()=>({source_profile:'LEFT'})),
  ...Array.from({length:200},()=>({source_profile:'CENTER'})),{source_profile:'RIGHT'}]});
assert(roundedZero.includes('Prawicowe <strong>0% (1)</strong>'));
assert.strictEqual(editorialGroup({source_profile:'CENTER',source_type:'GOVERNMENT_AGENCY'}),'CENTER');
// Updates remain split and indicate promotion without repeating it as new news.
const update={status:'NEW_INFORMATION',new_information_pl:'Ustalenie.',generated_at:'2026-10-19T12:00:00Z',perspective_sections:{COMMON:[],LEFT:[fact('Nowe lewicowe.')],RIGHT:[],STATE:[]},promoted_facts:[fact('Znany fakt ma szersze potwierdzenie.')]};
assert(perspectiveUpdateLabel(update).includes('źródłach lewicowych'));
assert(!perspectiveUpdateLabel(update).includes('Szersze potwierdzenie'));
html=perspectiveUpdateHtml(update);
assert(html.includes('Nowe lewicowe.') && !html.includes('Szersze potwierdzenie'));
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
const stateOnlyModel=topicModel(topic);
assert.strictEqual(stateOnlyModel.stateOnly,true);
assert.strictEqual(stateOnlyModel.summary.summary_pl,'');
assert(!stateOnlyModel.lead.includes('Przeredagowana'));
assert.strictEqual(stateOnlyModel.updates.length,0);
html=dialogHtml(stateOnlyModel);
assert(!html.includes('data-dialog-tab=') && !html.includes('Przeredagowana'));
// A stored synthesis with incorrect/missing STATE_ONLY metadata cannot leak
// into the card or dialog when all actual source articles are state media.
base.coverage_mode='MIXED';base.shared_available=true;base.summary_pl='STATE_SYNTHESIS_MUST_NOT_APPEAR';
base.topic={what_happened_one_sentence_pl:'STATE_LEAD_MUST_NOT_APPEAR'};
html=dialogHtml(topicModel(topic));
assert(!html.includes('STATE_SYNTHESIS_MUST_NOT_APPEAR') && !html.includes('STATE_LEAD_MUST_NOT_APPEAR'));
assert(!html.includes('data-dialog-tab='));
assert(html.includes('nie tworzymy syntezy'));
assert.strictEqual(isStateSource({source_profile:'CENTER',source_type:'GOVERNMENT_AGENCY'}),false);
// Subsequent mixed-source fixtures regain their independent source data.
state.articles=state.articles.map(a=>({...a,source_profile:'CENTER'}));invalidateViewCache();
// Preview metadata is preserved in direct-Supabase mode as well.
const preview=summaryPreview({perspective_version:1,coverage_mode:'MIXED',shared_available:false,base_text:''});
assert.strictEqual(preview.summary.base_summary.shared_available,false);
// Latest fact state is overlaid without changing the original publication.
const frozen={perspective_version:1,coverage_mode:'SINGLE_LEFT',shared_available:true,summary_pl:'Zachowana synteza.',background_context:[fact('Zachowany kontekst.')],facts:[fact('Pierwotny fakt.')]};
const current={perspective_version:1,coverage_mode:'MIXED',shared_available:true,facts:[fact('Aktualny wspólny fakt.')],perspective_sections:{LEFT:[],RIGHT:[],STATE:[]}};
state.summaries.set(topic.topic_id,{summary:{base_summary:frozen,perspective_state:current,updates:[]}});
model=topicModel(topic);
assert.strictEqual(model.summary.summary_pl,'Zachowana synteza.');
assert.strictEqual(model.summary.facts[0].text_pl,'Aktualny wspólny fakt.');
assert(coverageNotice(model.summary).includes('Pierwotna synteza powstała wyłącznie na podstawie źródeł lewicowych.'));
assert.strictEqual(frozen.coverage_mode,'SINGLE_LEFT');
assert.strictEqual(frozen.facts[0].text_pl,'Pierwotny fakt.');
// A topic initially published without common facts never creates a new
// narrative later; promoted common facts are accessible without an empty tab.
frozen.summary_pl='';
html=dialogHtml(topicModel(topic));
assert(!html.includes('data-dialog-tab="summary"'));
assert(html.includes('aria-selected="true" aria-controls="dialog-panel-facts"'));
assert(html.includes('Aktualny wspólny fakt.'));
assert(!html.includes('Brak zapisanej syntezy.'));
const latestPreview=summaryPreview({perspective_version:1,coverage_mode:'SINGLE_LEFT',shared_available:true,current_coverage_mode:'MIXED',current_shared_available:false});
assert.strictEqual(latestPreview.summary.base_summary.shared_available,false);
assert.strictEqual(latestPreview.summary.base_summary.synthesis_coverage_mode,'SINGLE_LEFT');
console.log('Perspectives UI: no-common message/no tabs, exceptions, separate state view, article shares, split updates, read state and previews — OK.');
`,c);
