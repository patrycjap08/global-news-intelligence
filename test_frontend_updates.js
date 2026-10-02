// Run with: node test_frontend_updates.js
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const context = {
  window: {GNI_CONFIG: {}, localStorage: {getItem: () => null, setItem: () => {}}},
  document: {}, console, assert,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('app/app.js', 'utf8').split("document.addEventListener('click'")[0], context);
vm.runInContext(`
loadDemoData();
const topic = state.topics[0];
const base = {summary_pl: 'Synteza bazowa.'};
const first = {status: 'NEW_INFORMATION', update_id: 'u1', run_id: 'same-run', new_information_pl: 'Pierwszy nowy fakt.', new_article_ids: ['demo-a1'], generated_at: '2026-10-02T08:34:00Z'};
const second = {status: 'NEW_INFORMATION', update_id: 'u2', run_id: 'same-run', new_information_pl: 'Drugi nowy fakt.', new_article_ids: ['demo-a2'], generated_at: '2026-10-02T09:45:00Z'};
const noChange = {status: 'NO_NEW_INFORMATION', is_update: false, new_information_pl: 'Nie pokazuj potwierdzenia.', new_article_ids: ['demo-a4'], generated_at: '2026-10-02T10:00:00Z'};
const stored = {base_summary: base, updates: [first, second], latest_update: second, last_analysis: noChange};
state.summaries.set(topic.topic_id, {summary: stored});
state.history.set(topic.topic_id, [{summary: {...stored, updates: [first, second, noChange]}}]);
const model = topicModel(topic);
assert.strictEqual(model.updates.length, 2);
assert.strictEqual(updateText(noChange), '');
assert.strictEqual(model.articles.length, 4); // new confirming article remains
assert.strictEqual(model.latestAnalysisStatus, 'NO_NEW_INFORMATION');
assert.strictEqual(cardHtml(model, 1).includes('AKTUALIZACJA'), false);
const html = dialogHtml(model);
assert.strictEqual((html.match(/class="update-label"/g) || []).length, 2);
assert(html.includes('Pierwszy nowy fakt.') && html.includes('Drugi nowy fakt.'));
assert(!html.includes('Nie pokazuj potwierdzenia.'));
assert(html.includes('02.10.2026') && html.includes('10:34') && html.includes('11:45'));
assert(html.includes('Materiały źródłowe'));

state.summaries.set(topic.topic_id, {summary: {base_summary: base, updates: [], latest_update: {status: 'BASE_SUMMARY'}, last_analysis: noChange}});
state.history.set(topic.topic_id, [{summary: {base_summary: base, updates: [noChange], latest_update: noChange}}]);
const noUpdates = topicModel(topic);
assert.strictEqual(noUpdates.updates.length, 0);
assert(!dialogHtml(noUpdates).includes('update-label'));
assert(!cardHtml(noUpdates, 1).includes('AKTUALIZACJA'));
assert.strictEqual(noUpdates.articles.length, 4);
assert(dialogHtml(noUpdates).includes('Synteza bazowa.'));

state.summaries.set(topic.topic_id, {summary: {base_summary: base, updates: [first], latest_update: first, last_analysis: first}});
state.history.set(topic.topic_id, []);
assert(cardHtml(topicModel(topic), 1).includes('AKTUALIZACJA'));
console.log('Frontend: brak pustych aktualizacji i oznaczeń, źródła zachowane, data i godzina czasu polskiego, osobne aktualizacje w tym samym runie — OK.');
`, context);
