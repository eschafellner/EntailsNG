const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/seating.js'), 'utf8');

function setup(mode = false) {
  const nodes = new Map();
  const htmlWrites = [];
  const requests = [];
  function element(tag = 'div') {
    return {
      tag, children: [], style: {}, textContent: '', attributes: {},
      classList: {add() {}},
      setAttribute(name, value) {this.attributes[name] = value;},
      set innerHTML(value) {htmlWrites.push(value); this.children = [];},
      appendChild(child) {
        if (child.tag === 'fragment') this.children.push(...child.children);
        else this.children.push(child);
        if (child.id) nodes.set(child.id, child);
      },
      addEventListener() {},
    };
  }
  for (const id of ['seating-grid', 'seating-status', 'reserve-modal', 'reserve-modal-text',
    'btn-confirm-reserve', 'clan-seat-counter', 'clan-seat-deadline', 'clan-seat-feedback',
    'clan-seat-confirm', 'clan-seat-refresh']) nodes.set(id, element());
  if (mode) {
    nodes.set('clan-selection-config', {textContent: JSON.stringify({clanId: 7, saveUrl: '/save/',
      counter: '{limit}/{selected}/{remaining}', until: '{date}', tooltip: 'Clan {clan}',
      limitMessage: 'Kontingent erreicht', network: 'Netzwerkfehler'})});
  }
  const context = vm.createContext({
    document: {getElementById: id => nodes.get(id), createElement: element,
      createDocumentFragment: () => element('fragment'), addEventListener() {}, body: element()},
    window: {location: {search: ''}, innerWidth: 1200, addEventListener() {}},
    fetch: (url, options) => new Promise(resolve => requests.push({url, options, resolve})),
    URLSearchParams, AbortController, console,
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  });
  vm.runInContext(source, context);
  context.window.initSeatingViewer({eventId: 1, isUserLoggedIn: true, csrfToken: 'test',
    clanTooltip: 'Vorgemerkt für Clan {clan}', rawConfirmText: 'Reservieren: {seat}'});
  return {nodes, requests, htmlWrites, async reply(body) {
    requests.at(-1).resolve({ok: true, json: async () => body});
    await new Promise(setImmediate);
  }};
}

function plan(cells, selection) {
  return {columns: 2, rows: 1, cells, clan_selection: selection};
}
const held = {id: 1, x: 1, y: 1, cell_type: 'SEAT', seat_label: 'A1', status: 'CLAN_HELD',
  hold_clan_id: 7, hold_clan_name: 'Wolves', hold_clan_tag: 'NW', can_claim_hold: false};

test('Clan names and seat labels remain literal text in tooltips, cells and feedback', async () => {
  const ui = setup();
  const unsafe = '<img src=x onerror=alert(1)>';
  await ui.reply(plan([{...held, seat_label: unsafe, hold_clan_name: unsafe}]));
  const cell = ui.nodes.get('seating-grid').children[0];
  assert.equal(cell.title, 'Vorgemerkt für Clan ' + unsafe);
  assert.equal(cell.children.at(-1).textContent, unsafe);
  cell.onclick({stopPropagation() {}});
  assert.equal(ui.nodes.get('seating-toast').textContent, '✓ Vorgemerkt für Clan ' + unsafe);
  assert.ok(ui.htmlWrites.every(value => !value.includes(unsafe)));
});

test('A clan member can open the normal reservation confirmation from a held seat', async () => {
  const ui = setup();
  await ui.reply(plan([{...held, can_claim_hold: true}]));
  ui.nodes.get('seating-grid').children[0].onclick({stopPropagation() {}});
  assert.equal(ui.nodes.get('reserve-modal').style.display, 'flex');
  assert.equal(ui.nodes.get('reserve-modal-text').innerText, 'Reservieren: A1');
});

test('Clan selection enforces its quota and submits a single batch with its revision', async () => {
  const ui = setup(true);
  const free = {...held, status: 'FREE'};
  await ui.reply(plan([free, {...free, id: 2, x: 2, seat_label: 'A2'}],
    {limit: 1, claimed: 0, selected: [], consumed_open: [], enabled: true, revision: 'initial'}));
  assert.equal(ui.requests[0].url, '/seating/api/plan/1/?clan=7');
  ui.nodes.get('seating-grid').children[0].onclick({stopPropagation() {}});
  ui.nodes.get('seating-grid').children[1].onclick({stopPropagation() {}});
  assert.equal(ui.nodes.get('clan-seat-counter').textContent, '1/1/0');
  assert.equal(ui.nodes.get('seating-toast').textContent, '⚠️ Kontingent erreicht');
  ui.nodes.get('clan-seat-confirm').onclick();
  const request = ui.requests.at(-1);
  assert.equal(request.url, '/save/');
  assert.equal(request.options.method, 'POST');
  assert.deepEqual(JSON.parse(request.options.body), {event_id: 1, cell_ids: [1], revision: 'initial'});
  assert.equal(ui.nodes.get('clan-seat-confirm').disabled, true);
});

test('Pending and prepaid clan seats show their status and cannot open personal booking', async () => {
  for (const status of ['CLAN_PAYMENT_PENDING', 'CLAN_PAID']) {
    const ui = setup();
    const tooltip = status + ' <unsafe clan>';
    await ui.reply(plan([{...held, status, hold_tooltip: tooltip}]));
    const cell = ui.nodes.get('seating-grid').children[0];
    assert.equal(cell.title, tooltip);
    assert.equal(cell.children.at(-1).textContent, 'A1');
    cell.onclick({stopPropagation() {}});
    assert.notEqual(ui.nodes.get('reserve-modal').style.display, 'flex');
    assert.ok(ui.htmlWrites.every(value => !value.includes('<unsafe clan>')));
  }
});

test('A fixed clan payment disables changes to the seat selection', async () => {
  const ui = setup(true);
  await ui.reply(plan([{...held, status: 'CLAN_PAID'}],
    {limit: 8, claimed: 0, selected: [1], consumed_open: [], enabled: false, revision: 'locked'}));
  assert.equal(ui.nodes.get('clan-seat-confirm').disabled, true);
  ui.nodes.get('seating-grid').children[0].onclick({stopPropagation() {}});
  ui.nodes.get('clan-seat-confirm').onclick();
  assert.equal(ui.requests.length, 1);
});
