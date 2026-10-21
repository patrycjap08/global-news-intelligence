const fs = require('fs'), vm = require('vm'), assert = require('assert');
const fixture = JSON.parse(fs.readFileSync('test_data/publication_audit_20261021.json', 'utf8'));
const context = {window: {GNI_CONFIG: {}, localStorage: {getItem: () => null, setItem: () => {}}}, document: {}, console, assert, fixture};
vm.createContext(context);
vm.runInContext(fs.readFileSync('app/app.js', 'utf8').split("document.addEventListener('click'")[0], context);
vm.runInContext(`
const snapshot = JSON.stringify(fixture);
for (const record of fixture.topics) {
  state.topics = [record.topic]; state.articles = record.articles; state.links = record.links;
  state.summaries = new Map([[record.topic.topic_id, record.summary]]); state.history = new Map(); invalidateViewCache();
  const model = topicModel(record.topic), html = dialogHtml(model);
  const currentSections = perspectiveSectionsHtml(model.summary, 'ready', model.updates);
  const sourceAssessment = 'Analiza opublikowana przez Le Monde sugeruje';
  if (record.topic.topic_id.endsWith('5b5e026fe04d9224a6da8fd9')) {
    assert.equal(currentSections.split(sourceAssessment).length - 1, 1, 'One quoted opinion, carried by both profiles');
    assert(currentSections.includes('Lewicowe') && currentSections.includes('Prawicowe'));
    assert(currentSections.includes('Le Monde') && currentSections.includes('El Mundo') && currentSections.includes('Niezależna'));
  }
  for (const bad of ['(Brak dodatkowych ustaleń)', '6:??', '202?', 'Desnianskyi/Daniels?', 'Dodał, że', 'Podkreśla, że']) {
    assert(!listValue(model.summary.facts).includes(bad), 'Reject public placeholder: ' + bad);
  }
  assert(model.summary.background_context.every(c => !c.needs_verification));
  assert(!html.includes('historia aktualizacji'));
  assert(!html.includes('class="update-section'));
  assert(!html.includes('class="claim-kind"'));
  assert(!html.includes('class="claim-attribution"'));
  assert(!html.includes('<details open'));
  for (const update of model.updates) {
    const onlyPromotions = {...update, perspective_sections: {}, new_information_pl: ''};
    assert(!perspectiveUpdateHtml(onlyPromotions).includes('Szersze potwierdzenie'));
  }
  markTopicRead(model);
  dialogHtml(topicModel(record.topic));
  assert(isTopicRead(topicModel(record.topic)), 'Rendering must not reset read state');
}
assert.equal(JSON.stringify(fixture), snapshot, 'Historical records must remain untouched');

const record = fixture.topics[1], changed = JSON.parse(JSON.stringify(record.summary));
changed.summary.current_summary = {perspective_version: 1, publication_version: 2,
  topic: {what_happened_one_sentence_pl: 'Najnowsza decyzja w sprawie sankcji.'}, summary_pl: 'Aktualna synteza po decyzji rządu.', background_context: []};
state.topics = [record.topic]; state.articles = record.articles; state.links = record.links;
state.summaries = new Map([[record.topic.topic_id, changed]]); invalidateViewCache();
const current = topicModel(record.topic), html = dialogHtml(current);
assert.equal(current.lead, 'Najnowsza decyzja w sprawie sankcji.');
assert.equal(current.summary.summary_pl, 'Aktualna synteza po decyzji rządu.');
assert(html.includes('Pierwsza opublikowana synteza'));
assert.equal(listValue([{text_pl: 'Dodał, że nastąpi zmiana.'}, {text_pl: 'Podkreśla, że nastąpi zmiana.'}]), '');
assert(listValue([{description_pl: 'Rada przyjęła budżet.'}]).includes('Rada przyjęła budżet.'), 'Retain legacy field aliases');
const stateOnly = {...current, stateOnly: true, mergedPublications: [{base_summary: {summary_pl: 'PRIVATE_ARCHIVE'}}]};
assert(!dialogHtml(stateOnly).includes('PRIVATE_ARCHIVE'), 'State-only must not reveal old neutral prose');
const fullUpdate = current.latestUpdate;
const preview = {status: fullUpdate.status, new_information_pl: fullUpdate.new_information_pl,
 generated_at: fullUpdate.generated_at, fact_classification_version: fullUpdate.fact_classification_version,
 section_counts: Object.fromEntries(Object.entries(fullUpdate.perspective_sections || {}).map(([k,v]) => [k,v.length]))};
assert.equal(perspectiveUpdateLabel(preview), perspectiveUpdateLabel(fullUpdate));
assert.equal(topicReadContent({...current, updates: [preview]}), topicReadContent({...current, updates: [fullUpdate]}));
console.log('Public audit: France, sanctions and Ukraine — one opinion, optional context, no placeholders, current text and stable history/read marks.');
`, context);
