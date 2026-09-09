/**
 * seating.js - Interaktiver Sitzplan-Viewer
 * Kapselt Pan/Zoom (Maus, Tastatur & Touch-Gesten), Raster-Rendering,
 * Platz-Reservierungs-Modals und dynamische Belegungs-Updates via AJAX.
 */

(function() {
  'use strict';

  // Vektor-SVG Icons für Kacheln (Theme-reaktiv via currentColor)
  const SVG_ICONS = {
    free: `<svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" style="position: absolute; top: 2px; right: 2px; opacity: 0.7;"><circle cx="12" cy="12" r="8"></circle></svg>`,
    pre_reserved: `<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="position: absolute; top: 2px; right: 2px;"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`,
    reserved: `<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="position: absolute; top: 2px; right: 2px;"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>`,
    clan: `<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="position: absolute; top: 2px; right: 2px;"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>`,
    own: `<svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1" style="position: absolute; top: 2px; right: 2px;"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>`,
    blocked: `<svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="position: absolute; top: 2px; right: 2px;"><circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line></svg>`
  };

  let currentScale = 1;
  let pointX = 0;
  let pointY = 0;
  let startX = 0;
  let startY = 0;
  let isPanning = false;

  // Touch-spezifische Variablen
  let initialTouchDistance = null;
  let initialScale = 1;

  let targetSeatX = null;
  let targetSeatY = null;

  let config = {};

  function initSeatingViewer(cfg) {
    config = cfg || {};
    const eventId = config.eventId;
    if (!eventId) return;

    loadSeatingData();

    // Bei Fenstergrößenänderung auf Mobilgeräten einpassen
    window.addEventListener('resize', () => {
      if (window.lastSeatingData && window.innerWidth < 768 && window.fitToViewport) {
        window.fitToViewport(window.lastSeatingData);
      }
    });

    // Escape-Taste schließt Reservierungsmodal
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeReserveModal();
      }
    });

    const btnConfirm = document.getElementById('btn-confirm-reserve');
    if (btnConfirm) {
      btnConfirm.onclick = confirmReservation;
    }
  }

  function loadSeatingData() {
    const eventId = config.eventId;
    fetch(`/seating/api/plan/${eventId}/`)
      .then(response => {
        if (!response.ok) throw new Error("Sitzplan konnte nicht geladen werden.");
        return response.json();
      })
      .then(data => {
        window.lastSeatingData = data;
        const statusEl = document.getElementById('seating-status');
        if (statusEl) statusEl.style.display = 'none';
        renderGrid(data);
        initPanZoom(data);
      })
      .catch(err => {
        const statusEl = document.getElementById('seating-status');
        if (statusEl) statusEl.innerText = err.message;
      });
  }
  window.loadSeatingData = loadSeatingData;

  function renderGrid(data) {
    const grid = document.getElementById('seating-grid');
    if (!grid) return;
    grid.innerHTML = '';

    let minX = 0, minY = 0, maxX = data.columns - 1, maxY = data.rows - 1;
    if (data.cells && data.cells.length > 0) {
      minX = Math.min(...data.cells.map(c => c.x));
      minY = Math.min(...data.cells.map(c => c.y));
      maxX = Math.max(...data.cells.map(c => c.x), data.columns - 1);
      maxY = Math.max(...data.cells.map(c => c.y), data.rows - 1);
    }

    const totalCols = (maxX - minX) + 1;
    grid.style.gridTemplateColumns = `repeat(${totalCols}, 36px)`;

    const cellMap = {};
    data.cells.forEach(c => {
      cellMap[`${c.x}_${c.y}`] = c;
    });

    const fragment = document.createDocumentFragment();

    for (let y = minY; y <= maxY; y++) {
      for (let x = minX; x <= maxX; x++) {
        const cellData = cellMap[`${x}_${y}`];
        const cellEl = document.createElement('div');

        cellEl.style.width = '36px';
        cellEl.style.height = '36px';
        cellEl.style.borderRadius = '5px';
        cellEl.style.display = 'flex';
        cellEl.style.flexDirection = 'column';
        cellEl.style.alignItems = 'center';
        cellEl.style.justifyContent = 'center';
        cellEl.style.fontSize = '10px';
        cellEl.style.fontWeight = 'bold';
        cellEl.style.fontFamily = "'JetBrains Mono', monospace";
        cellEl.style.boxSizing = 'border-box';
        cellEl.style.position = 'relative';
        cellEl.style.transition = 'transform 0.15s ease, box-shadow 0.15s ease';

        if (!cellData || cellData.cell_type === 'EMPTY') {
          cellEl.style.background = 'transparent';

        } else if (cellData.cell_type === 'SEAT') {
          const seatLabel = cellData.seat_label || `${x},${y}`;
          let tooltipText = "";
          let statusIconHtml = "";

          if (cellData.status === 'FREE') {
            cellEl.style.background = 'rgba(34, 197, 94, 0.12)';
            cellEl.style.border = '1px solid #22c55e';
            cellEl.style.color = '#4ade80';
            statusIconHtml = SVG_ICONS.free;
            tooltipText = `Platz ${seatLabel}: Frei`;

            if (config.isUserLoggedIn) {
              cellEl.style.cursor = 'pointer';
              cellEl.onmouseenter = () => { cellEl.style.transform = 'scale(1.08)'; cellEl.style.boxShadow = '0 0 8px rgba(34, 197, 94, 0.4)'; };
              cellEl.onmouseleave = () => { cellEl.style.transform = 'scale(1)'; cellEl.style.boxShadow = 'none'; };
              cellEl.onclick = function(e) {
                e.stopPropagation();
                openReserveModal(x, y, seatLabel);
              };
            }

          } else if (cellData.status === 'PRE_RESERVED' || cellData.status === 'RESERVED') {
            const currentUsername = config.username || '';
            const isOwnSeat = currentUsername && (cellData.occupied_by === currentUsername);
            const isSameClan = data.user_clan_name && cellData.clan_name && (data.user_clan_name === cellData.clan_name);
            const occupantText = cellData.clan_name
              ? `${cellData.occupied_by} (${cellData.clan_name})`
              : cellData.occupied_by;

            if (isOwnSeat) {
              // Eigener Sitzplatz: Leuchtendes Theme-Highlight (var(--signal)) mit Star-SVG
              cellEl.style.background = 'var(--signal, #f8ab2d)';
              cellEl.style.border = '2px solid #ffffff';
              cellEl.style.color = 'var(--navy, #332719)';
              cellEl.style.boxShadow = '0 0 12px var(--signal, #f8ab2d)';
              cellEl.style.zIndex = '5';
              statusIconHtml = SVG_ICONS.own;
              tooltipText = `Dein reservierter Sitzplatz: ${seatLabel}`;
            } else if (isSameClan) {
              // Clan-Mitglied: Blauer Akzentrahmen + Shield-SVG
              cellEl.style.background = 'rgba(56, 189, 248, 0.25)';
              cellEl.style.border = '1.5px solid #38bdf8';
              cellEl.style.color = '#7dd3fc';
              statusIconHtml = SVG_ICONS.clan;
            } else if (cellData.status === 'PRE_RESERVED') {
              // Vorgemerkt: Gestrichelter gelber Rand + Clock-SVG
              cellEl.style.background = 'rgba(234, 179, 8, 0.15)';
              cellEl.style.border = '1.5px dashed #eab308';
              cellEl.style.color = '#fde047';
              statusIconHtml = SVG_ICONS.pre_reserved;
            } else {
              // Fest bezahlt / Reserviert: Solider roter Rand + Lock-SVG
              cellEl.style.background = 'rgba(239, 68, 68, 0.22)';
              cellEl.style.border = '1px solid #ef4444';
              cellEl.style.color = '#fca5a5';
              statusIconHtml = SVG_ICONS.reserved;
            }

            if (!isOwnSeat) {
              const statusLabel = cellData.status === 'PRE_RESERVED' ? 'Vorgemerkt' : 'Reserviert';
              tooltipText = cellData.occupied_by 
                ? `Platz ${seatLabel}: ${statusLabel} von ${occupantText}`
                : `Platz ${seatLabel}: ${statusLabel}`;
            }

          } else {
            // Gesperrt: Diagonale Schraffur + Ban-SVG
            cellEl.style.background = 'repeating-linear-gradient(45deg, #1f2937, #1f2937 3px, #374151 3px, #374151 6px)';
            cellEl.style.border = '1px solid #4b5563';
            cellEl.style.color = '#9ca3af';
            statusIconHtml = SVG_ICONS.blocked;
            tooltipText = 'Platz gesperrt';
          }

          cellEl.innerHTML = `${statusIconHtml}<span>${seatLabel}</span>`;

          if (tooltipText) {
            cellEl.title = tooltipText;
          }

        } else if (cellData.cell_type === 'DOOR') {
          cellEl.style.background = 'rgba(56, 189, 248, 0.15)';
          cellEl.style.border = '1px dashed #38bdf8';
          cellEl.style.color = '#38bdf8';
          cellEl.innerText = cellData.text_label || '🚪';
          cellEl.title = 'TÜR / EINGANG';

        } else {
          cellEl.style.background = '#1f2937';
          cellEl.style.border = '1px solid #374151';
          cellEl.style.color = '#9ca3af';
          cellEl.innerText = cellData.text_label || '';
        }

        fragment.appendChild(cellEl);
      }
    }

    grid.appendChild(fragment);
  }

  /* MODAL STEUERUNG */
  function openReserveModal(x, y, seatLabel) {
    targetSeatX = x;
    targetSeatY = y;
    const modal = document.getElementById('reserve-modal');
    const modalText = document.getElementById('reserve-modal-text');
    const rawConfirm = config.rawConfirmText || 'Möchtest du den Sitzplatz {seat} verbindlich reservieren?';
    if (modalText) {
      modalText.innerText = rawConfirm.replace('{seat}', seatLabel);
    }
    if (modal) modal.style.display = 'flex';
  }
  window.openReserveModal = openReserveModal;

  function closeReserveModal() {
    const modal = document.getElementById('reserve-modal');
    if (modal) modal.style.display = 'none';
    targetSeatX = null;
    targetSeatY = null;
  }
  window.closeReserveModal = closeReserveModal;

  function confirmReservation() {
    if (targetSeatX === null || targetSeatY === null) return;

    fetch(`/seating/api/reserve/${config.eventId}/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': config.csrfToken
      },
      body: JSON.stringify({ x: targetSeatX, y: targetSeatY })
    })
    .then(res => res.json())
    .then(data => {
      closeReserveModal();
      if (data.status === 'success') {
        loadSeatingData();
      } else {
        alert(data.message || 'Fehler bei der Reservierung.');
      }
    })
    .catch(err => {
      closeReserveModal();
      alert('Netzwerkfehler bei der Reservierung.');
    });
  }

  /* PAN & ZOOM IMPLEMENTIERUNG */
  function initPanZoom(data) {
    const viewport = document.getElementById('viewport');
    const canvas = document.getElementById('pan-canvas');
    const zoomBadge = document.getElementById('zoom-level-badge');
    if (!viewport || !canvas) return;

    function updateTransform() {
      canvas.style.transform = `translate(${pointX}px, ${pointY}px) scale(${currentScale})`;
      if (zoomBadge) {
        zoomBadge.textContent = `${Math.round(currentScale * 100)}%`;
      }
    }

    window.fitToViewport = function(planData = data) {
      const viewportWidth = viewport.clientWidth;
      const viewportHeight = viewport.clientHeight;

      let minX = 0, minY = 0, maxX = planData.columns - 1, maxY = planData.rows - 1;
      if (planData.cells && planData.cells.length > 0) {
        minX = Math.min(...planData.cells.map(c => c.x));
        minY = Math.min(...planData.cells.map(c => c.y));
        maxX = Math.max(...planData.cells.map(c => c.x), data.columns - 1);
        maxY = Math.max(...planData.cells.map(c => c.y), data.rows - 1);
      }

      const totalCols = (maxX - minX) + 1;
      const totalRows = (maxY - minY) + 1;

      const gridWidth = (totalCols * 41) + 48;
      const gridHeight = (totalRows * 41) + 48;

      const scaleX = viewportWidth / gridWidth;
      const scaleY = viewportHeight / gridHeight;

      currentScale = Math.min(scaleX, scaleY, 1.2);

      pointX = (viewportWidth - (gridWidth * currentScale)) / 2;
      pointY = (viewportHeight - (gridHeight * currentScale)) / 2;

      updateTransform();
    };

    function initialSetup(planData = data) {
      const isDesktop = window.innerWidth >= 768;
      const viewportWidth = viewport.clientWidth;
      const viewportHeight = viewport.clientHeight;

      let minX = 0, minY = 0, maxX = planData.columns - 1, maxY = planData.rows - 1;
      if (planData.cells && planData.cells.length > 0) {
        minX = Math.min(...planData.cells.map(c => c.x));
        minY = Math.min(...planData.cells.map(c => c.y));
        maxX = Math.max(...planData.cells.map(c => c.x), data.columns - 1);
        maxY = Math.max(...planData.cells.map(c => c.y), data.rows - 1);
      }

      const totalCols = (maxX - minX) + 1;
      const totalRows = (maxY - minY) + 1;
      const gridWidth = (totalCols * 41) + 48;
      const gridHeight = (totalRows * 41) + 48;

      if (isDesktop) {
        const fitScale = Math.min(viewportWidth / gridWidth, viewportHeight / gridHeight);
        currentScale = Math.max(1.0, Math.min(fitScale, 1.3));

        const currentUsername = config.username || '';
        const ownCell = currentUsername && planData.cells ? planData.cells.find(c => c.occupied_by === currentUsername) : null;

        if (ownCell) {
          const seatPosX = ((ownCell.x - minX) * 41) + 24 + 18;
          const seatPosY = ((ownCell.y - minY) * 41) + 24 + 18;
          pointX = (viewportWidth / 2) - (seatPosX * currentScale);
          pointY = (viewportHeight / 2) - (seatPosY * currentScale);
        } else {
          pointX = (viewportWidth - (gridWidth * currentScale)) / 2;
          pointY = (viewportHeight - (gridHeight * currentScale)) / 2;
        }
        updateTransform();
      } else {
        window.fitToViewport(planData);
      }
    }

    initialSetup();

    // Tastatur-Shortcuts für Zoom (+/- und 0 für Reset)
    document.addEventListener('keydown', function(e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === '+' || e.key === '=') {
        currentScale = Math.min(currentScale * 1.2, 3);
        updateTransform();
      } else if (e.key === '-' || e.key === '_') {
        currentScale = Math.max(currentScale * 0.8, 0.15);
        updateTransform();
      } else if (e.key === '0' && window.fitToViewport) {
        window.fitToViewport();
      }
    });

    // --- MAUS EVENTS ---
    viewport.addEventListener('mousedown', function(e) {
      startX = e.clientX - pointX;
      startY = e.clientY - pointY;
      isPanning = true;
      viewport.style.cursor = 'grabbing';
    });

    window.addEventListener('mouseup', function() {
      isPanning = false;
      viewport.style.cursor = 'grab';
    });

    window.addEventListener('mousemove', function(e) {
      if (!isPanning) return;
      e.preventDefault();
      pointX = e.clientX - startX;
      pointY = e.clientY - startY;
      updateTransform();
    });

    viewport.addEventListener('wheel', function(e) {
      e.preventDefault();
      const xs = (e.clientX - pointX) / currentScale;
      const ys = (e.clientY - pointY) / currentScale;
      const delta = e.deltaY < 0 ? 1.1 : 0.9;
      const newScale = Math.min(Math.max(0.15, currentScale * delta), 3);

      pointX = e.clientX - xs * newScale;
      pointY = e.clientY - ys * newScale;
      currentScale = newScale;

      updateTransform();
    }, { passive: false });

    // --- TOUCH EVENTS (FOR MOBILES) ---
    function getTouchDistance(touches) {
      return Math.hypot(
        touches[0].clientX - touches[1].clientX,
        touches[0].clientY - touches[1].clientY
      );
    }

    viewport.addEventListener('touchstart', function(e) {
      if (e.touches.length === 1) {
        isPanning = true;
        startX = e.touches[0].clientX - pointX;
        startY = e.touches[0].clientY - pointY;
      } else if (e.touches.length === 2) {
        isPanning = false;
        initialTouchDistance = getTouchDistance(e.touches);
        initialScale = currentScale;
      }
    }, { passive: true });

    viewport.addEventListener('touchmove', function(e) {
      if (isPanning && e.touches.length === 1) {
        e.preventDefault();
        pointX = e.touches[0].clientX - startX;
        pointY = e.touches[0].clientY - startY;
        updateTransform();
      } else if (e.touches.length === 2 && initialTouchDistance) {
        e.preventDefault();
        const currentDistance = getTouchDistance(e.touches);
        const scaleFactor = currentDistance / initialTouchDistance;
        currentScale = Math.min(Math.max(0.15, initialScale * scaleFactor), 3);
        updateTransform();
      }
    }, { passive: false });

    viewport.addEventListener('touchend', function(e) {
      if (e.touches.length < 2) initialTouchDistance = null;
      if (e.touches.length === 0) isPanning = false;
    });

    // Controls
    const btnIn = document.getElementById('btn-zoom-in');
    const btnOut = document.getElementById('btn-zoom-out');
    const btnReset = document.getElementById('btn-zoom-reset');

    if (btnIn) btnIn.onclick = () => { currentScale = Math.min(currentScale * 1.2, 3); updateTransform(); };
    if (btnOut) btnOut.onclick = () => { currentScale = Math.max(currentScale * 0.8, 0.15); updateTransform(); };
    if (btnReset) btnReset.onclick = () => { if (window.fitToViewport) window.fitToViewport(); };
  }

  // Auto-init on DOMContentLoaded if config block exists
  document.addEventListener('DOMContentLoaded', function() {
    const configEl = document.getElementById('seating-config');
    if (configEl) {
      try {
        const parsed = JSON.parse(configEl.textContent);
        initSeatingViewer(parsed);
      } catch (err) {
        console.error("Fehler beim Parsen der Sitzplan-Konfiguration:", err);
      }
    }
  });

  window.initSeatingViewer = initSeatingViewer;

})();
