
const $ = (s) => document.querySelector(s);
const imageInput = $('#image-input');
const templateIdInput = $('#template-id');
const templateVariantInput = $('#template-variant');
const setFrameBtn = $('#set-frame-btn');
const drawBoxBtn = $('#draw-box-btn');
const drawLineBtn = $('#draw-line-btn');
const modeStatus = $('#mode-status');
const elementTypeInput = $('#element-type');
const elementIdInput = $('#element-id');
const elementFieldKeyInput = $('#element-field-key');
const elementTextInput = $('#element-text');
const elementList = $('#element-list');
const undoBtn = $('#undo-btn');
const resetBtn = $('#reset-btn');
const copyJsonBtn = $('#copy-json-btn');
const downloadJsonBtn = $('#download-json-btn');
const jsonOutput = $('#json-output');
const emptyStage = $('#empty-stage');
const stage = $('#stage');
const stageImage = $('#stage-image');
const stageOverlay = $('#stage-overlay');
const draftRect = $('#draft-rect');
const lineAnchor = $('#line-anchor');

const state = { imageUrl: '', imageWidth: 0, imageHeight: 0, mode: 'frame', frame: null, elements: [], pointerStart: null, lineStart: null };

imageInput.addEventListener('change', handleImageUpload);
setFrameBtn.addEventListener('click', () => setMode('frame'));
drawBoxBtn.addEventListener('click', () => setMode('box'));
drawLineBtn.addEventListener('click', () => setMode('line'));
undoBtn.addEventListener('click', removeLastElement);
resetBtn.addEventListener('click', resetAll);
copyJsonBtn.addEventListener('click', copyJson);
downloadJsonBtn.addEventListener('click', downloadJson);
templateIdInput.addEventListener('input', updateJsonOutput);
templateVariantInput.addEventListener('change', updateJsonOutput);
elementTypeInput.addEventListener('change', syncElementType);
stageOverlay.addEventListener('pointerdown', handlePointerDown);
stageOverlay.addEventListener('pointermove', handlePointerMove);
stageOverlay.addEventListener('pointerup', handlePointerUp);
stageOverlay.addEventListener('pointerleave', cancelDraft);

syncElementType();
setMode('frame');
render();

function handleImageUpload(event) {
  const [file] = event.target.files || [];
  if (!file) return;
  if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
  state.imageUrl = URL.createObjectURL(file);
  stageImage.src = state.imageUrl;
  stageImage.onload = () => {
    state.imageWidth = stageImage.naturalWidth;
    state.imageHeight = stageImage.naturalHeight;
    stageOverlay.setAttribute('viewBox', `0 0 ${state.imageWidth} ${state.imageHeight}`);
    emptyStage.classList.add('hidden');
    stage.classList.remove('hidden');
    resetGeometry();
  };
}

function setMode(mode) {
  state.mode = mode;
  state.pointerStart = null;
  state.lineStart = null;
  draftRect.classList.add('hidden');
  lineAnchor.classList.add('hidden');
  const messages = {
    frame: 'Fiyat blogunun tamamini ciz.',
    box: state.frame ? 'Bir kutu alan ciz.' : 'Once fiyat blogunun tamamini sec.',
    line: state.frame ? 'Cizgi icin ilk noktaya, sonra ikinci noktaya tikla.' : 'Once fiyat blogunun tamamini sec.'
  };
  modeStatus.textContent = messages[mode];
}

function syncElementType() {
  const type = elementTypeInput.value;
  elementFieldKeyInput.disabled = type !== 'field';
  elementTextInput.disabled = type !== 'text';
  if (type === 'line') setMode('line');
}
function handlePointerDown(event) {
  if (!state.imageWidth || !state.imageHeight) return;
  const point = getPointerPoint(event);
  if (!point) return;
  if (state.mode === 'line') {
    if (!state.frame) return setMode('frame');
    if (!state.lineStart) {
      state.lineStart = point;
      const metrics = getStageMetrics();
      lineAnchor.style.left = `${point.x * metrics.scaleX}px`;
      lineAnchor.style.top = `${point.y * metrics.scaleY}px`;
      lineAnchor.classList.remove('hidden');
      modeStatus.textContent = 'Simdi ikinci noktaya tikla.';
      return;
    }
    addLineElement(state.lineStart, point);
    state.lineStart = null;
    lineAnchor.classList.add('hidden');
    return setMode('line');
  }
  state.pointerStart = point;
  draftRect.classList.remove('hidden');
  updateDraftRect(point, point);
}

function handlePointerMove(event) {
  if (!state.pointerStart || state.mode === 'line') return;
  const point = getPointerPoint(event);
  if (!point) return;
  updateDraftRect(state.pointerStart, point);
}

function handlePointerUp(event) {
  if (!state.pointerStart || state.mode === 'line') return;
  const point = getPointerPoint(event);
  if (!point) return cancelDraft();
  const rect = normalizeRect(state.pointerStart, point);
  state.pointerStart = null;
  draftRect.classList.add('hidden');
  if (rect.w < 8 || rect.h < 8) return;
  if (state.mode === 'frame') {
    state.frame = rect;
    state.elements = [];
    setMode('box');
  } else {
    if (!state.frame) return setMode('frame');
    addBoxElement(rect);
  }
  render();
}

function cancelDraft() {
  if (state.mode !== 'line') {
    state.pointerStart = null;
    draftRect.classList.add('hidden');
  }
}

function addBoxElement(rect) {
  const type = elementTypeInput.value === 'line' ? 'field' : elementTypeInput.value;
  const element = { type, id: elementIdInput.value.trim() || `${type}_${state.elements.length + 1}`, x: round4((rect.x - state.frame.x) / state.frame.w), y: round4((rect.y - state.frame.y) / state.frame.h), w: round4(rect.w / state.frame.w), h: round4(rect.h / state.frame.h) };
  if (type === 'field') element.fieldKey = elementFieldKeyInput.value.trim();
  if (type === 'text') element.text = elementTextInput.value.trim();
  state.elements.push(element);
  render();
}

function addLineElement(start, end) {
  state.elements.push({ type: 'line', id: elementIdInput.value.trim() || `line_${state.elements.length + 1}`, x1: round4((start.x - state.frame.x) / state.frame.w), y1: round4((start.y - state.frame.y) / state.frame.h), x2: round4((end.x - state.frame.x) / state.frame.w), y2: round4((end.y - state.frame.y) / state.frame.h) });
  render();
}

function removeLastElement() {
  if (!state.elements.length) {
    if (state.frame) {
      state.frame = null;
      setMode('frame');
      render();
    }
    return;
  }
  state.elements.pop();
  render();
}

function resetAll() { resetGeometry(); render(); }
function resetGeometry() { state.frame = null; state.elements = []; state.pointerStart = null; state.lineStart = null; draftRect.classList.add('hidden'); lineAnchor.classList.add('hidden'); setMode('frame'); }
function render() { renderOverlay(); renderElementList(); updateJsonOutput(); }

function renderOverlay() {
  stageOverlay.innerHTML = '';
  if (state.frame) {
    stageOverlay.appendChild(svgRect(state.frame, 'overlay-frame'));
    stageOverlay.appendChild(svgLabel(state.frame.x + 8, state.frame.y + 16, 'frame'));
  }
  for (const element of state.elements) {
    if (element.type === 'line') {
      const line = denormalizeLine(element);
      stageOverlay.appendChild(svgLine(line, 'overlay-line'));
      stageOverlay.appendChild(svgLabel(line.x1 + 6, line.y1 - 6, element.id));
    } else {
      const rect = denormalizeRect(element);
      stageOverlay.appendChild(svgRect(rect, 'overlay-box'));
      stageOverlay.appendChild(svgLabel(rect.x + 6, rect.y + 16, element.id));
    }
  }
}

function renderElementList() {
  elementList.innerHTML = '';
  if (!state.frame && !state.elements.length) {
    elementList.innerHTML = '<p class="helper">Henuz alan eklenmedi.</p>';
    return;
  }
  if (state.frame) elementList.appendChild(buildChip('frame', `x:${round4(state.frame.x)}, y:${round4(state.frame.y)}, w:${round4(state.frame.w)}, h:${round4(state.frame.h)}`));
  for (const element of state.elements) {
    const detail = element.type === 'line' ? `(${element.x1}, ${element.y1}) -> (${element.x2}, ${element.y2})` : `x:${element.x}, y:${element.y}, w:${element.w}, h:${element.h}`;
    elementList.appendChild(buildChip(`${element.id} • ${element.type}`, detail));
  }
}

function buildChip(title, detail) {
  const chip = document.createElement('article');
  chip.className = 'element-chip';
  const strong = document.createElement('strong');
  strong.textContent = title;
  const small = document.createElement('small');
  small.textContent = detail;
  chip.append(strong, small);
  return chip;
}

function updateJsonOutput() { jsonOutput.value = JSON.stringify(buildTemplatePayload(), null, 2); }

function buildTemplatePayload() {
  const frame = state.frame ? { x: round4(state.frame.x / state.imageWidth), y: round4(state.frame.y / state.imageHeight), w: round4(state.frame.w / state.imageWidth), h: round4(state.frame.h / state.imageHeight) } : { x: 0, y: 0, w: 1, h: 1 };
  return {
    templateId: templateIdInput.value.trim() || 'price-block-v1',
    blockType: 'price-block',
    variant: templateVariantInput.value,
    frame,
    cleanup: { mode: 'erase-underlay' },
    fonts: { primaryBold: 'SofiaSans-Bold', primarySemiBold: 'SofiaSans-SemiBold', primaryRegular: 'SofiaSans-Regular' },
    elements: state.elements.map((element) => {
      if (element.type === 'line') return { type: 'line', id: element.id, x1: element.x1, y1: element.y1, x2: element.x2, y2: element.y2 };
      const payload = { type: element.type, id: element.id, x: element.x, y: element.y, w: element.w, h: element.h };
      if (element.type === 'field' && element.fieldKey) payload.fieldKey = element.fieldKey;
      if (element.type === 'text' && element.text) payload.text = element.text;
      return payload;
    })
  };
}

async function copyJson() {
  await navigator.clipboard.writeText(jsonOutput.value);
  modeStatus.textContent = 'JSON panoya kopyalandi.';
}

function downloadJson() {
  const blob = new Blob([jsonOutput.value], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${templateVariantInput.value}-price-block.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
function getPointerPoint(event) {
  const bounds = stageImage.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return null;
  const x = ((event.clientX - bounds.left) / bounds.width) * state.imageWidth;
  const y = ((event.clientY - bounds.top) / bounds.height) * state.imageHeight;
  return { x: clamp(x, 0, state.imageWidth), y: clamp(y, 0, state.imageHeight) };
}

function updateDraftRect(start, end) {
  const rect = normalizeRect(start, end);
  const metrics = getStageMetrics();
  draftRect.style.left = `${rect.x * metrics.scaleX}px`;
  draftRect.style.top = `${rect.y * metrics.scaleY}px`;
  draftRect.style.width = `${rect.w * metrics.scaleX}px`;
  draftRect.style.height = `${rect.h * metrics.scaleY}px`;
}

function getStageMetrics() {
  const bounds = stageImage.getBoundingClientRect();
  return {
    scaleX: bounds.width / Math.max(state.imageWidth, 1),
    scaleY: bounds.height / Math.max(state.imageHeight, 1)
  };
}

function normalizeRect(start, end) { return { x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), w: Math.abs(end.x - start.x), h: Math.abs(end.y - start.y) }; }
function denormalizeRect(element) { return { x: state.frame.x + element.x * state.frame.w, y: state.frame.y + element.y * state.frame.h, w: element.w * state.frame.w, h: element.h * state.frame.h }; }
function denormalizeLine(element) { return { x1: state.frame.x + element.x1 * state.frame.w, y1: state.frame.y + element.y1 * state.frame.h, x2: state.frame.x + element.x2 * state.frame.w, y2: state.frame.y + element.y2 * state.frame.h }; }
function svgRect(rect, className) { const node = document.createElementNS('http://www.w3.org/2000/svg', 'rect'); node.setAttribute('x', rect.x); node.setAttribute('y', rect.y); node.setAttribute('width', rect.w); node.setAttribute('height', rect.h); node.setAttribute('class', className); return node; }
function svgLine(line, className) { const node = document.createElementNS('http://www.w3.org/2000/svg', 'line'); node.setAttribute('x1', line.x1); node.setAttribute('y1', line.y1); node.setAttribute('x2', line.x2); node.setAttribute('y2', line.y2); node.setAttribute('class', className); return node; }
function svgLabel(x, y, text) { const node = document.createElementNS('http://www.w3.org/2000/svg', 'text'); node.setAttribute('x', x); node.setAttribute('y', y); node.setAttribute('class', 'overlay-label'); node.textContent = text; return node; }
function round4(value) { return Number(value.toFixed(4)); }
function clamp(value, min, max) { return Math.min(max, Math.max(min, value)); }



