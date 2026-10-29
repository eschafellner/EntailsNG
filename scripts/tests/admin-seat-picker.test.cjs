// Run with: node --test scripts/tests/admin-seat-picker.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/admin-seat-picker.js'), 'utf8');

// Minimales DOM: innerHTML wird nur protokolliert, nie geparst. Ein sicherer Picker
// darf Serverdaten ausschließlich über textContent/title/addEventListener ausgeben.
function makeElement(tag) {
  const el = {
    tagName: tag.toUpperCase(), children: [], style: {}, dataset: {}, title: '', textContent: '',
    listeners: {}, htmlWrites: [],
    appendChild(child) { this.children.push(child); return child; },
    replaceChildren(...nodes) { this.children = nodes; this.textContent = ''; },
    addEventListener(name, cb) { this.listeners[name] = cb; },
    setAttribute(name, value) { this[`attr:${name}`] = String(value); },
  };
  Object.defineProperty(el, 'innerHTML', {
    get() { return this.htmlWrites.at(-1) || ''; },
    set(value) { this.htmlWrites.push(String(value)); },
  });
  return el;
}

function setup(planResponse) {
  const container = makeElement('div');
  container.dataset = { eventId: '7', regId: '42', username: "gast'><img src=x onerror=alert(1)>" };
  const calls = [];
  const context = vm.createContext({
    document: {
      cookie: '',
      getElementById: id => (id === 'modal-grid-container' ? container : null),
      querySelector: () => null,
      createElement: makeElement,
    },
    confirm: () => false,
    fetch: () => Promise.resolve({ json: async () => planResponse }),
    console,
  });
  vm.runInContext(source, context);
  vm.runInContext('selectSeatForUser = (...args) => calls.push(args);', Object.assign(context, { calls }));
  return { container, calls, context };
}

const flush = () => new Promise(resolve => setImmediate(resolve));

function allNodes(root) {
  const out = [];
  const walk = node => { out.push(node); node.children.forEach(walk); };
  walk(root);
  return out;
}

const SEAT_PAYLOAD = "',import('//a.bc'),'";
const CELL_PAYLOAD = '<svg onload=alert()>';

test('Sitz- und Beschriftungstexte werden nur als Text ausgegeben', async () => {
  const { container, calls, context } = setup({
    rows: 1, columns: 3,
    cells: [
      { x: 1, y: 1, cell_type: 'SEAT', seat_label: SEAT_PAYLOAD, status: 'FREE', occupied_by: null },
      { x: 2, y: 1, cell_type: 'SEAT', seat_label: CELL_PAYLOAD, status: 'FREE', occupied_by: null },
      { x: 3, y: 1, cell_type: 'LABEL', text_label: '<b>Bühne</b>' },
    ],
  });
  vm.runInContext('loadModalGrid()', context);
  await flush(); await flush();

  const nodes = allNodes(container);
  for (const node of nodes) {
    for (const html of node.htmlWrites) {
      assert.ok(!html.includes(SEAT_PAYLOAD) && !html.includes(CELL_PAYLOAD) && !html.includes('<b>'),
        `Serverdaten dürfen nicht als HTML gesetzt werden: ${html.slice(0, 120)}`);
    }
  }
  const texts = nodes.map(node => node.textContent);
  assert.ok(texts.includes(SEAT_PAYLOAD));
  assert.ok(texts.includes(CELL_PAYLOAD));
  assert.ok(texts.includes('<b'), 'Beschriftung wird wie bisher auf zwei Zeichen gekürzt');
  assert.ok(nodes.some(node => node.title === `${SEAT_PAYLOAD} (FREE)`));

  const seat = nodes.find(node => node.textContent === SEAT_PAYLOAD);
  assert.equal(typeof seat.listeners.click, 'function', 'Klick über addEventListener, nicht onclick-Attribut');
  seat.listeners.click();
  assert.equal(JSON.stringify(calls), JSON.stringify([[42, 1, 1, SEAT_PAYLOAD, "gast'><img src=x onerror=alert(1)>"]]));
});

test('Gesperrte Plätze sind nicht anklickbar', async () => {
  const { container, context } = setup({
    rows: 1, columns: 1,
    cells: [{ x: 1, y: 1, cell_type: 'SEAT', seat_label: 'A1', status: 'BLOCKED', occupied_by: null }],
  });
  vm.runInContext('loadModalGrid()', context);
  await flush(); await flush();
  const seat = allNodes(container).find(node => node.textContent === 'A1');
  assert.ok(seat);
  assert.equal(seat.listeners.click, undefined);
});

test('Fehlermeldungen der API werden als Text angezeigt', async () => {
  const { container, context } = setup({ error: '<img src=x onerror=alert(1)>' });
  vm.runInContext('loadModalGrid()', context);
  await flush(); await flush();
  assert.deepEqual(container.htmlWrites, []);
  assert.equal(container.textContent, '<img src=x onerror=alert(1)>');
});
