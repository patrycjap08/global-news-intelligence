const fs = require('fs'), vm = require('vm'), assert = require('assert');
const c = {window:{GNI_CONFIG:{},localStorage:{getItem:()=>null,setItem:()=>{}}},document:{},console,assert};
vm.createContext(c);
vm.runInContext(fs.readFileSync('app/app.js','utf8').split("document.addEventListener('click'")[0],c);
vm.runInContext(`
loadDemoData();
const topic=state.topics[0];
const fact=(id,text,kind='FACT',ids=['demo-a1'])=>({fact_id:id,text_pl:text,kind,article_ids:ids});
const detail=fact('detail','Numer lotu to OS82.');
const statement=fact('statement','Minister twierdzi, że reforma obniży ceny.','STATEMENT');
statement.attribution='Minister spraw wewnętrznych';
const assessment=fact('assessment','Autor nazywa plan skandalicznym.','EDITORIAL');
const centerAssessment=fact('center','Autor redakcji centrowej krytykuje plan.','EDITORIAL');
const frozen={perspective_version:1,summary_pl:'Pierwotna synteza.',coverage_mode:'MIXED',shared_available:true,
  facts:[],background_context:[{text_pl:'Zachowany kontekst.'}]};
const current={perspective_version:1,fact_classification_version:1,coverage_mode:'MIXED',shared_available:true,
  facts:[detail,statement],perspective_sections:{LEFT:[assessment],RIGHT:[],CENTER:[centerAssessment],STATE:[]}};
state.summaries.set(topic.topic_id,{summary:{base_summary:frozen,perspective_state:current,updates:[]}});
let model=topicModel(topic),html=dialogHtml(model);
assert(html.includes('Numer lotu to OS82.') && html.includes('Minister twierdzi'));
assert(!html.includes('class="claim-kind"'));
assert(!html.includes('Autor: Minister spraw wewnętrznych'));
assert(!html.includes('class="claim-attribution"'));
assert.strictEqual(model.summary.facts.find(f => f.fact_id === 'statement').attribution, 'Minister spraw wewnętrznych');
const withEvidence={...statement,evidence:{'demo-a1':{quote:'Minister powiedział, że reforma obniży ceny.'}}};
const evidenceHtml=listValue([withEvidence]);
assert(evidenceHtml.includes('<details class="claim-evidence">'));
assert(evidenceHtml.includes('Fragmenty źródeł') && evidenceHtml.includes('Minister powiedział'));
assert(html.includes('Oceny i interpretacje') && html.includes(centerAssessment.text_pl));
const sections=perspectiveSectionsHtml(model.summary,'ready',[]);
assert(!sections.includes(detail.text_pl) && !sections.includes(statement.text_pl));
assert(sections.includes(assessment.text_pl) && sections.includes(centerAssessment.text_pl));
assert.strictEqual(model.summary.summary_pl,frozen.summary_pl);
const update={fact_classification_version:1,status:'NEW_INFORMATION',generated_at:'2026-10-19T12:00:00Z',
  new_information_pl:'Nowy numer lotu.',perspective_sections:{COMMON:[detail],LEFT:[assessment],CENTER:[centerAssessment]},promoted_facts:[]};
assert(perspectiveUpdateLabel(update).includes('Nowe ustalenia'));
assert(perspectiveUpdateHtml(update).includes('Nowe oceny i interpretacje'));
assert(!perspectiveUpdateHtml(update).includes('Nowe informacje wspólne'));
const oldUpdate={...update};delete oldUpdate.fact_classification_version;
assert(perspectiveUpdateLabel(oldUpdate).includes('Nowe informacje wspólne'));
// Classification of already known facts changes no read marker.
markTopicRead(model);
state.summaries.set(topic.topic_id,{summary:{base_summary:frozen,perspective_state:{...current,facts:[detail]},updates:[]}});
assert(isTopicRead(topicModel(topic)));
// Matching text in an older left update must not hide a right-source
// assessment when another outlet later independently expresses the same view.
const both={...current,perspective_sections:{LEFT:[assessment],RIGHT:[{...assessment,article_ids:['demo-a2']}]}};
const leftHistory=[{perspective_sections:{LEFT:[assessment]}}];
html=perspectiveSectionsHtml(both,'ready',leftHistory);
assert(!html.includes('data-perspective-tab="LEFT"'));
assert.strictEqual(html.split(assessment.text_pl).length - 1, 1);
// New opinion-only topics get the neutral-content message, while historical
// unclassified publications keep their established wording.
const opinionOnly={...model,summary:{...current,summary_pl:'',shared_available:false,facts:[]}};
html=dialogHtml(opinionOnly);
assert(html.includes('nie ma neutralnych ustaleń do syntezy'));
assert(!html.includes('data-dialog-tab='));
delete opinionOnly.summary.fact_classification_version;
assert(dialogHtml(opinionOnly).includes('Brak ustaleń spełniających kryteria tej syntezy. Dodatkowe informacje ze źródeł są poniżej.'));
const preview=summaryPreview({perspective_version:1,current_fact_classification_version:1,shared_available:true});
assert.strictEqual(preview.summary.base_summary.fact_classification_version,1);
console.log('Fact kinds UI: neutral details and statements, editorial/center tabs, versioned updates, per-profile evidence and unchanged read marks — OK.');
`,c);
