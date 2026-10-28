const fs = require('fs'), vm = require('vm'), assert = require('assert');
const context = { window: {GNI_CONFIG: {}, localStorage: {getItem: () => null, setItem() {}}}, document: {}, console, assert };
vm.createContext(context);
vm.runInContext(fs.readFileSync('app/app.js', 'utf8').split("document.addEventListener('click'")[0], context);
vm.runInContext(`
loadDemoData();
const topic = state.topics[0];
const full = 'Pełna synteza przedstawia przebieg rozmów.\\n\\nDrugi akapit syntezy podaje tło.\\n\\nTrzeci akapit syntezy zawiera szczegóły.';
const brief = 'Rada miasta przyjęła program budowy szkół.\\n\\nBudowa ma rozpocząć się w przyszłym roku.';
const factual = {fact_id: 'f1', kind: 'FACT', text_pl: 'FACT_ONLY_SENTINEL', article_ids: ['demo-a1']};
const opinion = {fact_id: 'e1', kind: 'EDITORIAL', text_pl: 'Redakcja ocenia program jako kosztowny.', article_ids: ['demo-a1']};
const saved = {base_summary: {summary_pl: full, brief_pl: 'Stary skrót.\\n\\nStarszy opis.'},
  current_summary: {summary_pl: full, brief_pl: brief, publication_version: 2, perspective_version: 1},
  perspective_state: {perspective_version: 1, publication_version: 2, fact_classification_version: 1,
    shared_available: true, coverage_mode: 'MIXED', facts: [factual], perspective_sections: {EDITORIAL: [opinion]}}, updates: []};
state.summaries.set(topic.topic_id, {version: 1, summary: saved});
const before = JSON.stringify(saved);
let model = topicModel(topic), html = dialogHtml(model);
assert(html.includes('data-dialog-tab="summary"') && html.includes('data-dialog-tab="brief"'));
assert(!html.includes('data-dialog-tab="facts"') && !html.includes('insight-facts'));
assert(!html.includes(factual.text_pl));
assert(html.includes('Trzeci akapit syntezy zawiera szczegóły.'));
assert(html.includes(opinion.text_pl), 'Editorial views remain visible');
const shortPanel = html.match(/class="summary-copy brief-copy">([\\s\\S]*?)<\\/div>/)[1];
assert.strictEqual((shortPanel.match(/<p>/g) || []).length, 2);
assert(shortPanel.includes('Rada miasta') && !shortPanel.includes('Stary skrót'));
assert.strictEqual(model.summary.facts[0].text_pl, factual.text_pl);
assert.strictEqual(JSON.stringify(saved), before, 'Hiding facts does not modify source records');
markTopicRead(model);
saved.current_summary.brief_pl = 'Nowy krótki opis tej samej wiadomości.\\n\\nUzupełniony skrót.';
assert(isTopicRead(topicModel(topic)), 'Brief backfill is not new information');
saved.current_summary.brief_pl = '';
html = dialogHtml(topicModel(topic));
assert(html.includes('Skrót nie jest jeszcze dostępny.'));
assert(!html.includes('FACT_ONLY_SENTINEL'));
assert(!html.includes('class="summary-copy brief-copy"'), 'No fake brief from the opening synthesis paragraphs');
assert.strictEqual(briefText('Jeden akapit.'), '');
assert.strictEqual(briefText('Pierwszy.\\n\\nDrugi.\\n\\nTrzeci.'), '');
const preview = summaryPreview({current_text: full, current_brief: brief, publication_version: 2});
assert.strictEqual(preview.summary.base_summary.brief_pl, brief);
assert.strictEqual(preview.summary.base_summary.summary_pl, full);
saved.current_summary.brief_pl = '<script>alert(1)</script> Pierwszy akapit.\\n\\nDrugi akapit.';
assert(!dialogHtml(topicModel(topic)).includes('<script>'));
console.log('Brief UI: two independent paragraphs, full article retained, facts hidden, opinions retained, safe previews and stable read marks — OK.');
`, context);
