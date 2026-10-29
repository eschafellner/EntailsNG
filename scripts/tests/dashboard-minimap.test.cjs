// Run with: node --test scripts/tests/dashboard-minimap.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/dashboard.js'), 'utf8');

function element(tag = 'div') {
  const el = { tagName: tag.toUpperCase(), children: [], dataset: {}, style: {}, className: '', textContent: '', htmlWrites: [],
    appendChild(child) { this.children.push(child); return child; },
    replaceChildren(...nodes) { this.children = nodes; },
    addEventListener() {}, classList: { add() {}, remove() {}, toggle() {} } };
  Object.defineProperty(el, 'innerHTML', { get() { return this.htmlWrites.at(-1) || ''; }, set(v) { this.htmlWrites.push(String(v)); } });
  return el;
}

test('Hinweis „Sitzplan nicht konfiguriert“ wird als Text eingesetzt (F-035)', async () => {
  const container = element();
  container.dataset = { eventId: '3', notConfiguredText: '<img src=x onerror=alert(1)>' };
  const context = vm.createContext({
    document: { getElementById: id => (id === 'minimap-container' ? container : null), createElement: element,
      addEventListener() {}, querySelectorAll: () => [] },
    window: {}, console, setInterval() {}, setTimeout() {},
    fetch: () => Promise.resolve({ json: async () => ({ cells: [] }) }),
  });
  vm.runInContext(source, context);
  vm.runInContext('initMinimap()', context);
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(container.htmlWrites, []);
  assert.equal(container.children.length, 1);
  assert.equal(container.children[0].className, 'minimap-empty');
  assert.equal(container.children[0].textContent, '<img src=x onerror=alert(1)>');
});
