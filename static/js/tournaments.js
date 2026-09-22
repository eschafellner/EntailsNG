/* Shared, accessible dialogs and tournament interactions. No HTML from team names. */
(() => {
  'use strict';
  let activeDialog = null;
  let opener = null;
  let inertElements = [];
  let previousOverflow = '';
  let saving = false;
  const focusable = dialog => [...dialog.querySelectorAll('button, input, select, textarea, a[href], [tabindex="0"]')]
    .filter(el => !el.disabled && el.getClientRects().length);

  function openDialog(id) {
    const dialog = document.getElementById(id);
    if (!dialog || activeDialog) return;
    opener = document.activeElement;
    activeDialog = dialog;
    dialog.style.display = 'flex';
    // Inert siblings at each level, never the dialog's ancestor.
    for (let node = dialog; node.parentElement; node = node.parentElement) {
      for (const sibling of node.parentElement.children) {
        if (sibling !== node && !sibling.inert) {
          sibling.inert = true;
          inertElements.push(sibling);
        }
      }
      if (node.parentElement === document.body) break;
    }
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    (focusable(dialog)[0] || dialog).focus();
  }
  function closeDialog() {
    if (!activeDialog || saving) return;
    activeDialog.style.display = 'none';
    activeDialog = null;
    inertElements.forEach(el => { el.inert = false; });
    inertElements = [];
    document.body.style.overflow = previousOverflow;
    if (opener?.isConnected) opener.focus();
  }
  window.openCreateTeamModal = () => openDialog('createTeamModal');
  window.closeCreateTeamModal = closeDialog;
  window.openFfaScoreModal = () => openDialog('ffaScoreModal');
  window.closeFfaScoreModal = closeDialog;
  window.closeScoreModal = closeDialog;
  document.addEventListener('keydown', e => {
    if (!activeDialog) return;
    if (e.key === 'Escape') { e.preventDefault(); closeDialog(); }
    if (e.key === 'Tab') {
      const elements = focusable(activeDialog);
      const first = elements[0], last = elements[elements.length - 1];
      if (!first) { e.preventDefault(); activeDialog.focus(); }
      else if (e.shiftKey && (document.activeElement === first || document.activeElement === activeDialog)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  window.toggleGenerateBracketConfirm = show => {
    const button = document.getElementById('btn-show-generate-bracket');
    const box = document.getElementById('bracket-generate-confirm');
    if (!button || !box) return;
    button.style.display = show ? 'none' : 'inline-block';
    box.style.display = show ? 'inline-flex' : 'none';
    (show ? box.querySelector('button') : button).focus();
  };

  const tabs = [...document.querySelectorAll('[role="tab"]')];
  window.openTab = (name, updateUrl = true) => {
    if (!tabs.some(tab => tab.id === 'tab-button-' + name)) return;
    tabs.forEach(tab => {
      const selected = tab.id === 'tab-button-' + name;
      tab.classList.toggle('active', selected);
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      const panel = document.getElementById(tab.getAttribute('aria-controls'));
      panel.classList.toggle('active', selected);
      panel.hidden = !selected;
    });
    if (updateUrl) history.replaceState(null, '', '#tab-' + name);
  };
  tabs.forEach((tab, i) => tab.addEventListener('keydown', e => {
    let next;
    if (e.key === 'ArrowRight') next = (i + 1) % tabs.length;
    if (e.key === 'ArrowLeft') next = (i + tabs.length - 1) % tabs.length;
    if (e.key === 'Home') next = 0;
    if (e.key === 'End') next = tabs.length - 1;
    if (next !== undefined) {
      e.preventDefault();
      window.openTab(tabs[next].id.replace('tab-button-', ''));
      tabs[next].focus();
    }
  }));
  if (tabs.length) window.openTab(location.hash.startsWith('#tab-') ? location.hash.slice(5) : 'bracket', false);

  const storageKey = 'tournament-view:' + location.pathname;
  const readStorage = () => { try { return JSON.parse(sessionStorage.getItem(storageKey) || '{}'); } catch (_) { return {}; } };
  const writeStorage = value => { try { sessionStorage.setItem(storageKey, JSON.stringify(value)); } catch (_) { /* Storage is optional. */ } };
  let listView = readStorage().view || (matchMedia('(max-width: 640px)').matches ? 'list' : 'tree');
  function setMatchView(view) {
    const list = document.getElementById('match-list'), tree = document.getElementById('match-tree');
    if (!list || !tree) return;
    listView = view;
    list.hidden = view !== 'list'; tree.hidden = view === 'list';
    document.querySelectorAll('[data-match-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.matchView === view)));
    writeStorage({view});
  }
  const restored = readStorage();
  setMatchView(listView);
  document.querySelectorAll('[data-match-view]').forEach(button => button.addEventListener('click', () => setMatchView(button.dataset.matchView)));
  if (Number.isFinite(restored.scroll)) {
    const restore = () => window.scrollTo(0, restored.scroll);
    if (document.readyState === 'complete') restore();
    else window.addEventListener('load', restore, {once: true});
    writeStorage({view: listView});
  }

  const data = document.getElementById('score-matches');
  if (!data) return;
  const matches = JSON.parse(data.textContent);
  const messages = document.getElementById('ux-messages').dataset;
  const form = document.getElementById('scoreForm');
  const first = document.getElementById('score_team1'), second = document.getElementById('score_team2');
  const winner = document.getElementById('winner_id');
  const reason = document.getElementById('decision_reason');
  const error = document.getElementById('scoreFormError');
  const submit = document.getElementById('btn_submit_score');
  let current = null;
  const format = (text, values) => text.replace(/\{(\w+)\}/g, (token, key) => values[key] ?? token);
  function validationMessage() {
    if (!current || first.value === '' || second.value === '') return messages.enterScores;
    const a = Number(first.value), b = Number(second.value);
    if (a === b && !current.isAdmin && !current.allowsDraw) return messages.tie;
    if (a === b && !winner.value && !current.allowsDraw) return messages.tie;
    const selected = Number(winner.value);
    const contradictory = (a > b && selected === current.team2Id) || (b > a && selected === current.team1Id);
    if (contradictory && (!current.isAdmin || !reason.value.trim())) return messages.discrepancy;
    return '';
  }
  function updateSummary() {
    if (!current) return;
    if (!current.isAdmin) {
      const draw = current.allowsDraw && first.value !== '' && second.value !== '' && Number(first.value) === Number(second.value);
      const loserName = current.role === 1 ? current.team1 : current.team2;
      const winnerName = current.role === 1 ? current.team2 : current.team1;
      winner.replaceChildren(new Option(draw ? messages.draw : winnerName,
        draw ? '' : current.role === 1 ? current.team2Id : current.team1Id));
      document.getElementById('participant_info_note').textContent = draw ? messages.drawNote : format(messages.defeatNote, {loser: loserName, winner: winnerName});
      submit.textContent = draw ? messages.drawSave : messages.defeatSave;
    }
    const problem = validationMessage();
    const a = Number(first.value), b = Number(second.value);
    const selected = winner.value ? winner.options[winner.selectedIndex].text : a > b ? current.team1 : b > a ? current.team2 : messages.draw;
    document.getElementById('score-summary').textContent = problem || format(messages.summary, {
      team1: current.team1, team2: current.team2, score1: first.value, score2: second.value, winner: selected,
    });
  }
  window.openScoreModal = button => {
    current = matches[button.dataset.matchId];
    if (!current || saving) return;
    form.reset();
    form.action = button.dataset.scoreUrl;
    document.getElementById('modal_match_id').value = current.id;
    first.value = current.score1 ?? ''; second.value = current.score2 ?? '';
    document.getElementById('lbl_team1').textContent = current.team1;
    document.getElementById('lbl_team2').textContent = current.team2;
    document.getElementById('modal_score_title').textContent = current.isAdmin ? messages.adminTitle : messages.defeatTitle;
    submit.textContent = current.isAdmin ? messages.save : messages.defeatSave;
    submit.style.background = current.isAdmin ? '#047857' : '#b91c1c';
    winner.replaceChildren();
    const note = document.getElementById('participant_info_note');
    note.style.display = current.isAdmin ? 'none' : 'block';
    if (current.isAdmin) {
      winner.add(new Option(messages.auto, ''));
      winner.add(new Option(current.team1, current.team1Id));
      winner.add(new Option(current.team2, current.team2Id));
      winner.value = current.winner ?? '';
      reason.value = current.reason || '';
    } else {
      const loserName = current.role === 1 ? current.team1 : current.team2;
      const winnerName = current.role === 1 ? current.team2 : current.team1;
      winner.add(new Option(winnerName, current.role === 1 ? current.team2Id : current.team1Id));
      note.textContent = format(messages.defeatNote, {loser: loserName, winner: winnerName});
      reason.value = '';
    }
    error.style.display = 'none'; error.textContent = '';
    updateSummary();
    openDialog('scoreModal');
  };
  [first, second, winner, reason].forEach(el => el.addEventListener('input', updateSummary));
  window.submitScore = async event => {
    event.preventDefault();
    if (saving || !form.reportValidity()) return;
    const problem = validationMessage();
    if (problem) { error.textContent = problem; error.style.display = 'block'; return; }
    saving = true;
    const oldText = submit.textContent;
    const formData = new FormData(form);
    const controls = [...form.querySelectorAll('button, input, select')];
    const disabled = controls.map(el => el.disabled);
    controls.forEach(el => { el.disabled = true; });
    submit.textContent = messages.saving;
    form.setAttribute('aria-busy', 'true');
    error.style.display = 'none';
    try {
      const response = await fetch(form.action, {method: 'POST', body: formData, headers: {'X-Requested-With': 'XMLHttpRequest'}});
      const result = await response.json();
      if (response.ok && result.success) {
        writeStorage({view: listView, scroll: window.scrollY});
        location.reload();
        return;
      }
      error.textContent = result.error || messages.error;
    } catch (_) {
      error.textContent = messages.network;
    }
    saving = false;
    controls.forEach((el, i) => { el.disabled = disabled[i]; });
    submit.textContent = oldText;
    form.removeAttribute('aria-busy');
    error.style.display = 'block';
    error.tabIndex = -1; error.focus();
  };
})();
