// Run with: node --test scripts/tests/checkin-scanner.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/checkin-scanner.js'), 'utf8');

function setup() {
  let now = 10000;
  let timerId = 0;
  const timers = new Map();
  const elements = new Map();
  const requests = [];
  const updates = [];
  const listeners = {};
  const element = id => {
    if (!elements.has(id)) {
      const classes = new Set();
      const attrs = {};
      elements.set(id, {
        textContent: '', value: '', hidden: false, disabled: false, style: {}, dataset: {},
        classList: { toggle(name, on) { on ? classes.add(name) : classes.delete(name); },
          contains: name => classes.has(name), add: name => classes.add(name), remove: name => classes.delete(name) },
        setAttribute: (name, value) => { attrs[name] = value; },
        getAttribute: name => attrs[name],
        addEventListener(name, callback) { this[name] = callback; }
      });
    }
    return elements.get(id);
  };
  element('scanner-feedback-texts').textContent = JSON.stringify(Object.fromEntries(
    ['ready', 'checking', 'waiting', 'success', 'already', 'checkout', 'rejected', 'limited', 'unknown',
      'unconfirmed', 'network', 'pause', 'next', 'seat', 'time', 'no_guest'].map(key => [key, key])));
  const context = vm.createContext({
    document: {
      cookie: '', getElementById: element,
      querySelector: selector => selector === '.scanner-container' ? element('container') : null,
      querySelectorAll: selector => selector === '.guest-row' ? [element('row')] : [],
      addEventListener: (name, cb) => { listeners[name] = cb; }
    },
    window: {}, navigator: {}, console, AbortController, URLSearchParams,
    Date: { now: () => now },
    setTimeout: (callback, delay) => { timers.set(++timerId, { at: now + delay, callback }); return timerId; },
    clearTimeout: id => timers.delete(id),
    fetch: (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })),
    updates
  });
  vm.runInContext(source, context);
  vm.runInContext('updateLocalTableStatus = (...args) => updates.push(args); loadGuestPage = () => {};', context);
  return {
    context, requests, updates, element, listeners,
    advance(ms) {
      now += ms;
      for (const [id, timer] of timers) if (timer.at <= now) { timers.delete(id); timer.callback(); }
    },
    async reply(body, status = 200) {
      requests.at(-1).resolve({ ok: status < 400, status, json: async () => body });
      await new Promise(setImmediate);
    }
  };
}

const success = { status: 'success', registration_id: 4, user: 'Gamer', full_name: 'Test Gast',
  seat: 'A-12', ticket: 'Weekend', checked_in_at: '12:34:56', message: 'Gespeichert' };

test('only the confirmed reply turns green; concurrent requests and the reading pause are blocked', async () => {
  const s = setup();
  assert.equal(s.context.sendScanCode('ABCD1234'), true);
  assert.equal(s.element('scan-status-banner').dataset.state, 'checking');
  assert.equal(s.context.toggleCheckIn(4), false);
  assert.equal(s.context.sendScanCode('EFGH5678'), false);
  assert.equal(s.requests.length, 1);
  assert.equal(s.updates.length, 0);
  await s.reply(success);
  assert.equal(s.element('scan-status-banner').dataset.state, 'success');
  assert.match(s.element('scan-result-summary').textContent, /Gamer.*A-12.*12:34:56/);
  assert.equal(s.element('scan-result-card').classList.contains('is-prominent'), true);
  assert.equal(s.context.sendScanCode('EFGH5678'), false);
  s.advance(3000);
  assert.equal(s.element('scan-result-card').classList.contains('is-prominent'), false);
  assert.equal(s.element('scan-status-banner').dataset.state, 'success');
  assert.equal(s.context.sendScanCode('EFGH5678'), true);
});

test('camera ignores a held QR even after the pause; removal allows a deliberate rescan', async () => {
  const s = setup();
  s.context.handleCameraCode('ABCD1234');
  await s.reply(success);
  for (let i = 0; i < 50; i++) { s.advance(100); s.context.handleCameraCode('ABCD1234'); }
  assert.equal(s.requests.length, 1);
  assert.equal(s.element('scan-status-banner').dataset.state, 'success');
  s.advance(1600);
  s.context.handleCameraCode('ABCD1234');
  assert.equal(s.requests.length, 2);
  await s.reply({ ...success, status: 'already_checked_in' });
  assert.equal(s.element('scan-status-banner').dataset.state, 'warning');
  assert.equal(s.element('scan-result-title').textContent, 'already');
});

test('camera can accept a different guest after the reading pause', async () => {
  const s = setup();
  s.context.handleCameraCode('ABCD1234');
  await s.reply(success);
  s.advance(3000);
  s.context.handleCameraCode('EFGH5678');
  assert.equal(s.requests.length, 2);
});

test('rejection messages are text; subsequent invalid codes clear previous guest details', async () => {
  const s = setup();
  s.context.sendScanCode('ABCD1234');
  await s.reply({ ...success, status: 'unpaid', message: '<img src=x onerror=alert(1)>' }, 400);
  assert.equal(s.element('scan-status-banner').dataset.state, 'error');
  assert.equal(s.element('scan-result-message').textContent, '<img src=x onerror=alert(1)>');
  assert.equal(s.updates.length, 0);
  s.advance(3000);
  s.context.sendScanCode('INVALID');
  await s.reply({ status: 'error', message: 'Nicht gefunden' }, 404);
  assert.equal(s.element('scan-details-box').hidden, true);
  assert.equal(s.element('scan-result-summary').hidden, true);
  assert.equal(s.element('res-user').textContent, '—');
});

test('lost replies, timeouts, server errors and login redirects never imply successful check-in', async () => {
  for (const mode of ['lost', 'timeout', 'server', 'login']) {
    const s = setup();
    s.context.sendScanCode('ABCD1234');
    if (mode === 'lost') s.requests[0].reject(new Error('offline'));
    if (mode === 'timeout') {
      s.requests[0].options.signal.addEventListener('abort', () => s.requests[0].reject(new Error('timeout')));
      s.advance(15000);
    }
    if (mode === 'server') s.requests[0].resolve({ status: 500 });
    if (mode === 'login') s.requests[0].resolve({ status: 200, redirected: true });
    await new Promise(setImmediate);
    assert.equal(s.element('scan-result-title').textContent, 'unconfirmed', mode);
    assert.equal(s.element('scan-status-banner').dataset.state, 'error', mode);
    assert.equal(s.updates.length, 0, mode);
    s.advance(3000);
    assert.equal(s.context.sendScanCode('ABCD1234'), true, mode);
  }
});

test('table buttons share feedback and distinguish check-out', async () => {
  const s = setup();
  s.context.toggleCheckIn(4);
  await s.reply({ ...success, is_checked_in: false, checked_in_at: null });
  assert.equal(s.element('scan-result-title').textContent, 'checkout');
  assert.equal(s.element('scan-status-banner').dataset.state, 'warning');
  assert.equal(s.updates[0][1], false);
});

test('search Enter uses the idempotent scan endpoint even when the displayed row is stale', () => {
  const s = setup();
  s.element('guest-table-body').dataset.matchCount = '1';
  s.element('row').setAttribute('data-code', 'ABCD1234');
  s.element('row').setAttribute('data-checked-in', 'false');
  s.listeners.DOMContentLoaded();
  s.element('guest-search-input').keydown({ key: 'Enter', preventDefault() {} });
  assert.equal(s.requests.length, 1);
  assert.equal(s.requests[0].url, '/api/check-in/scan/');
  assert.equal(JSON.parse(s.requests[0].options.body).code, 'ABCD1234');
});
