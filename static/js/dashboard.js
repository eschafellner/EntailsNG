/**
 * dashboard.js - Frontend Logik für das Dashboard
 * Kapselt Countdown-Timer, QR-Code-Modal und dynamische Saalplan-Mini-Map.
 */

function openQrModal() {
  const modal = document.getElementById('qr-modal');
  if (modal) modal.style.display = 'flex';
}
window.openQrModal = openQrModal;

function closeQrModal() {
  const modal = document.getElementById('qr-modal');
  if (modal) modal.style.display = 'none';
}
window.closeQrModal = closeQrModal;

function openPaymentQrModal() {
  const modal = document.getElementById('payment-qr-modal');
  if (modal) modal.style.display = 'flex';
}
window.openPaymentQrModal = openPaymentQrModal;

function closePaymentQrModal() {
  const modal = document.getElementById('payment-qr-modal');
  if (modal) modal.style.display = 'none';
}
window.closePaymentQrModal = closePaymentQrModal;

function initModals() {
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      closeQrModal();
      closePaymentQrModal();
    }
  });

  const qrModal = document.getElementById('qr-modal');
  if (qrModal) {
    qrModal.addEventListener('click', function(e) {
      if (e.target === qrModal) closeQrModal();
    });
  }

  const paymentModal = document.getElementById('payment-qr-modal');
  if (paymentModal) {
    paymentModal.addEventListener('click', function(e) {
      if (e.target === paymentModal) closePaymentQrModal();
    });
  }
}


function initCountdown() {
  const countdownEl = document.getElementById('ticket-countdown');
  if (!countdownEl) return;

  const eventDateStr = countdownEl.dataset.startDate;
  const eventEndDateStr = countdownEl.dataset.endDate;
  if (!eventDateStr) return;

  const targetDate = new Date(eventDateStr).getTime();
  const endDate = eventEndDateStr ? new Date(eventEndDateStr).getTime() : null;

  function update() {
    const now = new Date().getTime();

    if (endDate && now > endDate) {
      countdownEl.innerHTML = "<span class='countdown-expired'>VERANSTALTUNG BEENDET</span>";
      return;
    }

    let diff = targetDate - now;
    if (diff <= 0) {
      countdownEl.innerHTML = "<span class='countdown-live'>EVENT LÄUFT JETZT!</span>";
      return;
    }

    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((diff % (1000 * 60)) / 1000);

    const cdDays = document.getElementById('cd-days');
    const cdHours = document.getElementById('cd-hours');
    const cdMinutes = document.getElementById('cd-minutes');
    const cdSeconds = document.getElementById('cd-seconds');

    if (cdDays) cdDays.innerText = String(days).padStart(2, '0');
    if (cdHours) cdHours.innerText = String(hours).padStart(2, '0');
    if (cdMinutes) cdMinutes.innerText = String(minutes).padStart(2, '0');
    if (cdSeconds) cdSeconds.innerText = String(seconds).padStart(2, '0');
  }

  update();
  setInterval(update, 1000);
}

function initMinimap() {
  const container = document.getElementById('minimap-container');
  if (!container) return;

  const eventId = container.dataset.eventId;
  const currentUsername = container.dataset.username || '';
  if (!eventId) return;

  fetch(`/seating/api/plan/${eventId}/`)
    .then(res => res.json())
    .then(data => {
      if (!data.cells || data.cells.length === 0) {
        container.innerHTML = `<span class="minimap-empty">${container.dataset.notConfiguredText || 'Sitzplan noch nicht konfiguriert'}</span>`;
        return;
      }

      let targetCell = null;
      if (currentUsername) {
        targetCell = data.cells.find(c => c.occupied_by === currentUsername);
      }

      const allX = data.cells.map(c => c.x);
      const allY = data.cells.map(c => c.y);
      const planMinX = Math.min(...allX);
      const planMaxX = Math.max(...allX);
      const planMinY = Math.min(...allY);
      const planMaxY = Math.max(...allY);

      let minX, maxX, minY, maxY;
      const maxColsToShow = 14;
      const maxRowsToShow = 8;

      if (targetCell) {
        minX = Math.max(planMinX, Math.min(planMaxX - maxColsToShow + 1, targetCell.x - Math.floor(maxColsToShow / 2)));
        maxX = Math.min(planMaxX, minX + maxColsToShow - 1);
        minY = Math.max(planMinY, Math.min(planMaxY - maxRowsToShow + 1, targetCell.y - Math.floor(maxRowsToShow / 2)));
        maxY = Math.min(planMaxY, minY + maxRowsToShow - 1);
      } else {
        minX = planMinX;
        maxX = Math.min(planMinX + maxColsToShow - 1, planMaxX);
        minY = planMinY;
        maxY = Math.min(planMinY + maxRowsToShow - 1, planMaxY);
      }

      const cols = (maxX - minX) + 1;
      container.style.gridTemplateColumns = `repeat(${cols}, 14px)`;
      container.innerHTML = '';

      const cellMap = {};
      data.cells.forEach(c => cellMap[`${c.x}_${c.y}`] = c);

      for (let y = minY; y <= maxY; y++) {
        for (let x = minX; x <= maxX; x++) {
          const cell = cellMap[`${x}_${y}`];
          const div = document.createElement('div');
          div.className = 'minimap-cell';

          if (!cell || cell.cell_type === 'EMPTY') {
            div.classList.add('minimap-cell-empty');
          } else if (cell.cell_type === 'SEAT') {
            const isOwnCell = currentUsername && (cell.occupied_by === currentUsername);
            if (isOwnCell) {
              div.classList.add('minimap-cell-own');
              div.title = `Dein Platz: ${cell.seat_label || (cell.x + ',' + cell.y)}`;
            } else if (cell.status === 'FREE') {
              div.classList.add('minimap-cell-free');
            } else if (cell.status === 'PRE_RESERVED') {
              div.classList.add('minimap-cell-pre');
            } else {
              div.classList.add('minimap-cell-reserved');
            }
          } else {
            div.classList.add('minimap-cell-obstacle');
          }
          container.appendChild(div);
        }
      }
    })
    .catch(() => {});
}

document.addEventListener('DOMContentLoaded', function() {
  initModals();
  initCountdown();
  initMinimap();
});
