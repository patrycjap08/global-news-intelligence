// Run with: node test_frontend_read_state.js
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const context = { window: { GNI_CONFIG: {}, localStorage: { getItem: () => null, setItem: () => {} } }, document: {}, console, assert };
vm.createContext(context);
vm.runInContext(fs.readFileSync('app/app.js', 'utf8').split("document.addEventListener('click'")[0], context);
vm.runInContext(`
loadDemoData();
const topic = state.topics[0];
const base = {summary_pl: 'Pełna synteza. '.repeat(100)};
const previous = {status: 'NEW_INFORMATION', update_id: 'before', new_information_pl: 'Poprzednie ustalenie.', generated_at: '2026-10-01T10:00:00Z'};
const stored = {base_summary: base, updates: [previous], latest_update: previous};
state.summaries.set(topic.topic_id, {version: 2, summary: stored});
let model = topicModel(topic);
assert(!isTopicRead(model));
markTopicRead(model);
assert(isTopicRead(model));
// New attachment, still waiting for analysis: keep the read mark.
const extra = {...state.articles[0], article_id: 'confirmation'};
state.articles = [...state.articles, extra];
state.links = [...state.links, {topic_id: topic.topic_id, article_id: extra.article_id}];
invalidateViewCache();
model = topicModel(topic);
assert(isTopicRead(model));
// Analysis records no new information, but increments the internal version.
state.summaries.set(topic.topic_id, {version: 3, updated_at: '2099-01-01T00:00:00Z', summary: {...stored, last_analysis: {status: 'NO_NEW_INFORMATION'}}});
invalidateViewCache();
model = topicModel(topic);
assert(isTopicRead(model));
state.hideRead = true;
assert(!filteredModels([model]).length);
// The static preview and full detail must agree on the read state.
state.summaries.set(topic.topic_id, {version: 3, summary: {base_summary: {summary_pl: base.summary_pl.slice(0,650)}, latest_update: previous}});
assert(isTopicRead(topicModel(topic)));
// A genuine new accepted update makes it unread, even with the same articles.
const next = {...previous, update_id: 'after', new_information_pl: 'Nowy fakt.', generated_at: '2099-01-01T10:00:00Z'};
state.summaries.set(topic.topic_id, {version: 4, summary: {...stored, updates: [previous, next], latest_update: next}});
model = topicModel(topic);
assert(!isTopicRead(model));
assert.strictEqual(filteredModels([model]).length, 1);
markTopicRead(model);
assert(isTopicRead(model));
// Existing devices keep read marks from the previous article-based format.
state.readTopics[topic.topic_id] = {version: 2, article_ids: ['old-article'], read_at: '2026-10-02T10:00:00Z'};
state.summaries.set(topic.topic_id, {version: 3, summary: {...stored, last_analysis: {status: 'NO_NEW_INFORMATION'}}});
assert(isTopicRead(topicModel(topic)));
state.summaries.set(topic.topic_id, {version: 4, summary: {...stored, updates: [previous, next], latest_update: next}});
assert(!isTopicRead(topicModel(topic)));
// First synthesis without updates also stays read on confirming analyses.
state.summaries.set(topic.topic_id, {version: 1, summary: {base_summary: base, updates: []}});
markTopicRead(topicModel(topic));
state.summaries.set(topic.topic_id, {version: 2, summary: {base_summary: base, updates: [], last_analysis: {status: 'NO_NEW_INFORMATION'}}});
assert(isTopicRead(topicModel(topic)));
state.summaries.set(topic.topic_id, {version: 3, summary: {base_summary: {summary_pl: 'Zmieniona synteza.'}, updates: []}});
assert(!isTopicRead(topicModel(topic)));
console.log('Read state: attachments, no-change analyses, accepted updates, preview/full, hide-read and legacy migration — OK.');
`, context);
