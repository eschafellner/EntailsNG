(() => {
  'use strict';
  const edit = document.getElementById('draw-edit-form');
  const publish = document.getElementById('draw-publish-form');
  if (!edit || !publish) return;
  const open = document.getElementById('draw-open-confirm');
  const close = document.getElementById('draw-close-confirm');
  const confirm = document.getElementById('draw-confirm');
  const submit = document.getElementById('draw-publish-submit');
  const notice = document.getElementById('draw-dirty-notice');
  open.hidden = false;
  close.hidden = false;
  confirm.hidden = true;
  open.addEventListener('click', () => {
    if (!publish.reportValidity()) return;
    open.hidden = true;
    confirm.hidden = false;
    submit.focus();
  });
  close.addEventListener('click', () => {
    confirm.hidden = true;
    open.hidden = false;
    open.focus();
  });
  let dirty = false;
  edit.addEventListener('change', event => {
    const name = event.target.name || '';
    if (!name.startsWith('clan_') && !['respect_seeds', 'avoid_clans'].includes(name)) return;
    dirty = true;
    notice.hidden = false;
    open.disabled = true;
    submit.disabled = true;
    confirm.hidden = true;
    open.hidden = false;
  });
  publish.addEventListener('submit', event => {
    if (dirty) { event.preventDefault(); notice.hidden = false; return; }
    submit.disabled = true;
  });
})();
