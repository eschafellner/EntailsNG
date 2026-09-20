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

const PAGE_SIZE = 30;
let currentFilter = 'all';
let visibleLimit = PAGE_SIZE;

function applyFilters() {
  const searchInput = document.getElementById('guest-search-input');
  const query = searchInput ? searchInput.value.toLowerCase().trim() : '';
  const clearBtn = document.getElementById('guest-search-clear');
  const noResults = document.getElementById('no-search-results');
  const loadMoreWrap = document.getElementById('load-more-wrap');
  const loadMoreCount = document.getElementById('load-more-count');

  if (clearBtn) {
    clearBtn.style.display = query ? 'block' : 'none';
  }

  const allRows = Array.from(document.querySelectorAll('.guest-row'));
  if (allRows.length === 0) return;

  // Filter matching rows
  const matchingRows = allRows.filter(row => {
    // 1. Tab Status Filter
    const isCheckedIn = row.getAttribute('data-checked-in') === 'true';
    const isPaid = row.getAttribute('data-paid') === 'paid';

    if (currentFilter === 'pending' && isCheckedIn) return false;
    if (currentFilter === 'checked-in' && !isCheckedIn) return false;
    if (currentFilter === 'unpaid' && isPaid) return false;

    // 2. Search Query Filter
    if (query) {
      const searchData = (row.getAttribute('data-search') || '').toLowerCase();
      if (!searchData.includes(query)) return false;
    }

    return true;
  });

  // Display logic: Active search shows ALL matches without limit; browsing uses visibleLimit
  const isSearching = query.length > 0;
  const displayLimit = isSearching ? matchingRows.length : visibleLimit;

  allRows.forEach(row => {
    row.style.display = 'none';
  });

  matchingRows.slice(0, displayLimit).forEach(row => {
    row.style.display = '';
  });

  // Empty state for search/filter
  if (noResults) {
    noResults.style.display = matchingRows.length === 0 ? 'block' : 'none';
  }

  // Load more button container
  if (loadMoreWrap) {
    if (!isSearching && matchingRows.length > visibleLimit) {
      loadMoreWrap.style.display = 'block';
      if (loadMoreCount) {
        loadMoreCount.innerText = matchingRows.length - visibleLimit;
      }
    } else {
      loadMoreWrap.style.display = 'none';
    }
  }
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

  // Recalculate stats & counts
  const allRows = document.querySelectorAll('.guest-row');
  const totalCount = allRows.length;
  const checkedInCount = document.querySelectorAll('.guest-row[data-checked-in="true"]').length;
  const pendingCount = Math.max(0, totalCount - checkedInCount);
  const unpaidCount = document.querySelectorAll('.guest-row[data-paid]:not([data-paid="paid"])').length;
  const pct = totalCount > 0 ? Math.round((checkedInCount / totalCount) * 100) : 0;

  // Update Header Counters & Progress Bar
  const statTotal = document.getElementById('stat-total-count');
  const statCheckedIn = document.getElementById('stat-checked-in-count');
  const statPaid = document.getElementById('stat-paid-count');
  const progressText = document.getElementById('stat-progress-text');
  const progressFill = document.getElementById('stat-progress-fill');

  if (statTotal) statTotal.innerText = totalCount;
  if (statCheckedIn) statCheckedIn.innerText = checkedInCount;
  if (statPaid) statPaid.innerText = totalCount - unpaidCount;
  if (progressText) {
    progressText.innerHTML = `<strong>${checkedInCount}</strong> / ${totalCount} (${pct}%)`;
  }
  if (progressFill) {
    progressFill.style.width = `${pct}%`;
  }

  // Update Tab Badges
  const tabAll = document.getElementById('tab-count-all');
  const tabPending = document.getElementById('tab-count-pending');
  const tabCheckedIn = document.getElementById('tab-count-checked-in');
  const tabUnpaid = document.getElementById('tab-count-unpaid');

  if (tabAll) tabAll.innerText = totalCount;
  if (tabPending) tabPending.innerText = pendingCount;
  if (tabCheckedIn) tabCheckedIn.innerText = checkedInCount;
  if (tabUnpaid) tabUnpaid.innerText = unpaidCount;

  // Re-apply filters so row position/visibility updates accurately
  applyFilters();
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
      visibleLimit = PAGE_SIZE;
      applyFilters();
    });
  });

  // Guest Search Input Filter & Speed Check-in on Enter
  const searchInput = document.getElementById('guest-search-input');
  const searchClearBtn = document.getElementById('guest-search-clear');

  if (searchInput) {
    searchInput.addEventListener('input', function() {
      visibleLimit = PAGE_SIZE;
      applyFilters();
    });

    searchInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        const visibleRows = Array.from(document.querySelectorAll('.guest-row')).filter(r => r.style.display !== 'none');
        if (visibleRows.length === 1) {
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
      visibleLimit = PAGE_SIZE;
      applyFilters();
      searchInput.focus();
    });
  }

  // Load More Button
  const loadMoreBtn = document.getElementById('btn-load-more');
  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', function() {
      visibleLimit += PAGE_SIZE;
      applyFilters();
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
      visibleLimit = PAGE_SIZE;
      applyFilters();
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

  // Initial Filter / Display Run
  applyFilters();
});
