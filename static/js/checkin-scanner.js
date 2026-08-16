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

function updateLocalTableStatus(regId, isCheckedIn, timeStr) {
  const statusCell = document.getElementById(`status-cell-${regId}`);
  const btn = document.getElementById(`btn-toggle-${regId}`);
  const statCount = document.getElementById('stat-checked-in-count');

  if (statusCell && btn) {
    if (isCheckedIn) {
      statusCell.innerHTML = `<span class="badge-checked-in scanner-badge-checked">✓ Eingecheckt ${timeStr ? '(' + timeStr + ')' : ''}</span>`;
      btn.innerText = 'Auschecken';
    } else {
      statusCell.innerHTML = `<span class="badge-not-checked-in scanner-badge-pending">Noch nicht da</span>`;
      btn.innerText = 'Einchecken';
    }
  }

  // Rekalkuliere den Counter
  const checkedInElements = document.querySelectorAll('.badge-checked-in');
  if (statCount) statCount.innerText = checkedInElements.length;
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

  // Guest Search Input Filter
  const searchInput = document.getElementById('guest-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', function() {
      const q = this.value.toLowerCase().trim();
      document.querySelectorAll('.guest-row').forEach(row => {
        const text = row.getAttribute('data-search') || '';
        row.style.display = text.includes(q) ? '' : 'none';
      });
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
});
