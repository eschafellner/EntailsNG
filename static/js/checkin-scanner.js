/**
 * Shared, server-confirmed feedback for camera, USB scanner and guest list.
 */
let html5QrcodeScanner = null;
let isScannerRunning = false;
let isCameraStarting = false;
let audioCtx = null;
let scanBusy = false;
let nextScanAt = 0;
let feedbackTimer = null;
let lastCameraCode = '';
let lastCameraSeenAt = 0;
const FEEDBACK_HOLD_MS = 3000;
const CAMERA_REMOVAL_MS = 1500;

function scannerText(key) {
  const texts = JSON.parse(document.getElementById('scanner-feedback-texts').textContent);
  return texts[key] || '';
}

function getCsrfToken() {
  const tokenInput = document.querySelector('[name=csrfmiddlewaretoken]');
  if (tokenInput) return tokenInput.value;
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : '';
}

// Unlock audio on user interaction; sound is supplementary to visible feedback.
function prepareAudio() {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
  } catch (_) { /* Audio may be unavailable on this device. */ }
}

function playTone(type) {
  prepareAudio();
  if (!audioCtx || audioCtx.state !== 'running') return;
  try {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    const now = audioCtx.currentTime;
    osc.type = type === 'success' ? 'sine' : 'triangle';
    osc.frequency.setValueAtTime(type === 'success' ? 880 : type === 'warning' ? 600 : 220, now);
    if (type === 'success') osc.frequency.exponentialRampToValueAtTime(1320, now + 0.15);
    gain.gain.setValueAtTime(0.15, now);
    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.3);
    osc.start(now);
    osc.stop(now + 0.3);
  } catch (_) { /* Visual feedback remains available. */ }
}

function setScanControls(disabled) {
  document.querySelectorAll('#btn-manual-scan, #toggle-camera-btn, .btn-checkin-action').forEach(button => {
    button.disabled = disabled;
  });
}

function renderScanFeedback(state, title, message, body = {}, prominent = false) {
  const banner = document.getElementById('scan-status-banner');
  const card = document.getElementById('scan-result-card');
  banner.dataset.state = state;
  document.querySelector('.scanner-container').dataset.feedback = state;
  // API messages contain guest input: always render text, never HTML.
  document.getElementById('scan-result-icon').textContent =
    { ready: '⌁', checking: '…', success: '✓', warning: '⚠', error: '✕' }[state];
  document.getElementById('scan-result-title').textContent = title;
  document.getElementById('scan-result-message').textContent = message;
  const summary = document.getElementById('scan-result-summary');
  summary.textContent = [
    body.user,
    body.seat ? scannerText('seat') + ': ' + body.seat : '',
    body.checked_in_at ? scannerText('time') + ': ' + body.checked_in_at : ''
  ].filter(Boolean).join(' · ');
  summary.hidden = !summary.textContent;
  const details = document.getElementById('scan-details-box');
  details.hidden = !body.user;
  ['user', 'name', 'seat', 'ticket'].forEach(key => {
    document.getElementById('res-' + key).textContent = body[key === 'name' ? 'full_name' : key] || '—';
  });
  banner.setAttribute('aria-busy', state === 'checking' ? 'true' : 'false');
  card.classList.toggle('is-prominent', prominent);
  if (prominent) {
    playTone(state);
    try {
      if (navigator.vibrate) navigator.vibrate(state === 'success' ? 100 : [80, 60, 80]);
    } catch (_) { /* Vibration is optional. */ }
  }
}

function holdScanFeedback() {
  setScanControls(true);
  nextScanAt = Date.now() + FEEDBACK_HOLD_MS;
  document.getElementById('scan-next-hint').textContent = scannerText('pause');
  clearTimeout(feedbackTimer);
  feedbackTimer = setTimeout(() => {
    nextScanAt = 0;
    document.getElementById('scan-result-card').classList.remove('is-prominent');
    document.getElementById('scan-next-hint').textContent = scannerText('next');
    setScanControls(scanBusy);
  }, FEEDBACK_HOLD_MS);
}

function startScannerRequest(url, payload, isToggle = false) {
  if (scanBusy || Date.now() < nextScanAt) return false;
  prepareAudio();
  scanBusy = true;
  setScanControls(true);
  renderScanFeedback('checking', scannerText('checking'), scannerText('waiting'));
  document.getElementById('scan-next-hint').textContent = scannerText('waiting');
  void performScannerRequest(url, payload, isToggle);
  return true;
}

async function performScannerRequest(url, payload, isToggle) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    // Server errors, expired sessions (HTML redirects) and lost replies are uncertain.
    if (response.redirected || response.status >= 500) throw new Error('Unconfirmed response');
    const body = await response.json();
    if (response.ok && (body.status === 'success' || body.status === 'already_checked_in')) {
      const checkedIn = isToggle ? body.is_checked_in : true;
      const warning = body.status === 'already_checked_in' || !checkedIn;
      const title = body.status === 'already_checked_in' ? scannerText('already') :
        checkedIn ? scannerText('success') : scannerText('checkout');
      renderScanFeedback(warning ? 'warning' : 'success', title, body.message, body, true);
      updateLocalTableStatus(body.registration_id || payload.registration_id, checkedIn, body.checked_in_at);
    } else {
      renderScanFeedback(response.status === 429 ? 'warning' : 'error',
        response.status === 429 ? scannerText('limited') : scannerText('rejected'),
        body.message || scannerText('unknown'), body, true);
    }
  } catch (_) {
    renderScanFeedback('error', scannerText('unconfirmed'), scannerText('network'), {}, true);
    // The request may have been saved even if its reply was lost.
    loadGuestPage();
  } finally {
    clearTimeout(timeout);
    scanBusy = false;
    holdScanFeedback();
  }
}

function sendScanCode(code) {
  if (!code.trim()) return false;
  return startScannerRequest('/api/check-in/scan/', { code: code.trim() });
}

function toggleCheckIn(registrationId) {
  return startScannerRequest('/api/check-in/toggle/', { registration_id: registrationId }, true);
}

function handleCameraCode(decodedText) {
  const now = Date.now();
  if (now - lastCameraSeenAt >= CAMERA_REMOVAL_MS) lastCameraCode = '';
  lastCameraSeenAt = now;
  if (decodedText === lastCameraCode) return;
  if (sendScanCode(decodedText)) lastCameraCode = decodedText;
}


let currentFilter = 'all';
let displayedFilter = 'all';
let displayedQuery = '';
let listRequest = null;
let listGeneration = 0;

function setScannerStats(stats) {
  document.getElementById('stat-total-count').innerText = stats.total;
  document.getElementById('stat-paid-count').innerText = stats.paid;
  document.getElementById('stat-checked-in-count').innerText = stats.checked_in;
  document.getElementById('stat-progress-text').innerHTML = `<strong>${stats.checked_in}</strong> / ${stats.total} (${stats.percent}%)`;
  document.getElementById('stat-progress-fill').style.width = `${stats.percent}%`;
  document.getElementById('tab-count-all').innerText = stats.total;
  document.getElementById('tab-count-pending').innerText = stats.pending;
  document.getElementById('tab-count-checked-in').innerText = stats.checked_in;
  document.getElementById('tab-count-unpaid').innerText = stats.unpaid;
}

function loadGuestPage(page = 1, append = false) {
  if (listRequest) listRequest.abort();
  listRequest = new AbortController();
  const generation = ++listGeneration;
  const query = document.getElementById('guest-search-input').value.trim();
  const params = new URLSearchParams({ partial: '1', page: String(page), filter: currentFilter, q: query });
  const loadMoreWrap = document.getElementById('load-more-wrap');
  const loadMoreBtn = document.getElementById('btn-load-more');
  if (loadMoreBtn) loadMoreBtn.disabled = true;
  fetch(`${window.location.pathname}?${params}`, { signal: listRequest.signal })
    .then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(data => {
      if (generation !== listGeneration) return;
      const tbody = document.getElementById('guest-table-body');
      if (append) tbody.insertAdjacentHTML('beforeend', data.rows_html);
      else tbody.innerHTML = data.rows_html;
      setScanControls(scanBusy || Date.now() < nextScanAt);
      tbody.dataset.matchCount = data.match_count;
      displayedFilter = currentFilter;
      displayedQuery = query;
      setScannerStats(data.stats);
      document.getElementById('no-search-results').style.display = data.match_count === 0 ? 'block' : 'none';
      loadMoreWrap.dataset.nextPage = data.next_page || '';
      loadMoreWrap.style.display = data.next_page ? 'block' : 'none';
      document.getElementById('load-more-count').innerText = data.remaining;
      const clearBtn = document.getElementById('guest-search-clear');
      clearBtn.style.display = query ? 'block' : 'none';
    })
    .catch(error => {
      if (error.name !== 'AbortError') console.error('Teilnehmerliste konnte nicht geladen werden:', error);
    })
    .finally(() => {
      if (generation === listGeneration && loadMoreBtn) loadMoreBtn.disabled = false;
    });
}

function updateLocalTableStatus(regId, isCheckedIn, timeStr) {
  const row = document.getElementById(`guest-row-${regId}`);
  const statusCell = document.getElementById(`status-cell-${regId}`);
  const btn = document.getElementById(`btn-toggle-${regId}`);

  if (row) {
    row.setAttribute('data-checked-in', isCheckedIn ? 'true' : 'false');
  }

  if (statusCell) {
    if (isCheckedIn) {
      statusCell.innerHTML = `<span class="badge-checked-in scanner-badge-checked">✓ Eingecheckt ${timeStr ? '(' + timeStr + ')' : ''}</span>`;
    } else {
      statusCell.innerHTML = `<span class="badge-not-checked-in scanner-badge-pending">⏳ Noch nicht da</span>`;
    }
  }

  if (btn) {
    if (isCheckedIn) {
      btn.innerText = 'Auschecken';
      btn.className = 'btn-checkin-action btn-action-checkout';
    } else {
      btn.innerText = 'Einchecken';
      btn.className = 'btn-checkin-action btn-action-checkin';
    }
  }

  // Die Liste enthält höchstens 30 Zeilen; globale Zähler kommen vom Server.
  loadGuestPage();
}

function startCamera() {
  if (isCameraStarting || isScannerRunning) return;
  prepareAudio();
  if (typeof Html5Qrcode === 'undefined') {
    renderScanFeedback('error', scannerText('camera'), scannerText('library'), {}, true);
    holdScanFeedback();
    return;
  }

  const cameraBtn = document.getElementById('toggle-camera-btn');
  const placeholder = document.getElementById('camera-placeholder');
  if (placeholder) placeholder.style.display = 'none';
  isCameraStarting = true;
  lastCameraCode = '';
  lastCameraSeenAt = 0;
  html5QrcodeScanner = new Html5Qrcode("reader");
  html5QrcodeScanner.start(
    { facingMode: "environment" },
    { fps: 10, qrbox: { width: 220, height: 220 } },
    handleCameraCode,
    () => {}
  ).then(() => {
    isScannerRunning = true;
    isCameraStarting = false;
    if (cameraBtn) {
      cameraBtn.innerText = scannerText('camera_stop');
      cameraBtn.classList.add('btn-camera-active');
    }
  }).catch(() => {
    isCameraStarting = false;
    if (placeholder) placeholder.style.display = 'block';
    renderScanFeedback('error', scannerText('camera'), scannerText('camera_permission'), {}, true);
    holdScanFeedback();
  });
}

function stopCamera() {
  if (html5QrcodeScanner && isScannerRunning) {
    html5QrcodeScanner.stop().then(() => {
      isScannerRunning = false;
      const cameraBtn = document.getElementById('toggle-camera-btn');
      if (cameraBtn) {
        cameraBtn.innerText = scannerText('camera_start');
        cameraBtn.classList.remove('btn-camera-active');
      }
      const placeholder = document.getElementById('camera-placeholder');
      if (placeholder) placeholder.style.display = 'block';
    });
  }
}

// EVENTS & INIT
document.addEventListener('DOMContentLoaded', function() {
  document.addEventListener('pointerdown', prepareAudio, { once: true });
  const manualBtn = document.getElementById('btn-manual-scan');
  const manualInput = document.getElementById('manual-code-input');

  if (manualBtn && manualInput) {
    manualBtn.addEventListener('click', () => {
      const val = manualInput.value.trim();
      if (val && sendScanCode(val)) manualInput.value = '';
    });

    manualInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const val = manualInput.value.trim();
        if (val && sendScanCode(val)) manualInput.value = '';
      }
    });
  }

  // Filter Tabs
  const tabBtns = document.querySelectorAll('.scanner-tab-btn');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', function() {
      tabBtns.forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      currentFilter = this.getAttribute('data-filter') || 'all';
      loadGuestPage();
    });
  });

  // Guest Search Input Filter & Speed Check-in on Enter
  const searchInput = document.getElementById('guest-search-input');
  const searchClearBtn = document.getElementById('guest-search-clear');

  if (searchInput) {
    let searchTimer;
    searchInput.addEventListener('input', function() {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadGuestPage(), 250);
    });

    searchInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (searchInput.value.trim() !== displayedQuery || displayedFilter !== currentFilter) {
          clearTimeout(searchTimer);
          loadGuestPage();
          return;
        }
        const visibleRows = Array.from(document.querySelectorAll('.guest-row'));
        if (visibleRows.length === 1 && Number(document.getElementById('guest-table-body').dataset.matchCount) === 1) {
          const targetRow = visibleRows[0];
          // Enter always checks in; a stale list must never check a guest out.
          sendScanCode(targetRow.getAttribute('data-code') || '');
        } else if (visibleRows.length === 0) {
          if (!scanBusy && Date.now() >= nextScanAt) {
            renderScanFeedback('error', scannerText('rejected'), scannerText('no_guest'), {}, true);
            holdScanFeedback();
          }
        }
      }
    });
  }

  if (searchClearBtn && searchInput) {
    searchClearBtn.addEventListener('click', function() {
      searchInput.value = '';
      loadGuestPage();
      searchInput.focus();
    });
  }

  // Load More Button
  const loadMoreBtn = document.getElementById('btn-load-more');
  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', function() {
      const page = Number(document.getElementById('load-more-wrap').dataset.nextPage);
      if (page) loadGuestPage(page, true);
    });
  }

  // Reset Filters Button (Empty State)
  const resetFiltersBtn = document.getElementById('btn-reset-filters');
  if (resetFiltersBtn) {
    resetFiltersBtn.addEventListener('click', function() {
      if (searchInput) searchInput.value = '';
      currentFilter = 'all';
      tabBtns.forEach(b => {
        if (b.getAttribute('data-filter') === 'all') {
          b.classList.add('active');
        } else {
          b.classList.remove('active');
        }
      });
      loadGuestPage();
    });
  }

  // Kamera Button
  const cameraBtn = document.getElementById('toggle-camera-btn');
  if (cameraBtn) {
    cameraBtn.addEventListener('click', function() {
      if (isScannerRunning) {
        stopCamera();
      } else {
        startCamera();
      }
    });
  }

  displayedQuery = searchInput.value.trim();
  document.getElementById('guest-search-clear').style.display = displayedQuery ? 'block' : 'none';
});
