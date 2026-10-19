const fs = require('fs'), vm = require('vm'), assert = require('assert');
const fixture = JSON.parse(fs.readFileSync('test_data/perspective_display_regression.json', 'utf8'));
const context = { window: { GNI_CONFIG: {}, localStorage: { getItem: () => null, setItem: () => {} } },
  document: {}, console, assert, fixture };
vm.createContext(context);
vm.runInContext(fs.readFileSync('app/app.js', 'utf8').split("document.addEventListener('click'")[0], context);
vm.runInContext(`
// Replay the public record from the user's Austrian Airlines screenshots.
state.topics = [fixture.topic]; state.articles = fixture.articles; state.links = fixture.links;
state.summaries = new Map([[fixture.topic.topic_id, fixture.summary]]);
state.history = new Map([[fixture.topic.topic_id, fixture.history]]);
invalidateViewCache();
const before = JSON.stringify(fixture);
const model = topicModel(fixture.topic), html = dialogHtml(model);
assert.strictEqual(html.split(fixture.repeated_text).length - 1, 1,
  'OS82 must appear once, in the update, not again in the left section');
assert(model.updates.some(update => perspectiveUpdateHtml(update).includes(fixture.repeated_text)));
assert(!perspectiveSectionsHtml(model.summary, 'ready', model.updates).includes(fixture.repeated_text));
assert(model.summary.perspective_sections.LEFT.some(fact => fact.fact_id === fixture.repeated_fact_id),
  'the complete current ledger is preserved');
assert.strictEqual(model.summary.summary_pl, fixture.summary.summary.base_summary.summary_pl);
assert.strictEqual(JSON.stringify(fixture), before, 'display must not mutate stored facts or update history');
markTopicRead(model);
dialogHtml(topicModel(fixture.topic));
assert(isTopicRead(topicModel(fixture.topic)), 'the display correction must not mark a topic unread');

const fact = (id, text) => ({ fact_id: id, text_pl: text, article_ids: [] });
const originalLeft = fact('old-left', 'Pierwotne ustalenie lewicowe.');
const newLeft = fact('new-left', 'Dodatkowe ustalenie lewicowe.');
const originalRight = fact('old-right', 'Pierwotne ustalenie prawicowe.');
const newRight = fact('new-right', 'Dodatkowe ustalenie prawicowe.');
const originalState = fact('old-state', 'Pierwotne doniesienie państwowe.');
const newState = fact('new-state', 'Dodatkowe doniesienie państwowe.');
const summary = { perspective_version: 1, perspective_sections: {
  LEFT: [originalLeft, newLeft], RIGHT: [originalRight, newRight], STATE: [originalState, newState] } };
const updates = [{ perspective_sections: { LEFT: [newLeft] } },
  { perspective_sections: { RIGHT: [newRight], STATE: [newState] } }];
const saved = JSON.stringify({ summary, updates });
const sections = perspectiveSectionsHtml(summary, 'ready', updates);
for (const item of [originalLeft, originalRight, originalState]) assert(sections.includes(item.text_pl));
for (const item of [newLeft, newRight, newState]) assert(!sections.includes(item.text_pl),
  'check all displayed updates, including older ones and state reports');
assert.strictEqual(JSON.stringify({ summary, updates }), saved);
// A confirming analysis adds no timeline entry and must not hide original facts.
assert(perspectiveSectionsHtml(summary, 'ready', []).includes(originalLeft.text_pl));
assert(perspectiveSectionsHtml(summary, 'loading', updates).includes('po pobraniu pełnego opracowania'));

// Older records without stable fact IDs can still match exact text; differing
// numbers and claims must never be collapsed by an approximate text match.
const missingIds = { perspective_version: 1, perspective_sections: { LEFT: [
  { text_pl: '  Ten sam   fakt. ' }, { text_pl: 'Zatrzymano 8 osób.' }, { text_pl: 'Zatrzymano 10 osób.' } ] } };
let output = perspectiveSectionsHtml(missingIds, 'ready', [
  { perspective_sections: { LEFT: [{ text_pl: 'Ten sam fakt.' }, { text_pl: 'Zatrzymano 8 osób.' }] } } ]);
assert(!output.includes('Ten sam') && !output.includes('Zatrzymano 8 osób.'));
assert(output.includes('Zatrzymano 10 osób.'));
// Stable identity still works when the wording was formatted differently.
output = perspectiveSectionsHtml({ perspective_version: 1, perspective_sections: { RIGHT: [newRight] } },
  'ready', [{ promoted_facts: [{ ...newRight, text_pl: 'Szersze potwierdzenie tego samego faktu.' }] }]);
assert.strictEqual(output, '', 'empty groups leave no empty tabs or section heading');
// State-only topics hide updates, so their current state reports stay visible.
const stateOnly = { ...model, stateOnly: true, updates: [{ perspective_sections: { STATE: [newState] } }],
  summary: { perspective_version: 1, coverage_mode: 'STATE_ONLY', shared_available: false,
    perspective_sections: { STATE: [newState] } } };
assert(dialogHtml(stateOnly).includes(newState.text_pl));
assert.strictEqual(perspectiveSectionsHtml({ perspective_sections: summary.perspective_sections }, 'ready', updates), '');
console.log('Perspective updates: real OS82 regression, no repeated timeline facts, all profiles/history, immutable data and read state — OK.');
`, context);
