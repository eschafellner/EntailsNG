/* Native touch scrolling; rotation starts by itself only on desktop, elsewhere on request. */
(() => {
  'use strict';

  document.querySelectorAll('[data-news-carousel]').forEach(root => {
    const track = root.querySelector('[data-news-track]');
    if (!track) return;
    const slides = Array.from(track.querySelectorAll('[data-news-slide]'));
    slides.forEach(slide => {
      const image = slide.querySelector('img');
      if (!image) return;
      const fallback = () => {
        image.parentElement.hidden = true;
        slide.classList.add('news-slide-text');
      };
      image.addEventListener('error', fallback);
      if (image.complete && image.naturalWidth === 0) fallback();
    });
    if (slides.length < 2) return;

    const controls = root.querySelector('[data-news-controls]');
    const rotation = root.querySelector('[data-news-rotation]');
    const position = root.querySelector('[data-news-position]');
    const desktop = window.matchMedia('(min-width: 901px) and (hover: hover) and (pointer: fine)');
    const hoverable = window.matchMedia('(hover: hover) and (pointer: fine)');
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let index = 0;
    // null until the visitor decides; until then the device decides.
    let pausedByVisitor = null;
    let hovered = root.matches(':hover');
    let timer = null;
    let scrollTimer = null;
    let pointerRotationState = null;

    const isPaused = () => pausedByVisitor ?? (!desktop.matches || reducedMotion.matches);
    const isRotating = () => !isPaused() && !hovered && !document.hidden;

    function showPosition() {
      position.textContent = `${index + 1} ${position.dataset.positionLabel} ${slides.length}`;
      slides.forEach((slide, i) => {
        // Keep off-screen links out of the tab order and screen-reader flow.
        slide.inert = i !== index;
        slide.setAttribute('aria-hidden', String(i !== index));
      });
    }

    function schedule() {
      window.clearTimeout(timer);
      timer = null;
      rotation.textContent = isPaused() ? root.dataset.startLabel : root.dataset.pauseLabel;
      position.setAttribute('aria-live', isRotating() ? 'off' : 'polite');
      if (isRotating()) timer = window.setTimeout(() => goTo(index + 1), 8000);
    }

    function pause() {
      pausedByVisitor = true;
      schedule();
    }

    function goTo(nextIndex) {
      index = (nextIndex + slides.length) % slides.length;
      const offset = slides[index].getBoundingClientRect().left - track.getBoundingClientRect().left;
      track.scrollTo({ left: track.scrollLeft + offset, behavior: reducedMotion.matches ? 'instant' : 'smooth' });
      showPosition();
      schedule();
    }

    root.querySelector('[data-news-previous]').addEventListener('click', () => {
      pause();
      goTo(index - 1);
    });
    root.querySelector('[data-news-next]').addEventListener('click', () => {
      pause();
      goTo(index + 1);
    });
    rotation.addEventListener('pointerdown', () => {
      // Remember the intended action before focusin pauses automatic movement.
      pointerRotationState = !isPaused();
    });
    rotation.addEventListener('pointercancel', () => { pointerRotationState = null; });
    rotation.addEventListener('click', event => {
      pausedByVisitor = event.detail && pointerRotationState !== null ? pointerRotationState : !isPaused();
      pointerRotationState = null;
      schedule();
    });
    root.addEventListener('focusin', pause);
    track.addEventListener('pointerdown', pause, { passive: true });
    track.addEventListener('wheel', pause, { passive: true });
    root.addEventListener('keydown', event => {
      pause();
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        goTo(index + (event.key === 'ArrowRight' ? 1 : -1));
      }
    });
    // Touch browsers emit mouseenter on tap without a matching mouseleave.
    root.addEventListener('mouseenter', () => { hovered = hoverable.matches; schedule(); });
    root.addEventListener('mouseleave', () => { hovered = false; schedule(); });
    track.addEventListener('scroll', () => {
      window.clearTimeout(scrollTimer);
      scrollTimer = window.setTimeout(() => {
        const left = track.getBoundingClientRect().left;
        index = slides.reduce((nearest, slide, i) =>
          Math.abs(slide.getBoundingClientRect().left - left) <
          Math.abs(slides[nearest].getBoundingClientRect().left - left) ? i : nearest, 0);
        showPosition();
      }, 150);
    }, { passive: true });
    desktop.addEventListener('change', schedule);
    reducedMotion.addEventListener('change', schedule);
    document.addEventListener('visibilitychange', schedule);
    controls.hidden = false;
    rotation.hidden = false;
    showPosition();
    schedule();
  });
})();
