(() => {
  const form = document.getElementById('media-editor-form');
  if (!form) return;

  const canvas = document.getElementById('media-canvas');
  const hidden = document.getElementById('id_elements');
  const kind = document.getElementById('id_kind');
  const paper = document.getElementById('id_paper_size');
  const backgroundInput = document.getElementById('id_background');
  const labels = JSON.parse(document.getElementById('media-field-labels').textContent);
  const sizes = JSON.parse(document.getElementById('media-paper-mm').textContent);
  const list = document.getElementById('media-field-list');
  const controls = document.getElementById('media-field-controls');
  const source = document.getElementById('media-source');
  const staticWrap = document.getElementById('media-static-wrap');
  const staticText = document.getElementById('media-static-text');
  const inputs = {
    x: document.getElementById('media-x'),
    y: document.getElementById('media-y'),
    width: document.getElementById('media-width'),
    font_size_mm: document.getElementById('media-font-size'),
    color: document.getElementById('media-color'),
    align: document.getElementById('media-align'),
  };
  let elements;
  try { elements = JSON.parse(hidden.value); }
  catch { elements = JSON.parse(document.getElementById('media-elements').textContent); }
  if (!Array.isArray(elements)) elements = [];
  let selected = elements.length ? 0 : -1;
  let uploadedUrl = null;

  const sample = {
    'guest.username': canvas.dataset.sampleGuest,
    'guest.clan': 'Clan',
    'guest.seat': 'A-12',
    'team.name': canvas.dataset.sampleTeam,
    'team.placement': '1. Platz',
    'award.title': 'Turnierurkunde',
    'tournament.title': 'LAN Cup',
    'event.title': 'LAN Event',
  };

  function currentSize() { return sizes[paper.value] || sizes.A8; }
  function fieldName(element) {
    return element.source === 'static' ? (element.text || canvas.dataset.staticLabel)
      : (labels[kind.value]?.[element.source] || element.source);
  }
  function current() { return elements[selected]; }
  function write() { hidden.value = JSON.stringify(elements); }

  function updateSourceOptions() {
    source.replaceChildren();
    Object.entries(labels[kind.value] || {}).forEach(([value, label]) => {
      source.add(new Option(label, value));
    });
    source.add(new Option(canvas.dataset.staticLabel, 'static'));
  }

  function render() {
    const [widthMm, heightMm] = currentSize();
    canvas.style.aspectRatio = `${widthMm} / ${heightMm}`;
    canvas.replaceChildren();
    list.replaceChildren();
    elements.forEach((element, index) => {
      const label = fieldName(element);
      const box = document.createElement('div');
      box.className = 'media-element' + (index === selected ? ' is-selected' : '');
      box.textContent = element.source === 'static' ? element.text : (sample[element.source] || label);
      box.style.left = `${element.x * 100}%`;
      box.style.top = `${element.y * 100}%`;
      box.style.width = `${element.width * 100}%`;
      box.style.color = element.color;
      box.style.textAlign = element.align;
      box.style.fontSize = `${Math.max(9, element.font_size_mm / widthMm * canvas.clientWidth)}px`;
      box.addEventListener('pointerdown', event => {
        event.preventDefault();
        selected = index;
        const startX = event.clientX;
        const startY = event.clientY;
        const originalX = element.x;
        const originalY = element.y;
        box.setPointerCapture(event.pointerId);
        box.onpointermove = move => {
          const rect = canvas.getBoundingClientRect();
          element.x = Math.max(0, Math.min(1 - element.width, originalX + (move.clientX - startX) / rect.width));
          element.y = Math.max(0, Math.min(0.98, originalY + (move.clientY - startY) / rect.height));
          box.style.left = `${element.x * 100}%`;
          box.style.top = `${element.y * 100}%`;
          inputs.x.value = (element.x * 100).toFixed(1);
          inputs.y.value = (element.y * 100).toFixed(1);
          write();
        };
        box.onpointerup = () => { box.onpointermove = null; box.onpointerup = null; render(); };
        renderSelection();
      });
      canvas.appendChild(box);

      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.className = index === selected ? 'is-selected' : '';
      button.addEventListener('click', () => { selected = index; render(); });
      list.appendChild(button);
    });
    renderSelection();
    write();
  }

  function renderSelection() {
    const element = current();
    controls.hidden = !element;
    if (!element) return;
    updateSourceOptions();
    source.value = element.source;
    staticWrap.hidden = element.source !== 'static';
    staticText.value = element.text || '';
    for (const key of ['x', 'y', 'width']) inputs[key].value = (element[key] * 100).toFixed(1);
    inputs.font_size_mm.value = element.font_size_mm;
    inputs.color.value = element.color;
    inputs.align.value = element.align;
  }

  document.getElementById('media-add-field').addEventListener('click', () => {
    if (elements.length >= 30) return;
    const firstSource = Object.keys(labels[kind.value] || {})[0] || 'static';
    elements.push({ source: firstSource, text: '', x: 0.1, y: 0.2,
      width: 0.8, font_size_mm: 4, color: '#172033', align: 'center' });
    selected = elements.length - 1;
    render();
  });
  document.getElementById('media-remove-field').addEventListener('click', () => {
    if (selected < 0) return;
    elements.splice(selected, 1);
    selected = Math.min(selected, elements.length - 1);
    render();
  });
  source.addEventListener('change', () => { current().source = source.value; render(); });
  staticText.addEventListener('input', () => { current().text = staticText.value; render(); });
  Object.entries(inputs).forEach(([key, input]) => input.addEventListener('input', () => {
    if (!current()) return;
    if (['x', 'y', 'width'].includes(key)) current()[key] = Number(input.value) / 100;
    else if (key === 'font_size_mm') current()[key] = Number(input.value);
    else current()[key] = input.value;
    if (current().x + current().width > 1) current().width = 1 - current().x;
    render();
  }));
  kind.addEventListener('change', () => { elements = []; selected = -1; render(); });
  paper.addEventListener('change', render);
  backgroundInput.addEventListener('change', () => {
    if (uploadedUrl) URL.revokeObjectURL(uploadedUrl);
    uploadedUrl = backgroundInput.files[0] ? URL.createObjectURL(backgroundInput.files[0]) : null;
    canvas.style.backgroundImage = uploadedUrl ? `url("${uploadedUrl}")` :
      (canvas.dataset.background ? `url("${canvas.dataset.background}")` : 'none');
  });
  if (canvas.dataset.background) canvas.style.backgroundImage = `url("${canvas.dataset.background}")`;
  form.addEventListener('submit', write);
  render();
  new ResizeObserver(render).observe(canvas);
})();
