const fs = require('fs'), vm = require('vm'), assert = require('assert');
const fixture = JSON.parse(fs.readFileSync('test_data/pegasus_display_20261021.json', 'utf8'));
const context = {fixture, assert, console, window: {GNI_CONFIG: {}, localStorage: {getItem: () => null, setItem: () => {}}}, document: {}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('app/app.js', 'utf8').split("document.addEventListener('click'")[0], context);
vm.runInContext(`
const before = JSON.stringify(fixture);
state.topics = [fixture.topic]; state.articles = fixture.articles; state.links = fixture.links;
state.summaries = new Map([[fixture.topic.topic_id, fixture.summary]]); invalidateViewCache();
const model = topicModel(fixture.topic);
markTopicRead(model);
assert(model.summary.summary_pl.includes('Według PAP:'));
for (const detailsState of ['ready', 'loading', 'error']) {
  const html = dialogHtml(model, {detailsState});
  assert(!html.includes('class="dialog-lead"'), 'Description stays hidden throughout detail loading');
  assert(!html.includes('Według PAP:') && !html.includes('Według Onet:'));
  assert(html.includes('sejmowa komisja śledcza ds. Pegasusa'));
  assert(html.includes('131. posiedzenie'));
  assert(html.includes('sześcioro członków komisji'));
  for (const article of fixture.articles) assert(html.includes(escapeHtml(article.original_url)));
}
assert(!cardHtml(model, 0).includes('class="card-dek"'));
assert(isTopicRead(model), 'A display change must not mark a read topic as unread');
assert.strictEqual(JSON.stringify(fixture), before, 'Stored source attribution and history remain intact');
assert.strictEqual(withoutPublisherPrefixes('Według lekarza: Pacjent wymaga leczenia.'), 'Według lekarza: Pacjent wymaga leczenia.');
assert.strictEqual(withoutPublisherPrefixes('Według PAP: Minister powiedział, że badanie trwa.'), 'Minister powiedział, że badanie trwa.');
assert.strictEqual(withoutPublisherPrefixes('Według agencji PAP: Decyzja zapadła.\\n\\nWedług Onet, Głosowanie zakończono.'), 'Decyzja zapadła.\\n\\nGłosowanie zakończono.');
assert.strictEqual(withoutPublisherPrefixes('Według PAP-owskiego informatora: sprawa trwa.'), 'Według PAP-owskiego informatora: sprawa trwa.');
assert.strictEqual(withoutObviousDefinitions('USA (Stany Zjednoczone Ameryki) i UE (Unia Europejska) prowadzą rozmowy.'), 'USA i UE prowadzą rozmowy.');
assert.strictEqual(withoutObviousDefinitions('USA (po ostatnich wyborach) zmieniły stanowisko.'), 'USA (po ostatnich wyborach) zmieniły stanowisko.');
assert.strictEqual(withoutObviousDefinitions('USPS (amerykańska poczta) dostarczyło listy.'), 'USPS (amerykańska poczta) dostarczyło listy.');
state.articles = [...state.articles, {source_id: 'punctuation', source_name: 'News (World).+'}]; invalidateViewCache();
assert.strictEqual(withoutPublisherPrefixes('Według News (World).+: Reporter opisał wydarzenie.'), 'Reporter opisał wydarzenie.');
assert(listValue([{text_pl: 'Minister powiedział, że badanie trwa.', article_ids: [fixture.articles[0].article_id]}]).includes(fixture.articles[0].source_name));
for (const source_id of ['caixin', 'kommersant']) {
  const article = {article_id: source_id, source_id, source_name: source_id, source_profile: 'STATE_ALIGNED'};
  state.articles = [article]; invalidateViewCache();
  assert(!isStateSource(articleMap().get(source_id)), 'Private ownership must not retain a legacy state label');
  assert.strictEqual(article.source_profile, 'STATE_ALIGNED', 'Do not mutate the downloaded record');
}
`, context);
console.log('Clean narrative: actual Pegasus synthesis, no publisher prefixes or title descriptions; source links, speaker attribution and read state retained.');
