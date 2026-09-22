/**
 * admin-seat-preview.js - Admin Saalplan Live-Preview Aktionen
 */

function getAdminCsrfToken() {
  const tokenInput = document.querySelector('[name=csrfmiddlewaretoken]');
  if (tokenInput) return tokenInput.value;
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : '';
}

function toggleBlockSeat(eventId, x, y) {
  if (!eventId) {
    alert("Diesem Sitzplan ist noch keine Veranstaltung zugewiesen.");
    return;
  }

  fetch('/seating/admin/toggle-block-seat/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getAdminCsrfToken()
    },
    body: JSON.stringify({ event_id: eventId, x: x, y: y })
  })
  .then(res => res.json())
  .then(data => {
    if (data.status === 'success') {
      location.reload();
    } else {
      alert("Fehler: " + data.message);
    }
  })
  .catch(err => {
    alert("Netzwerkfehler: " + err);
  });
}

function releaseOccupiedSeat(eventId, x, y, username, seatLabel) {
  if (!confirm(`Möchtest du den Platz "${seatLabel}" von User "${username}" wirklich freigeben?`)) {
    return;
  }

  fetch('/seating/admin/release-seat/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getAdminCsrfToken()
    },
    body: JSON.stringify({ event_id: eventId, x: x, y: y })
  })
  .then(res => res.json())
  .then(data => {
    if (data.status === 'success') {
      location.reload();
    } else {
      alert("Fehler: " + data.message);
    }
  })
  .catch(err => {
    alert("Netzwerkfehler: " + err);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const grid = document.querySelector('.seat-grid');
  if (!grid) return;

  grid.addEventListener('click', (e) => {
    const cell = e.target.closest('.preview-cell[data-action]');
    if (!cell) return;

    const action = cell.dataset.action;
    const eventId = parseInt(cell.dataset.eventId, 10);
    const x = parseInt(cell.dataset.x, 10);
    const y = parseInt(cell.dataset.y, 10);

    if (action === 'release') {
      const username = cell.dataset.username || '';
      const seatLabel = cell.dataset.seatLabel || 'P';
      releaseOccupiedSeat(eventId, x, y, username, seatLabel);
    } else if (action === 'toggle_block') {
      toggleBlockSeat(eventId, x, y);
    }
  });
});
