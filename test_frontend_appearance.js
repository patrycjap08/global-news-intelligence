// Run with: node test_frontend_appearance.js
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('app/appearance.js', 'utf8');
const key = 'gni.appearance.v1';

function fixture(saved, blocked = false) {
  const storage = new Map([[key, saved], ['gni.filters.v1', 'saved filters']]);
  const handlers = new Map(), root = { dataset: {} }, meta = {};
  const element = () => ({
    handlers: {}, attrs: {},
    addEventListener(type, listener) { this.handlers[type] = listener; },
    setAttribute(name, value) { this.attrs[name] = value; },
    focus() { this.focused = true; },
  });
  const inputs = ['newspaper', 'minimal', 'night'].map(value => ({ ...element(), value }));
  const button = element(), close = element(), dialog = {
    ...element(), open: false,
    showModal() { this.open = true; },
    close() { this.open = false; this.handlers.close(); },
    querySelector: () => inputs.find(input => input.checked),
    getBoundingClientRect: () => ({ left: 10, top: 10, right: 400, bottom: 600 }),
  };
  const document = { documentElement: root,
    querySelector: selector => ({
      'meta[name="theme-color"]': {setAttribute: (name, value) => { meta[name] = value; }},
      '#appearance-button': button, '#appearance-close': close, '#appearance-dialog': dialog,
    })[selector],
    querySelectorAll: () => inputs,
    addEventListener: (type, listener) => handlers.set(`document:${type}`, listener),
  };
  const window = {
    localStorage: {
      getItem(name) { if (blocked) throw new Error('Storage unavailable'); return storage.get(name); },
      setItem(name, value) { if (blocked) throw new Error('Storage unavailable'); storage.set(name, value); },
    },
    addEventListener: (type, listener) => handlers.set(`window:${type}`, listener),
  };
  vm.runInNewContext(source, { document, window, fetch: () => { throw new Error('Appearance must not fetch news'); } });
  return { storage, root, meta, inputs, button, dialog,
    boot: () => handlers.get('document:DOMContentLoaded')(),
    choose: value => dialog.handlers.change({target: {value, matches: () => true}}),
    external: (eventKey, newValue) => handlers.get('window:storage')({key: eventKey, newValue}),
  };
}

// A returning reader gets the saved colors before content starts to paint.
const returning = fixture('night');
assert.strictEqual(returning.root.dataset.theme, 'night');
assert.strictEqual(returning.meta.content, '#101822');
returning.boot();
assert.strictEqual(returning.inputs.find(input => input.checked).value, 'night');
returning.button.handlers.click();
assert.strictEqual(returning.dialog.open, true);
assert.strictEqual(returning.button.attrs['aria-expanded'], 'true');
assert(returning.inputs.find(input => input.value === 'night').focused);
returning.dialog.close();
assert.strictEqual(returning.button.attrs['aria-expanded'], 'false');

// Selecting a style applies immediately, persists, and leaves other settings intact.
returning.choose('minimal');
assert.strictEqual(returning.root.dataset.theme, 'minimal');
assert.strictEqual(returning.meta.content, '#f3f5f7');
assert.strictEqual(returning.storage.get(key), 'minimal');
assert.strictEqual(returning.storage.get('gni.filters.v1'), 'saved filters');
assert.strictEqual(returning.inputs.filter(input => input.checked).length, 1);
assert.strictEqual(fixture(returning.storage.get(key)).root.dataset.theme, 'minimal');

// Fresh devices, malformed values and unavailable storage safely use the default.
for (const saved of [undefined, '', 'unknown', 'toString', '__proto__']) {
  assert.strictEqual(fixture(saved).root.dataset.theme, 'newspaper');
}
const privateMode = fixture('night', true);
privateMode.boot();
privateMode.choose('night');
assert.strictEqual(privateMode.root.dataset.theme, 'night');

// Another tab may change or clear the preference without changing this tab's news.
returning.external('unrelated', 'night');
assert.strictEqual(returning.root.dataset.theme, 'minimal');
returning.external(key, 'night');
assert.strictEqual(returning.root.dataset.theme, 'night');
returning.external(key, null);
assert.strictEqual(returning.root.dataset.theme, 'newspaper');
returning.external(null, null);
assert.strictEqual(returning.root.dataset.theme, 'newspaper');
console.log('Frontend appearance: early restore, radio selection, persistence, safe default, blocked storage and cross-tab sync — OK.');
