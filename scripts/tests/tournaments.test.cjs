const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/tournaments.js'), 'utf8');

function views({mode = 'SWISS', mobile = true, stored = null, storageUnavailable = false} = {}) {
  const tree = {hidden: false, dataset: {tournamentMode: mode}};
  const list = {hidden: true};
  const buttons = ['tree', 'list'].map(view => ({
    dataset: {matchView: view}, attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, callback) { this[name] = callback; }
  }));
  const document = {
    readyState: 'complete', addEventListener() {},
    querySelectorAll: selector => selector === '[data-match-view]' ? buttons : [],
    getElementById: id => id === 'match-tree' ? tree : id === 'match-list' ? list : null
  };
  let saved;
  const context = {
    document, window: {}, location: {pathname: '/tournaments/test/', hash: ''},
    matchMedia: () => ({matches: mobile}),
    sessionStorage: {
      getItem() { if (storageUnavailable) throw new Error('Unavailable'); return stored; },
      setItem(key, value) { if (storageUnavailable) throw new Error('Unavailable'); saved = JSON.parse(value); }
    }
  };
  vm.runInNewContext(source, context);
  return {tree, list, buttons, saved: () => saved};
}

test('Swiss rankings remain visible on the first mobile visit', () => {
  const ui = views();
  assert.equal(ui.tree.hidden, false);
  assert.equal(ui.list.hidden, true);
  assert.equal(ui.buttons[0].attributes['aria-pressed'], 'true');
});

test('Legacy brackets still default to the mobile match list', () => {
  const ui = views({mode: 'SINGLE_ELIMINATION'});
  assert.equal(ui.tree.hidden, true);
  assert.equal(ui.list.hidden, false);
  assert.equal(ui.buttons[1].attributes['aria-pressed'], 'true');
});

test('A chosen Swiss match list is restored and can switch back to rankings', () => {
  const ui = views({stored: JSON.stringify({view: 'list'})});
  assert.equal(ui.list.hidden, false);
  ui.buttons[0].click();
  assert.equal(ui.tree.hidden, false);
  assert.equal(ui.list.hidden, true);
  assert.equal(ui.saved().view, 'tree');
  assert.equal(ui.buttons[1].attributes['aria-pressed'], 'false');
});

test('Corrupt session state does not hide Swiss rankings', () => {
  const ui = views({stored: '{invalid'});
  assert.equal(ui.tree.hidden, false);
});

test('Unavailable session storage does not prevent changing the view', () => {
  const ui = views({storageUnavailable: true});
  ui.buttons[1].click();
  assert.equal(ui.list.hidden, false);
  assert.equal(ui.tree.hidden, true);
});
