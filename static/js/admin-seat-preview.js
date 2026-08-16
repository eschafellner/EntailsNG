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
