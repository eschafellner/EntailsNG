/**
 * Check-in Scanner Frontend Controller
 * Kapselt Kamera-QR-Scan, Web Audio Feedback, USB/Token-Scans und AJAX-Statusupdates.
 */

let html5QrcodeScanner = null;
let isScannerRunning = false;
let audioCtx = null;

function getCsrfToken() {
  const tokenInput = document.querySelector('[name=csrfmiddlewaretoken]');
  if (tokenInput) return tokenInput.value;
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : '';
}

// WEB AUDIO API SOUND GENERATOR
function playTone(type) {
  try {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);

    if (type === 'success') {
      // Hoher angenehmer Chime-Ton
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, audioCtx.currentTime); // A5
      osc.frequency.exponentialRampToValueAtTime(1320, audioCtx.currentTime + 0.15); // E6
      gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.3);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.3);
    } else if (type === 'warning') {
      // Doppel-Beep für bereits eingecheckt
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(600, audioCtx.currentTime);
      gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.2);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.2);
    } else {
      // Tiefer Fehler-Brummton für Unbezahlt / Ungültig
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(220, audioCtx.currentTime); // A3
      osc.frequency.setValueAtTime(140, audioCtx.currentTime + 0.15);
      gain.gain.setValueAtTime(0.4, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.4);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.4);
    }
  } catch (e) {
    console.warn("Audio feedback unavailable:", e);
  }
}

// SCAN ANFRAGE VERARBEITEN
function sendScanCode(code) {
  const banner = document.getElementById('scan-status-banner');
  const detailsBox = document.getElementById('scan-details-box');
  if (!banner) return;

  banner.style.background = '#0b0f17';
  banner.style.borderColor = 'var(--line)';
  banner.innerHTML = '<span style="font-size: 32px;">⏳</span><p style="color: var(--muted); margin: 6px 0 0 0;">Code wird geprüft...</p>';

  fetch('/api/check-in/scan/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken()
    },
    body: JSON.stringify({ code: code })
  })
  .then(res => res.json().then(data => ({ status: res.status, body: data })))
  .then(({ status, body }) => {
    if (detailsBox) detailsBox.style.display = 'block';
    const resUser = document.getElementById('res-user');
    const resName = document.getElementById('res-name');
    const resSeat = document.getElementById('res-seat');
    const resTicket = document.getElementById('res-ticket');

    if (resUser) resUser.innerText = body.user || '-';
    if (resName) resName.innerText = body.full_name || '-';
    if (resSeat) resSeat.innerText = body.seat || '-';
    if (resTicket) resTicket.innerText = body.ticket || '-';

    if (body.status === 'success') {
      playTone('success');
      banner.style.background = 'rgba(34, 197, 94, 0.15)';
      banner.style.borderColor = '#22c55e';
      banner.innerHTML = `
        <span style="font-size: 48px; color: #22c55e;">✓</span>
        <h3 style="margin: 6px 0 2px 0; color: #22c55e; font-family: 'Barlow Condensed', sans-serif; font-size: 26px;">EINLASS GESTATTET</h3>
        <p style="margin: 0; color: #86efac; font-family: 'JetBrains Mono', monospace; font-size: 13px;">${body.message}</p>
      `;
      updateLocalTableStatus(body.registration_id, true, body.checked_in_at);

    } else if (body.status === 'already_checked_in') {
      playTone('warning');
      banner.style.background = 'rgba(234, 179, 8, 0.15)';
      banner.style.borderColor = '#eab308';
      banner.innerHTML = `
        <span style="font-size: 48px; color: #eab308;">⚠️</span>
        <h3 style="margin: 6px 0 2px 0; color: #eab308; font-family: 'Barlow Condensed', sans-serif; font-size: 26px;">BEREITS EINGECHECKT</h3>
        <p style="margin: 0; color: #fde047; font-family: 'JetBrains Mono', monospace; font-size: 13px;">${body.message}</p>
      `;

    } else if (body.status === 'unpaid') {
      playTone('error');
      banner.style.background = 'rgba(239, 68, 68, 0.2)';
      banner.style.borderColor = '#ef4444';
      banner.innerHTML = `
        <span style="font-size: 48px; color: #ef4444;">⛔</span>
        <h3 style="margin: 6px 0 2px 0; color: #ef4444; font-family: 'Barlow Condensed', sans-serif; font-size: 26px;">CHECK-IN ABGELEHNT</h3>
        <p style="margin: 0; color: #fca5a5; font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: bold;">${body.message}</p>
      `;

    } else {
      playTone('error');
      banner.style.background = 'rgba(239, 68, 68, 0.15)';
      banner.style.borderColor = '#ef4444';
      banner.innerHTML = `
        <span style="font-size: 48px; color: #ef4444;">✖</span>
        <h3 style="margin: 6px 0 2px 0; color: #ef4444; font-family: 'Barlow Condensed', sans-serif; font-size: 24px;">UNGÜLTIGER CODE</h3>
        <p style="margin: 0; color: #fca5a5; font-family: 'JetBrains Mono', monospace; font-size: 12px;">${body.message || 'Code nicht gefunden'}</p>
      `;
    }
  })
  .catch(() => {
    playTone('error');
    banner.style.background = 'rgba(239, 68, 68, 0.15)';
    banner.style.borderColor = '#ef4444';
    banner.innerHTML = '<span style="font-size: 32px;">⚠️</span><p style="color: #fca5a5; margin: 6px 0 0 0;">Netzwerkfehler beim Scannen.</p>';
  });
}

// TOGGLE CHECK-IN PER BUTTON IN DER TABELLE
function toggleCheckIn(registrationId) {
  fetch('/api/check-in/toggle/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken()
    },
    body: JSON.stringify({ registration_id: registrationId })
  })
  .then(res => res.json())
  .then(data => {
    if (data.status === 'success') {
      updateLocalTableStatus(registrationId, data.is_checked_in, data.checked_in_at);
      playTone(data.is_checked_in ? 'success' : 'warning');
    } else {
      alert(data.message || 'Fehler beim Umschalten.');
    }
  })
  .catch(err => {
    alert('Netzwerkfehler: ' + err);
  });
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
  if (typeof Html5Qrcode === 'undefined') {
    alert("QR-Code Bibliothek lädt noch oder wird blockiert.");
    return;
  }

  const cameraBtn = document.getElementById('toggle-camera-btn');
  const placeholder = document.getElementById('camera-placeholder');
  if (placeholder) placeholder.style.display = 'none';

  html5QrcodeScanner = new Html5Qrcode("reader");
  html5QrcodeScanner.start(
    { facingMode: "environment" },
    { fps: 10, qrbox: { width: 220, height: 220 } },
    (decodedText) => {
      sendScanCode(decodedText);
    },
    () => {}
  ).then(() => {
    isScannerRunning = true;
    if (cameraBtn) {
      cameraBtn.innerText = "Kamera Stoppen";
      cameraBtn.classList.add('btn-camera-active');
    }
  }).catch(() => {
    alert("Kamera-Zugriff nicht möglich. Bitte Berechtigung im Browser erteilen.");
  });
}

function stopCamera() {
  if (html5QrcodeScanner && isScannerRunning) {
    html5QrcodeScanner.stop().then(() => {
      isScannerRunning = false;
      const cameraBtn = document.getElementById('toggle-camera-btn');
      if (cameraBtn) {
        cameraBtn.innerText = "Kamera Starten";
        cameraBtn.classList.remove('btn-camera-active');
      }
      const placeholder = document.getElementById('camera-placeholder');
      if (placeholder) placeholder.style.display = 'block';
    });
  }
}

// EVENTS & INIT
document.addEventListener('DOMContentLoaded', function() {
  const manualBtn = document.getElementById('btn-manual-scan');
  const manualInput = document.getElementById('manual-code-input');

  if (manualBtn && manualInput) {
    manualBtn.addEventListener('click', () => {
      const val = manualInput.value.trim();
      if (val) { sendScanCode(val); manualInput.value = ''; }
    });

    manualInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const val = manualInput.value.trim();
        if (val) { sendScanCode(val); manualInput.value = ''; }
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
          const regId = targetRow.getAttribute('data-id');
          const isAlreadyCheckedIn = targetRow.getAttribute('data-checked-in') === 'true';

          if (!isAlreadyCheckedIn) {
            toggleCheckIn(regId);
            targetRow.style.outline = '2px solid #22c55e';
            setTimeout(() => { targetRow.style.outline = ''; }, 1200);
          } else {
            playTone('warning');
            targetRow.style.outline = '2px solid #eab308';
            setTimeout(() => { targetRow.style.outline = ''; }, 1200);
          }
        } else if (visibleRows.length === 0) {
          playTone('error');
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
