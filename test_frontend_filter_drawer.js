// Run with: node test_frontend_filter_drawer.js
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const elements = new Map(), storage = new Map();
let writes = 0;
function element(selector) {
  if (!elements.has(selector)) elements.set(selector, {
    textContent: '', innerHTML: '', hidden: false, checked: false, open: false,
    classList: { toggle() {} }, attrs: {}, querySelectorAll: () => [],
    setAttribute(name, value) { this.attrs[name] = value; },
    closest() { return { classList: { toggle() {} } }; },
    showModal() { this.open = true; }, close() { this.open = false; }, focus() {},
  });
  return elements.get(selector);
}
const context = {
  window: { GNI_CONFIG: {}, localStorage: {
    getItem: key => storage.get(key) || null,
    setItem(key, value) { storage.set(key, value); writes++; },
  } },
  document: { querySelector: element, querySelectorAll: () => [] }, console, assert,
};
vm.createContext(context);
const source = fs.readFileSync('app/app.js', 'utf8').split("document.addEventListener('click'")[0];
vm.runInContext(source, context);
const run = code => vm.runInContext(code, context);
run('loadDemoData(); render();');
const original = run('JSON.stringify(filterSelection())');
run('openFilters(); changeDraftFilter("category", "GOSPODARKA");');
assert.strictEqual(run('JSON.stringify(filterSelection())'), original, 'Draft must not change the live selection');
assert.strictEqual(writes, 0, 'Editing a draft never writes preferences');
assert.strictEqual(run('filteredModels().length'), 2);
assert.strictEqual(elements.get('#filters-apply').textContent, 'Pokaż 1 temat');
assert.strictEqual(elements.get('#sources-summary').textContent, '4 źródła · 6 artykułów',
  'Publisher counts still describe the applied selection');
assert.strictEqual(run('state.categories === filterDraft.categories'), false);

run('changeDraftFilter("category", "POLITYKA");');
assert.strictEqual(elements.get('#category-match-options').hidden, false);
assert.strictEqual(elements.get('#filters-apply').textContent, 'Pokaż 2 tematy');
run('changeDraftFilter("match", "ALL"); changeDraftFilter("profile", "RIGHT");');
assert.strictEqual(elements.get('#filters-apply').textContent, 'Pokaż 1 temat');
run('applyFilters();');
assert.strictEqual(run('filterDraft'), null);
assert.strictEqual(run('filteredModels().length'), 1);
assert.strictEqual(run('state.categoryMatch'), 'ALL');
assert.strictEqual(run('state.profile'), 'RIGHT');
assert.strictEqual(elements.get('#filter-count').textContent, 3);
assert(elements.get('#active-filters').innerHTML.includes('Wszystkie wybrane kategorie'));
assert.strictEqual(JSON.parse(storage.get('gni.filters.v1')).categoryMatch, 'ALL');
assert.strictEqual(elements.get('#sources-summary').textContent, '2 źródła · 3 artykuły');

run('removeAppliedFilter("category", "GOSPODARKA");');
assert.strictEqual(run('filteredModels().length'), 2);
assert.strictEqual(elements.get('#filter-count').textContent, 2);
run('state.search="BBC"; state.sort="newest"; clearAppliedFilters();');
assert.strictEqual(run('state.search'), 'BBC', 'Clearing sheet filters preserves the separately editable search');
assert.strictEqual(run('state.sort'), 'newest');
assert.strictEqual(elements.get('#filter-count').hidden, true);
assert.strictEqual(run('filteredModels().length'), 1);
run('state.search=""; render();');

// One article is linked to both demo topics; source bars must not double it.
assert.strictEqual(elements.get('#visible-edition-counts').textContent, '2 tematy · 6 artykułów');
assert.strictEqual(elements.get('#sources-summary').textContent, '4 źródła · 6 artykułów');
assert(elements.get('#source-list').innerHTML.includes('Fox News</span><small>2 artykuły'));
assert(!elements.get('#source-list').innerHTML.includes('data-profile'));
assert(!elements.get('#source-list').innerHTML.includes('data-category'));
run('openFilters(); changeDraftFilter("category", "POLSKA");');
assert.strictEqual(elements.get('#filters-apply').textContent, 'Pokaż 0 tematów');
assert.strictEqual(run('filteredModels().length'), 2, 'An empty preview is not an applied empty list');

// Exact matching rules use the supplied draft rather than the live ANY mode.
const selected = run('filteredModels(allTopicModels(), {filters:{...state,...filterDraft}}).length');
assert.strictEqual(selected, 0);
run('filterDraft=defaultFilterSelection(); changeDraftFilter("read", true);');
assert.strictEqual(run('state.hideRead'), false);
assert.strictEqual(run('activeFilterItems(filterDraft).length'), 1);
run('applyFilters();');
assert.strictEqual(run('state.hideRead'), true);
run('removeAppliedFilter("read", "unread");');
assert.strictEqual(run('state.hideRead'), false);

// Refreshing data while the sheet is open keeps the draft and updates its preview.
run(`openFilters(); changeDraftFilter('category','GOSPODARKA');
state.topics=state.topics.map(topic=>({...topic,categories:['POLITYKA']})); render();`);
assert.strictEqual(run('filterDraft.categories[0]'), 'GOSPODARKA');
assert.strictEqual(elements.get('#filters-apply').textContent, 'Pokaż 0 tematów');
assert.strictEqual(run('state.categories.length'), 0);
console.log('Filter drawer: draft isolation, OR/AND previews, apply/persistence, chips/reset, refresh and unique read-only publisher counts — OK.');
