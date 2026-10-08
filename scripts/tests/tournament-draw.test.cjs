const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../static/js/tournament-draw.js'), 'utf8');

function page(valid = true) {
  const ids = ['draw-edit-form', 'draw-publish-form', 'draw-open-confirm', 'draw-close-confirm',
    'draw-confirm', 'draw-publish-submit', 'draw-dirty-notice'];
  const elements = Object.fromEntries(ids.map(id => [id, {hidden: false, disabled: false,
    addEventListener(name, callback) { this[name] = callback; },
    focus() { this.focused = true; }, reportValidity() { return valid; }}]));
  vm.runInNewContext(source, {document: {getElementById: id => elements[id]}});
  return elements;
}

test('publication requires the inline confirmation and preserves keyboard focus', () => {
  const elements = page();
  assert.equal(elements['draw-confirm'].hidden, true);
  elements['draw-open-confirm'].click();
  assert.equal(elements['draw-confirm'].hidden, false);
  assert.equal(elements['draw-publish-submit'].focused, true);
  elements['draw-close-confirm'].click();
  assert.equal(elements['draw-confirm'].hidden, true);
  assert.equal(elements['draw-open-confirm'].focused, true);
});

test('missing conflict approval or reason prevents opening the confirmation', () => {
  const elements = page(false);
  elements['draw-open-confirm'].click();
  assert.equal(elements['draw-confirm'].hidden, true);
});

test('changed clan or seed policy disables publication until the preview is updated', () => {
  for (const name of ['clan_14', 'respect_seeds', 'avoid_clans']) {
    const elements = page();
    elements['draw-edit-form'].change({target: {name}});
    assert.equal(elements['draw-open-confirm'].disabled, true);
    assert.equal(elements['draw-publish-submit'].disabled, true);
    assert.equal(elements['draw-dirty-notice'].hidden, false);
    let blocked = false;
    elements['draw-publish-form'].submit({preventDefault() { blocked = true; }});
    assert.equal(blocked, true);
  }
});

test('choosing swap candidates does not change the approved draw by itself', () => {
  const elements = page();
  elements['draw-edit-form'].change({target: {name: 'swap_first'}});
  assert.equal(elements['draw-open-confirm'].disabled, false);
});

test('submitting disables the button to suppress repeated clicks', () => {
  const elements = page();
  elements['draw-publish-form'].submit({preventDefault() { assert.fail('Valid publication blocked'); }});
  assert.equal(elements['draw-publish-submit'].disabled, true);
});
