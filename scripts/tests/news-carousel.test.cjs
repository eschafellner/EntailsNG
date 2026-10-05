// Run with: node --test scripts/tests/news-carousel.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../static/js/news-carousel.js'), 'utf8');

function setup({ desktop = true, reduced = false, count = 3, brokenImage = false } = {}) {
  const timers = new Map();
  let timerId = 0;
  let now = 0;
  function element() {
    const listeners = {};
    return {
      hidden: false, dataset: {}, textContent: '', attributes: {},
      addEventListener(name, callback) { (listeners[name] ??= []).push(callback); },
      fire(name, event = {}) { for (const callback of listeners[name] || []) callback(event); },
      setAttribute(name, value) { this.attributes[name] = value; },
      classes: new Set(),
      classList: { add(name) { this.owner.classes.add(name); } },
    };
  }
  const root = element();
  root.dataset = { pauseLabel: 'Pause', startLabel: 'Start' };
  root.matches = () => false;
  const track = element();
  track.scrollLeft = 0;
  track.getBoundingClientRect = () => ({ left: 200 });
  track.calls = [];
  track.scrollTo = options => { track.calls.push(options); track.scrollLeft = options.left; track.fire('scroll'); };
  const slides = Array.from({ length: count }, (_, i) => {
    const slide = element();
    slide.classList.owner = slide;
    slide.getBoundingClientRect = () => ({ left: 200 + i * 316 - track.scrollLeft });
    slide.querySelector = () => null;
    return slide;
  });
  const image = element();
  image.complete = brokenImage;
  image.naturalWidth = brokenImage ? 0 : 100;
  image.parentElement = element();
  if (count) slides[0].querySelector = () => image;
  track.querySelectorAll = () => slides;
  const controls = element(), previous = element(), next = element(), rotation = element(), position = element();
  position.dataset.positionLabel = 'von';
  root.querySelector = selector => ({
    '[data-news-track]': track, '[data-news-controls]': controls, '[data-news-rotation]': rotation,
    '[data-news-position]': position, '[data-news-previous]': previous, '[data-news-next]': next,
  })[selector];
  const desktopQuery = element(), reducedQuery = element(), document = element();
  desktopQuery.matches = desktop; reducedQuery.matches = reduced; document.hidden = false;
  document.querySelectorAll = () => [root];
  const window = {
    matchMedia: query => query.includes('reduced-motion') ? reducedQuery : desktopQuery,
    setTimeout(callback, delay) { const id = ++timerId; timers.set(id, { callback, time: now + delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  vm.runInNewContext(source, { document, window });
  return { root, track, slides, controls, previous, next, rotation, position, image, desktopQuery, reducedQuery, document,
    advance(ms) {
      now += ms;
      for (const [id, timer] of Array.from(timers)) {
        if (timer.time <= now) { timers.delete(id); timer.callback(); }
      }
    },
  };
}

test('desktop rotates after eight seconds and wraps to the first article', () => {
  const s = setup();
  s.advance(7999); assert.equal(s.track.calls.length, 0);
  s.advance(1); assert.equal(s.position.textContent, '2 von 3');
  s.advance(8000); assert.equal(s.position.textContent, '3 von 3');
  s.advance(8000); assert.equal(s.position.textContent, '1 von 3');
});

test('mobile and reduced-motion preference never auto-rotate', () => {
  for (const options of [{ desktop: false }, { reduced: true }]) {
    const s = setup(options);
    s.advance(60000);
    assert.equal(s.track.calls.length, 0);
    assert.equal(s.rotation.hidden, true);
    s.next.fire('click');
    assert.equal(s.position.textContent, '2 von 3');
    if (options.reduced) assert.equal(s.track.calls[0].behavior, 'instant');
  }
});

test('manual next, previous, touch, wheel and keyboard focus stop rotation until restarted', () => {
  for (const action of [s => s.next.fire('click'), s => s.previous.fire('click'),
    s => s.track.fire('pointerdown'), s => s.track.fire('wheel'), s => s.root.fire('focusin')]) {
    const s = setup(); action(s);
    const count = s.track.calls.length;
    s.advance(16000);
    assert.equal(s.track.calls.length, count);
    assert.equal(s.rotation.textContent, 'Start');
    s.rotation.fire('click', { detail: 0 });
    s.advance(8000); assert.equal(s.track.calls.length, count + 1);
  }
});

test('first pointer click pauses even though receiving focus also pauses rotation', () => {
  const s = setup();
  s.rotation.fire('pointerdown'); s.root.fire('focusin'); s.rotation.fire('click', { detail: 1 });
  assert.equal(s.rotation.textContent, 'Start');
  s.advance(16000); assert.equal(s.track.calls.length, 0);
  s.rotation.fire('pointerdown'); s.rotation.fire('click', { detail: 1 });
  assert.equal(s.rotation.textContent, 'Pause');
  s.advance(8000); assert.equal(s.track.calls.length, 1);
});

test('hover and a hidden document suspend rotation, with a fresh eight-second interval on return', () => {
  for (const mode of ['hover', 'visibility']) {
    const s = setup();
    if (mode === 'hover') s.root.fire('mouseenter');
    else { s.document.hidden = true; s.document.fire('visibilitychange'); }
    s.advance(20000); assert.equal(s.track.calls.length, 0);
    if (mode === 'hover') s.root.fire('mouseleave');
    else { s.document.hidden = false; s.document.fire('visibilitychange'); }
    s.advance(7999); assert.equal(s.track.calls.length, 0);
    s.advance(1); assert.equal(s.track.calls.length, 1);
  }
});

test('changing screen size or reduced-motion preference cancels pending rotation', () => {
  for (const mode of ['desktop', 'motion']) {
    const s = setup();
    if (mode === 'desktop') { s.desktopQuery.matches = false; s.desktopQuery.fire('change'); }
    else { s.reducedQuery.matches = true; s.reducedQuery.fire('change'); }
    s.advance(16000); assert.equal(s.track.calls.length, 0);
    assert.equal(s.rotation.hidden, true);
  }
});

test('swiping updates the position and makes only the visible article links accessible', () => {
  const s = setup({ desktop: false });
  assert.equal(s.slides[0].inert, false); assert.equal(s.slides[1].inert, true);
  s.track.fire('pointerdown'); s.track.scrollLeft = 316; s.track.fire('scroll'); s.advance(150);
  assert.equal(s.position.textContent, '2 von 3');
  assert.equal(s.slides[0].inert, true); assert.equal(s.slides[1].inert, false);
  assert.equal(s.slides[1].attributes['aria-hidden'], 'false');
});

test('keyboard arrows switch articles and announce the position after rotation pauses', () => {
  const s = setup(); let prevented = false;
  assert.equal(s.position.attributes['aria-live'], 'off');
  s.root.fire('keydown', { key: 'ArrowLeft', preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(s.position.textContent, '3 von 3');
  assert.equal(s.position.attributes['aria-live'], 'polite');
  s.advance(16000); assert.equal(s.track.calls.length, 1);
});

test('one or zero articles need no rotation; broken images gracefully fall back to text', () => {
  for (const count of [0, 1]) {
    const s = setup({ count, brokenImage: true });
    s.advance(16000); assert.equal(s.track.calls.length, 0);
    if (count) {
      assert.equal(s.image.parentElement.hidden, true);
      assert.equal(s.slides[0].classes.has('news-slide-text'), true);
    }
  }
});
