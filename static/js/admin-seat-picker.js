/**
 * admin-seat-picker.js - Admin Sitzplatzzuweisungs-Modal für EventRegistrationAdmin
 */

function openSeatModal(eventId) {
  const modal = document.getElementById('seatModal');
  if (modal) {
    modal.style.display = 'flex';
    loadModalGrid(eventId);
  }
}

function closeSeatModal() {
  const modal = document.getElementById('seatModal');
  if (modal) {
    modal.style.display = 'none';
  }
}

function getAdminCsrfToken() {
  const tokenInput = document.querySelector('[name=csrfmiddlewaretoken]');
  if (tokenInput) return tokenInput.value;
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : '';
}

function loadModalGrid(eventId) {
  const container = document.getElementById('modal-grid-container');
  if (!container) return;

  const targetEventId = eventId || container.dataset.eventId;
  const regId = container.dataset.regId;
  const username = container.dataset.username || '';

  fetch(`/seating/api/plan/${targetEventId}/`)
    .then(res => res.json())
    .then(data => {
      if (data.error) {
        container.innerHTML = data.error;
        return;
      }

      let gridHtml = `<div style="display: grid; grid-template-columns: repeat(${data.columns}, 32px); gap: 4px;">`;
      const cellMap = {};
      data.cells.forEach(c => cellMap[`${c.x}_${c.y}`] = c);

      for (let y = 1; y <= data.rows; y++) {
        for (let x = 1; x <= data.columns; x++) {
          const c = cellMap[`${x}_${y}`];
          if (!c) {
            gridHtml += `<div style="width:32px; height:32px; background:#1e293b; border-radius:4px;"></div>`;
            continue;
          }

          let bg = "#334155";
          let cursor = "default";
          let title = `(${x},${y})`;
          let content = "";
          let isClickable = false;

          if (c.cell_type === 'WALL') {
            bg = "#64748b";
          } else if (c.cell_type === 'DOOR') {
            bg = "#8b5cf6";
          } else if (c.cell_type === 'LABEL') {
            bg = "#0284c7";
            content = c.text_label ? c.text_label.substring(0, 2) : "T";
          } else if (c.cell_type === 'SEAT') {
            content = c.seat_label || "S";
            title = `${c.seat_label} (${c.status})`;
            isClickable = true;
            cursor = "pointer";

            if (c.occupied_by === username) {
              bg = "#3b82f6";
              title += " - Aktueller Platz dieses Users";
            } else if (c.status === 'RESERVED') {
              bg = "#ef4444";
            } else if (c.status === 'PRE') {
              bg = "#f97316";
            } else if (c.status === 'BLOCKED') {
              bg = "#000";
              isClickable = false;
            } else {
              bg = "#22c55e";
            }
          }

          const clickAttr = isClickable ? `onclick="selectSeatForUser(${regId}, ${x}, ${y}, '${c.seat_label || ''}', '${username}')"` : '';
          gridHtml += `<div ${clickAttr} title="${title}" style="background: ${bg}; width: 32px; height: 32px; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: bold; color: white; cursor: ${cursor}; user-select: none;">${content}</div>`;
        }
      }

      gridHtml += '</div>';
      container.innerHTML = gridHtml;
    });
}

function selectSeatForUser(regId, x, y, label, username) {
  if (!confirm(`Möchtest du ${username || 'dem Gast'} den Platz "${label || x + ',' + y}" zuweisen?`)) return;

  fetch('/seating/admin/assign-seat/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getAdminCsrfToken()
    },
    body: JSON.stringify({
      registration_id: regId,
      x: x,
      y: y
    })
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

function deleteSeatAssignment(regId, username) {
  if (!confirm(`Möchtest du die Sitzplatzzuweisung für ${username || 'den Gast'} wirklich löschen? Der Platz wird dadurch wieder freigegeben.`)) return;

  fetch('/seating/admin/release-seat/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getAdminCsrfToken()
    },
    body: JSON.stringify({
      registration_id: regId
    })
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
