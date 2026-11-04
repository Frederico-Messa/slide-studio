'use strict';

const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="studio-token"]').content;
const studioInstance = document.querySelector('meta[name="studio-instance"]').content;
const ui = { presentation: '', variant: '', language: 'pt-BR', slide: '', selectedIndex: 0, state: null, settings: null, previewUrl: '', tab: 'ai', mainMode: 'slides', factCategory: '', assetFolder: '', factDraft: false, assetAnchor: '', diffs: [], busy: false, viewSource: false, aiJob: '', modelCapabilities: new Map(), sourceDraft: false, previewGeneration: 0, savedSource: null, savedSourceKey: "", sourceDiffRequest: 0, sourcePaintTimer: null, sourceUndo: [], sourceRedo: [], sourceEditTime: 0, sourceEditKind: '', sourceInputBefore: null, sourceComposing: false, previewReady: false, lastCategory: {facts: '', assets: ''}, selected: {facts: new Set(), assets: new Set()}, collapsed: {facts: new Set(), assets: new Set()}, visible: {facts: [], assets: []}, scopeByMode: {}, promptByMode: {}, currentScope: 'slide', serverOnline: true, showHiddenInNavigation: true };
const icons = {
  edit: '<svg viewBox="0 0 24 24"><path d="m4 16 0 4 4 0L20 8l-4-4L4 16Z"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6m4-6v6M6 7l1 14h10l1-14M9 7V4h6v3"/></svg>'
};

async function api(path, method = 'GET', payload = null) {
  const options = { method, headers: method === 'GET' ? {} : { 'Content-Type': 'application/json', 'X-Studio-Token': token }, cache: 'no-store' };
  if (payload !== null) options.body = JSON.stringify(payload);
  let response;
  try { response = await fetch(path, options); }
  catch (error) { setServerAvailability(false); throw new Error('Local server unavailable'); }
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function hasUnsavedChanges() {
  return Boolean(ui.state?.dirty || ui.sourceDraft || ui.factDraft || scriptState.draft || recipeState.draft);
}

function updateSaveIndicator() {
  const unsaved = hasUnsavedChanges();
  const indicator = $('save-indicator');
  indicator.textContent = ui.serverOnline ? (unsaved ? 'Unsaved' : 'Saved') : (unsaved ? 'Unsaved · Server offline' : 'Server offline');
  indicator.classList.toggle('unsaved', unsaved);
  indicator.classList.toggle('offline', !ui.serverOnline);
  indicator.title = ui.serverOnline ? 'Local server available' : 'Local application server unavailable';
  $('save-button').disabled = !ui.serverOnline || !(ui.state?.dirty || ui.factDraft) || ui.busy || Boolean(scriptState.draft) || Boolean(recipeState.draft);
}

function setServerAvailability(available) {
  ui.serverOnline = available;
  updateSaveIndicator();
}

let healthCheckInProgress = false;
async function checkServerHealth() {
  if (healthCheckInProgress) return;
  healthCheckInProgress = true;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2500);
  let available = false;
  try {
    const response = await fetch('/api/health', {cache: 'no-store', signal: controller.signal});
    if (response.ok) available = (await response.json()).instance === studioInstance;
  } catch (error) {
    available = false;
  } finally {
    clearTimeout(timer);
    healthCheckInProgress = false;
  }
  setServerAvailability(available);
}

function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character]));
}

function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 4000);
}

function dateLocal() {
  const date = new Date();
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
}

function hasPresentation() {
  return Boolean(ui.presentation && ui.state?.sources);
}

function currentVariant() {
  return ui.state?.variants?.variants?.[ui.variant] || null;
}

function setTheme(theme) {
  const value = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = value;
  $('theme-toggle').title = value === 'dark' ? 'Light mode' : 'Dark mode';
  $('theme-toggle').setAttribute('aria-label', $('theme-toggle').title);
}

function rememberChoices() {
  api('/api/session', 'POST', { presentation: ui.presentation, variant: ui.variant, slide: ui.slide, language: ui.language, scope: document.querySelector('input[name="scope"]:checked').value }).catch((error) => toast(error.message));
}

async function loadState(render = false) {
  const priorState = ui.state;
  const state = await api(`/api/state?presentation=${encodeURIComponent(ui.presentation)}`);
  ui.state = state;
  if (!state.presentations.some((item) => item.id === ui.presentation)) {
    ui.presentation = state.presentations[0]?.id || '';
    if (ui.presentation) ui.state = await api(`/api/state?presentation=${encodeURIComponent(ui.presentation)}`);
  }
  const select = $('presentation-select');
  select.replaceChildren();
  if (!ui.state.presentations.length) select.add(new Option('No presentations', ''));
  for (const presentation of ui.state.presentations) select.add(new Option(presentation.name, presentation.id));
  select.value = ui.presentation;
  select.disabled = !ui.state.presentations.length;
  $('presentation-settings').disabled = !ui.presentation;
  const variantSelect = $('variant-select');
  variantSelect.replaceChildren();
  const variants = ui.state.variants;
  if (variants) {
    for (const [id, variant] of Object.entries(variants.variants)) variantSelect.add(new Option(variant.name, id));
    if (!variants.variants[ui.variant]) ui.variant = variants.default;
  } else {
    ui.variant = '';
    variantSelect.add(new Option('Standard', ''));
  }
  variantSelect.value = ui.variant;
  variantSelect.disabled = !variants;

  const active = currentVariant();
  if (active) {
    ui.state.slides = ui.state.allSlides || [];
    $('preview-frame').style.setProperty('--preview-ratio', String(active.width / active.height));
  } else {
    $('preview-frame').style.setProperty('--preview-ratio', String(16 / 9));
  }
  chooseSlide(ui.slide);
  updateSaveIndicator();
  $('undo-button').disabled = !ui.state.canUndo || ui.busy;
  $('redo-button').disabled = !ui.state.canRedo || ui.busy;
  updateSourceStage();
  $('view-source').disabled = !hasPresentation();
  updateActionState();
  if (ui.mainMode === 'facts') renderFacts();
  if (ui.mainMode === 'assets') renderAssets();
  if (ui.tab === 'changes') await renderChanges();
  const contentsChanged = priorState && priorState.revision !== ui.state.revision;
  if (ui.mainMode === 'scripts' && (contentsChanged || !priorState)) await renderScripts();
  if (ui.mainMode === 'recipes' && (contentsChanged || !priorState)) await renderRecipes();
  if (render || contentsChanged) {
    if (ui.mainMode === 'facts' || ui.mainMode === 'assets' || ui.mainMode === 'scripts' || ui.mainMode === 'recipes' || ui.mainMode === 'source') { ui.previewUrl = ''; ui.previewReady = false; }
    else if (ui.mainMode === 'slides') await renderPreview();
  }
  if (ui.mainMode === 'source' && (render || contentsChanged)) refreshSourceDiff().catch((error) => toast(error.message));
  if (contentsChanged || !priorState) api('/api/precompute', 'POST', {}).catch(() => {});
}

function layoutSlidePreview() {
  if (!ui.previewReady || ui.mainMode !== 'slides') return;
  const frame = $('slide-iframe');
  requestAnimationFrame(() => {
    frame.contentWindow?.postMessage({type: 'studio-layout'}, '*');
    setTimeout(() => frame.contentWindow?.postMessage({type: 'studio-layout'}, '*'), 110);
  });
}

async function renderPreview() {
  if (ui.mainMode === 'facts' || ui.mainMode === 'assets' || ui.mainMode === 'scripts' || ui.mainMode === 'recipes') return;
  const generation = ++ui.previewGeneration;
  const target = ui.presentation;
  const language = ui.language;
  const variant = ui.variant;
  const iframe = $('slide-iframe');
  ui.previewReady = false;
  $('hidden-slide-overlay').hidden = true;
  $('empty-stage').hidden = true;
  $('preview-error').hidden = true;
  $('loading-preview').hidden = !hasPresentation() || ui.mainMode !== 'slides';
  $('open-preview').disabled = true;
  $('export-pdf').disabled = true;
  if (!hasPresentation()) {
    ui.previewUrl = '';
    iframe.hidden = true;
    $('empty-stage').hidden = ui.mainMode !== 'slides';
    updateSourceStage();
    return;
  }
  try {
    const result = await api(`/api/preview?presentation=${encodeURIComponent(target)}&language=${encodeURIComponent(language)}&variant=${encodeURIComponent(variant)}&includeHidden=1`);
    if (generation !== ui.previewGeneration || target !== ui.presentation || language !== ui.language || variant !== ui.variant) return;
    ui.previewUrl = result.url;
    iframe.hidden = ui.mainMode !== 'slides';
    iframe.src = result.url + '#/' + encodeURIComponent(ui.slide);
    setTimeout(() => {
      if (generation !== ui.previewGeneration || ui.previewReady || ui.mainMode !== 'slides') return;
      $('loading-preview').hidden = true;
      $('preview-error-message').textContent = 'Reveal.js did not initialize. Reload the preview to retry.';
      $('preview-error').hidden = false;
    }, 15000);
    $('open-preview').disabled = false;
    $('export-pdf').disabled = false;
    if (ui.mainMode !== 'slides') $('loading-preview').hidden = true;
  } catch (error) {
    if (generation !== ui.previewGeneration) return;
    iframe.hidden = true;
    $('preview-error-message').textContent = error.message;
    $('preview-error').hidden = ui.mainMode !== 'slides';
    $('loading-preview').hidden = true;
  }
}

function sourceRange(source, slideId) {
  const lines = source.split('\n');
  const heading = /^## [^\n]*?\{#([a-z][a-z0-9_-]*)\}[ \t]*$/;
  let start = -1;
  let end = lines.length;
  for (let i = 0; i < lines.length; i++) {
    const found = heading.exec(lines[i]);
    if (!found) continue;
    if (found[1] === slideId) start = i;
    else if (start !== -1) { end = i; break; }
  }
  return { start, end };
}

function paintSourceHighlight(scrollToSlide = false) {
  if (!ui.viewSource || !hasPresentation()) return;
  const source = $('source-editor').value;
  const baseline = ui.savedSourceKey === `${ui.presentation}:${ui.language}` && ui.savedSource !== null ? ui.savedSource : source;
  SourceDiff.render($('source-diff-editor'), baseline, source, sourceRange(source, ui.slide), scrollToSlide);
}

async function refreshSourceDiff() {
  if (!ui.presentation || !ui.state?.sources) return;
  const presentation = ui.presentation;
  const language = ui.language;
  const request = ++ui.sourceDiffRequest;
  const result = await api(`/api/source/saved?presentation=${encodeURIComponent(presentation)}&language=${encodeURIComponent(language)}`);
  if (request !== ui.sourceDiffRequest || presentation !== ui.presentation || language !== ui.language) return;
  ui.savedSourceKey = `${presentation}:${language}`;
  ui.savedSource = result.source;
  paintSourceHighlight();
}

function resetSourceHistory() {
  ui.sourceUndo = [];
  ui.sourceRedo = [];
  ui.sourceEditTime = 0;
  ui.sourceEditKind = '';
  ui.sourceInputBefore = null;
  ui.sourceComposing = false;
}

function rememberSourceEdit(previous, next, kind, caret = null) {
  if (previous === next) return;
  const now = performance.now();
  if (kind !== 'insertText' || ui.sourceEditKind !== kind || now - ui.sourceEditTime > 650 || !ui.sourceUndo.length) {
    ui.sourceUndo.push({source: previous, caret});
    if (ui.sourceUndo.length > 100) ui.sourceUndo.shift();
  }
  ui.sourceRedo = [];
  ui.sourceEditTime = now;
  ui.sourceEditKind = kind;
}

function moveSourceHistory(direction) {
  const from = direction < 0 ? ui.sourceUndo : ui.sourceRedo;
  const to = direction < 0 ? ui.sourceRedo : ui.sourceUndo;
  if (!from.length) return;
  const editor = $('source-diff-editor');
  to.push({source: $('source-editor').value, caret: SourceDiff.captureCaret(editor)});
  const item = from.pop();
  $('source-editor').value = item.source;
  ui.sourceEditKind = '';
  updateSourceDraft();
  if (item.caret) SourceDiff.restoreCaret(editor, item.source, item.caret);
}

function scheduleSourcePaint() {
  clearTimeout(ui.sourcePaintTimer);
  ui.sourcePaintTimer = setTimeout(() => paintSourceHighlight(), $('source-editor').value.length > 200000 ? 800 : 250);
}

function updateSourceDraft(repaint = true) {
  const original = ui.state?.sources?.[ui.language] || '';
  ui.sourceDraft = $('source-editor').value !== original;
  $('source-apply').disabled = !ui.sourceDraft || ui.busy;
  $('source-revert').disabled = !ui.sourceDraft;
  if (repaint) paintSourceHighlight();
  updateSaveIndicator();
}

function confirmDiscardSource() {
  if (!ui.sourceDraft) return true;
  if (!window.confirm('Discard unapplied source edits?')) return false;
  ui.sourceDraft = false;
  updateSaveIndicator();
  return true;
}

function updateSourceStage(scrollToSlide = false) {
  $('source-stage').hidden = !ui.viewSource || !hasPresentation();
  $('source-caption').textContent = ui.language.toUpperCase();
  $('view-source').textContent = 'Source';
  $('view-source').setAttribute('aria-pressed', String(ui.viewSource));
  if (ui.viewSource && hasPresentation()) {
    const content = ui.state.sources[ui.language];
    if (!ui.sourceDraft || $('source-editor').dataset.language !== ui.language || $('source-editor').dataset.presentation !== ui.presentation) {
      $('source-editor').value = content;
      $('source-editor').dataset.language = ui.language;
      $('source-editor').dataset.presentation = ui.presentation;
      ui.sourceDraft = false;
      resetSourceHistory();
      ui.savedSourceKey = '';
      refreshSourceDiff().catch((error) => toast(error.message));
    }
    updateSourceDraft();
    paintSourceHighlight(scrollToSlide);
    $('slide-iframe').hidden = true;
    $('empty-stage').hidden = true;
    $('preview-error').hidden = true;
    $('loading-preview').hidden = true;
  } else if (ui.previewUrl && ui.mainMode === 'slides') {
    $('slide-iframe').hidden = false;
  }
}

async function applySource() {
  if (!hasPresentation() || !ui.sourceDraft || ui.busy) return;
  const source = $('source-editor').value;
  try {
    await api('/api/source', 'POST', {presentation: ui.presentation, language: ui.language, source});
    ui.sourceDraft = false;
    resetSourceHistory();
    await loadState(true);
    updateSourceStage(true);
    toast('Source applied to working session');
  } catch (error) { toast(error.message); }
}


const scopeSettings = {
  slides: [['slide', 'Current slide'], ['presentation', 'Entire presentation']],
  source: [['slide', 'Current slide'], ['presentation', 'Entire presentation']],
  facts: [['fact_table', 'Current table'], ['facts', 'All facts']],
  assets: [['asset_folder', 'Folder + subfolders'], ['assets', 'All assets']],
  scripts: [['script', 'Current script'], ['scripts', 'All scripts']],
  recipes: [['recipe', 'Current recipe'], ['recipes', 'All recipes']]
};

function updateAIScope() {
  const mode = ui.mainMode;
  const selected = ui.scopeByMode[mode] || scopeSettings[mode][0][0];
  const options = $('scope-options');
  options.replaceChildren();
  for (const [value, text] of scopeSettings[mode]) {
    const label = document.createElement('label');
    label.className = 'scope-option';
    label.innerHTML = `<input type="radio" name="scope" value="${value}" ${value === selected ? 'checked' : ''}><span><strong>${text}</strong></span>`;
    options.append(label);
  }
  ui.currentScope = selected;
  $('scope-slide-name').textContent = mode === 'slides' || mode === 'source' ? (ui.slide ? `#${ui.slide}` : 'No slide selected') : mode === 'facts' ? (ui.factCategory || 'No table open') : mode === 'assets' ? (ui.assetFolder || 'Root') : mode === 'scripts' ? (scriptState.script?.name || 'No script selected') : (recipeState.recipe?.name || 'No recipe selected');
  updateActionState();
}

function updateRunningState() {
  $('ai-running').hidden = !ui.busy;
  $('stop-ai').disabled = !ui.aiJob;
  $('ai-running-label').textContent = ui.aiJob ? 'Applying change…' : 'Starting…';
  if (ui.state) {
    updateSaveIndicator();
    $('undo-button').disabled = !ui.state.canUndo || ui.busy;
    $('redo-button').disabled = !ui.state.canRedo || ui.busy;
  }
  updateChatControls();
}

function updateActionState() {
  const prompt = $('ai-prompt').value;
  $('prompt-count').textContent = `${prompt.length.toLocaleString()} characters`;
  updateChatControls();
  const scope = document.querySelector('input[name=scope]:checked')?.value || '';
  const targetOK = ['slide','presentation'].includes(scope) ? hasPresentation() : scope === 'fact_table' ? Boolean(ui.factCategory) : scope === 'script' ? Boolean(scriptState.id) : scope === 'recipe' ? Boolean(recipeState.id) : true;
  $('apply-ai').disabled = !targetOK || !ui.settings?.hasKey || !selectedModel('edit') || !prompt.trim() || ui.busy;
  $('ai-prompt').disabled = ui.busy;
  updateRunningState();
  updateSaveIndicator();
  updateRecipeActions();
}

function showAIResult(message, error = false) {
  const box = $('ai-result');
  box.hidden = !message;
  box.textContent = message;
  box.classList.toggle('error', error);
}

function openModal(title, markup, submitText, onSubmit) {
  $('modal-title').textContent = title;
  $('modal').classList.toggle('wide-modal', title === 'Variants');
  $('modal-body').innerHTML = markup;
  $('modal-submit').textContent = submitText;
  $('modal-submit').classList.toggle('primary', submitText !== 'Remove');
  $('modal-submit').classList.toggle('secondary', submitText === 'Remove');
  const form = $('modal-form');
  form.onsubmit = async (event) => {
    event.preventDefault();
    $('modal-submit').disabled = true;
    try {
      const result = await onSubmit(new FormData(form));
      if (result !== false) $('modal').close();
    } catch (error) {
      toast(error.message);
    } finally {
      $('modal-submit').disabled = false;
    }
  };
  $('modal').showModal();
  $('modal-body').querySelector('input:not([type=file]),textarea')?.focus();
}

function showAIHelp(kind) {
  const editing = kind === 'edit';
  const content = editing
    ? 'Describe a change to the selected slides or workspace resources, then choose Apply change. Review the result, use Undo if needed, and Save when satisfied.'
    : 'Ask questions about presentations and other workspace resources. AI Chat can inspect the workspace but cannot change it. Conversations can be saved, branched, and restored.';
  openModal(editing ? 'AI Edit' : 'AI Chat', `<p class="modal-caption">${content}</p>`, 'Close', async () => {});
  $('modal-cancel').hidden = true;
  $('modal').addEventListener('close', () => { $('modal-cancel').hidden = false; }, {once: true});
}

function field(label, name, value = '', type = 'text', extra = '') {
  return `<div><label for="field-${escapeHTML(name)}">${escapeHTML(label)}</label><input id="field-${escapeHTML(name)}" name="${escapeHTML(name)}" type="${type}" value="${escapeHTML(value)}" ${extra}></div>`;
}

function createPresentation() {
  const markup = field('Name', 'name', '', 'text', 'required maxlength="100" placeholder="Presentation name"') +
    '<div><label for="presentation-format">Slide format</label><select id="presentation-format" name="size"><option value="1280x720">16:9 · Widescreen</option><option value="960x720">4:3 · Standard</option></select></div>';
  openModal('New presentation', markup, 'Create', async (form) => {
    const [width, height] = form.get('size').split('x').map(Number);
    const result = await api('/api/presentations', 'POST', { name: form.get('name'), width, height });
    ui.presentation = result.id;
    ui.variant = '';
    ui.slide = '';
    await loadState(true);
    rememberChoices();
  });
}

function removePresentation() {
  const entry = ui.state.presentations.find((presentation) => presentation.id === ui.presentation);
  if (!entry) return;
  openModal('Remove presentation', `<p class="modal-caption">Remove <strong>${escapeHTML(entry.name)}</strong> and both language versions from the working session?</p><p class="modal-caption modal-danger">This change is not written to the workspace until Save.</p>`, 'Remove', async () => {
    await api('/api/presentations', 'DELETE', { id: entry.id });
    ui.presentation = ''; ui.variant = ''; ui.slide = '';
    await loadState(true);
    rememberChoices();
  });
}

function duplicatePresentation() {
  const current = ui.state?.presentations?.find((entry) => entry.id === ui.presentation);
  if (!current) return;
  const sourceId = current.id;
  openModal('Duplicate presentation', field('New name', 'name', `${current.name} (copy)`.slice(0, 100), 'text', 'required maxlength="100"'), 'Duplicate', async (form) => {
    const result = await api('/api/presentations/duplicate', 'POST', {presentation: sourceId, name: form.get('name')});
    ui.presentation = result.id;
    ui.variant = '';
    ui.slide = '';
    await loadState(true);
    rememberChoices();
  });
}

function openPresentationSettings() {
  if (!hasPresentation()) return;
  const pid = ui.presentation;
  const presentation = ui.state.presentations.find((item) => item.id === pid);
  const count = Object.keys(ui.state.variants?.variants || {}).length;
  const variant = currentVariant();
  const markup = field('Presentation name', 'name', presentation.name, 'text', 'required maxlength="100"') +
    field('Description', 'description', presentation.description || '', 'text', 'maxlength="2000"') +
    `<div><label>Identifier</label><p class="modal-caption">${escapeHTML(pid)}</p></div>` +
    `<div class="presentation-settings-section"><label>Variants (${count})</label><div class="modal-sub-actions"><span class="modal-caption">${escapeHTML(variant?.name || '')} · ${variant?.width || 0} × ${variant?.height || 0}</span><button type="button" class="neutral" id="presentation-variants">Manage variants</button></div></div>` +
    `<div class="presentation-settings-section"><button type="button" class="text-button" id="presentation-duplicate">Duplicate presentation…</button></div>` +
    `<div class="presentation-settings-section"><button type="button" class="text-button danger-text" id="presentation-remove">Delete presentation…</button></div>`;
  openModal('Presentation settings', markup, 'Apply settings', async (form) => {
    await api('/api/presentations/settings', 'POST', {presentation: pid, name: form.get('name'), description: form.get('description')});
    await loadState();
  });
  $('presentation-variants').onclick = () => { $('modal').close(); openVariantManager(); };
  $('presentation-duplicate').onclick = () => { $('modal').close(); duplicatePresentation(); };
  $('presentation-remove').onclick = () => { $('modal').close(); removePresentation(); };
}


function variantSlidesMarkup(visibleIds) {
  const visible = new Set(visibleIds);
  return (ui.state.allSlides || []).map((id, index) => `<label class="variant-slide"><input type="checkbox" name="visible" value="${escapeHTML(id)}" ${visible.has(id) ? 'checked' : ''}><span title="${escapeHTML(ui.state.slideLabels?.[id] || id)}">${index + 1}. ${escapeHTML(ui.state.slideLabels?.[id] || id)}</span></label>`).join('');
}

function variantFieldsMarkup(variant) {
  const visible = (ui.state.allSlides || []).filter((id) => !variant.hidden_slides.includes(id));
  return field('Name', 'name', variant.name, 'text', 'required maxlength="80"') +
    field('Description', 'description', variant.description || '', 'text', 'maxlength="2000"') +
    `<div><label>Canvas size (pixels)</label><div class="format-controls"><input aria-label="Width" name="width" type="number" min="320" max="8192" required value="${variant.width}"><span>×</span><input aria-label="Height" name="height" type="number" min="320" max="8192" required value="${variant.height}"></div></div>` +
    `<div><label>Visible slides</label><div class="variant-edit-slides">${variantSlidesMarkup(visible)}</div></div>`;
}

function variantPayload(form) {
  const visible = new Set(form.getAll('visible').map(String));
  return { name: String(form.get('name')).trim(), description:String(form.get('description') || ''), width: Number(form.get('width')), height: Number(form.get('height')), hidden_slides: (ui.state.allSlides || []).filter((id) => !visible.has(id)) };
}

function variantId(name) {
  const base = String(name).toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 55) || 'variant';
  let candidate = /^[a-z]/.test(base) ? base : `variant-${base}`;
  let count = 2;
  while (ui.state.variants.variants[candidate]) candidate = `${base}-${count++}`;
  return candidate;
}

function openVariantManager() {
  if (!hasPresentation()) return;
  const pid = ui.presentation;
  let selected = ui.variant;
  let newVariant = false;
  let templateId = selected;
  let template = null;
  const markup = '<div class="variant-manager"><nav class="variant-list" id="variant-list" aria-label="Variants"></nav><div class="variant-fields" id="variant-fields"></div></div>';
  openModal('Variants', markup, 'Save variant', async (form) => {
    const variant = variantPayload(form);
    const id = newVariant ? variantId(variant.name) : selected;
    await api('/api/variants', 'POST', {presentation:pid, id, variant, duplicateFrom:newVariant ? templateId : null});
    newVariant = false;
    selected = id;
    template = null;
    ui.variant = id;
    await loadState(true);
    rememberChoices();
    render();
    return false;
  });

  function render() {
    const data = ui.state?.variants;
    if (!data) return;
    const list = $('variant-list');
    const fields = $('variant-fields');
    list.replaceChildren();
    for (const [id, entry] of Object.entries(data.variants)) {
      const button = document.createElement('button');
      button.type = 'button';
      button.classList.toggle('active', !newVariant && selected === id);
      button.textContent = entry.name;
      if (data.default === id) {
        const mark = document.createElement('span'); mark.textContent = '★'; mark.title = 'Default variant'; button.append(mark);
      }
      button.onclick = () => { selected = id; newVariant = false; render(); };
      list.append(button);
    }
    const add = document.createElement('button'); add.type = 'button'; add.textContent = '+ New variant';
    add.classList.toggle('active', newVariant);
    add.onclick = () => {
      templateId = selected;
      const original = data.variants[selected] || data.variants[data.default];
      template = {...original, name:`${original.name} (copy)`, description:original.description || "", hidden_slides:[...original.hidden_slides]};
      newVariant = true;
      render();
    };
    list.append(add);
    const entry = newVariant ? template : data.variants[selected];
    if (!entry) return;
    fields.innerHTML = variantFieldsMarkup(entry) + (newVariant ? '' :
      '<div class="variant-manager-actions"><button type="button" id="variant-default" class="button secondary">Set as default</button><button type="button" id="variant-delete" class="button secondary">Delete variant</button></div>');
    $('modal-submit').textContent = newVariant ? 'Create variant' : 'Save variant';
    if (!newVariant) {
      $('variant-default').disabled = data.default === selected;
      $('variant-default').onclick = async () => {
        try {
          await api('/api/variants/default', 'POST', {presentation:pid, id:selected});
          await loadState();
          render();
        } catch (error) { toast(error.message); }
      };
      $('variant-delete').disabled = Object.keys(data.variants).length < 2;
      $('variant-delete').onclick = async () => {
        if (!window.confirm(`Delete variant “${entry.name}”?`)) return;
        try {
          await api('/api/variants', 'DELETE', {presentation:pid, id:selected});
          selected = Object.keys(ui.state.variants.variants).find((id) => id !== selected) || '';
          ui.variant = selected;
          await loadState(true);
          rememberChoices();
          render();
        } catch (error) { toast(error.message); }
      };
    }
  }
  render();
}

function categoryPicker(kind, value = '', readonly = false) {
  if (readonly) return field(kind === 'facts' ? 'Table' : 'Folder', 'category', value, 'text', 'readonly');
  const categories = kind === 'facts' ? Object.keys(ui.state.facts.categories || {}) : knownAssetFolders();
  categories.sort((a, b) => a.localeCompare(b));
  const preferred = kind === 'assets' ? value : (value || ui.lastCategory[kind] || categories[0] || '');
  if (preferred && !categories.includes(preferred)) categories.unshift(preferred);
  const choice = preferred || (kind === 'facts' ? '__new__' : '');
  const options = categories.map((item) => `<option value="${escapeHTML(item)}" ${item === choice ? 'selected' : ''}>${escapeHTML(item)}</option>`).join('');
  const root = kind === 'assets' ? `<option value="" ${choice === '' ? 'selected' : ''}>Assets (root)</option>` : '';
  return `<div><label for="category-choice">${kind === 'facts' ? 'Table' : 'Folder'}</label><select name="categoryChoice" id="category-choice">${root}${options}<option value="__new__" ${choice === '__new__' ? 'selected' : ''}>+ New…</option></select></div>` +
    `<div id="new-category-box" ${choice === '__new__' ? '' : 'hidden'}>${field(kind === 'facts' ? 'New table' : 'New folder', 'newCategory', '', 'text', `maxlength="${kind === 'assets' ? 220 : 60}"`)}</div>`;
}

function bindCategoryPicker() {
  const choice = $('category-choice');
  if (!choice) return;
  const sync = () => { $('new-category-box').hidden = choice.value !== '__new__'; $('field-newCategory').required = choice.value === '__new__'; };
  choice.onchange = sync;
  sync();
}

function chosenCategory(form) {
  if (form.get('categoryChoice') === '') return '';
  const category = form.get('categoryChoice') === '__new__' ? form.get('newCategory') : (form.get('categoryChoice') || form.get('category'));
  if (!String(category || '').trim() && form.get('categoryChoice') !== '') throw new Error('Choose a table or folder');
  return String(category).trim();
}

function rememberCategory(kind, category) {
  ui.lastCategory[kind] = category;
  api('/api/session', 'POST', {[kind === 'facts' ? 'factCategory' : 'assetCategory']: category}).catch((error) => toast(error.message));
}

function openFactEditor(category = '', key = '') {
  const old = ui.state.facts.categories?.[category]?.[key];
  const markup = categoryPicker('facts', category, Boolean(old)) +
    field('Identifier', 'key', key, 'text', `${old ? 'readonly' : ''} required pattern="[a-z][a-z0-9_-]*" placeholder="student_count"`) +
    field('Value', 'value', old?.value ?? '', 'text', 'required') +
    field('Last verified', 'updated', old ? (old.updated || '') : dateLocal(), 'date') +
    '<button type="button" class="text-button clear-date" id="clear-fact-date">Clear date</button>' +
    field('Description', 'description', old?.description || '', 'text');
  openModal(old ? 'Edit fact' : 'Add fact', markup, 'Save fact', async (form) => {
    const values = Object.fromEntries(form.entries());
    values.category = chosenCategory(form);
    await api('/api/facts', 'POST', values);
    rememberCategory('facts', values.category);
    await loadState(true);
  });
  bindCategoryPicker();
  $('clear-fact-date').onclick = () => { $('field-updated').value = ''; };
}

function sortedEntries(entries, kind) {
  const sort = $(`${kind}-sort`).value;
  const dateField = kind === 'facts' ? 'updated' : 'added';
  return entries.sort(([nameA, a], [nameB, b]) => {
    const byName = nameA.localeCompare(nameB, undefined, {sensitivity: 'base'});
    if (sort === 'name') return byName;
    if (sort === 'name-desc') return -byName;
    if (sort === 'size' || sort === 'size-asc') return ((Number(b.bytes || 0) - Number(a.bytes || 0)) * (sort === 'size' ? 1 : -1)) || byName;
    const dateA = a[dateField] || '', dateB = b[dateField] || '';
    if (!dateA) return dateB ? 1 : byName;
    if (!dateB) return -1;
    const compare = sort === 'date' ? dateB.localeCompare(dateA) : dateA.localeCompare(dateB);
    return compare || byName;
  });
}

function isUsed(kind, key) {
  return ui.state.usage?.[kind]?.[key] || [];
}

function matchesUsage(kind, key) {
  const filter = $(`${kind}-usage`).value;
  const used = isUsed(kind, key);
  return filter === 'all' || (filter === 'here' && used.includes(ui.presentation)) || (filter === 'unused' && used.length === 0);
}

function makeCategoryHeader(kind, category, number) {
  const header = document.createElement('button');
  header.type = 'button';
  header.className = 'category-heading category-toggle';
  header.setAttribute('aria-expanded', String(!ui.collapsed[kind].has(category)));
  const arrow = document.createElement('span'); arrow.textContent = ui.collapsed[kind].has(category) ? '▸' : '▾';
  const label = document.createElement('span'); label.textContent = category;
  const count = document.createElement('span'); count.textContent = String(number); count.className = 'category-count';
  header.append(arrow, label, count);
  header.onclick = () => { if (ui.collapsed[kind].has(category)) ui.collapsed[kind].delete(category); else ui.collapsed[kind].add(category); renderLibrary(kind); };
  return header;
}

function updateBulkControls(kind) {
  const selected = ui.selected[kind];
  const visible = ui.visible[kind];
  const check = $(`${kind}-select-visible`);
  check.checked = visible.length > 0 && visible.every((id) => selected.has(id));
  check.indeterminate = !check.checked && visible.some((id) => selected.has(id));
  const action = $(`${kind}-bulk-remove`);
  action.disabled = !selected.size;
  action.textContent = selected.size ? `Delete selected (${selected.size})` : 'Delete selected';
  $(`${kind}-collapse`).textContent = ui.collapsed[kind].size ? 'Expand all' : 'Collapse all';
}

function makeSelection(kind, id) {
  const check = document.createElement('input');
  check.type = 'checkbox'; check.className = 'entity-check'; check.setAttribute('aria-label', `Select ${id}`);
  check.checked = ui.selected[kind].has(id);
  check.onchange = () => { if (check.checked) ui.selected[kind].add(id); else ui.selected[kind].delete(id); updateBulkControls(kind); };
  return check;
}

function fileAlias(name) {
  let basename = name.replace(/\.[^.]+$/, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  if (!/^[a-z]/.test(basename)) basename = 'image-' + basename;
  return basename.slice(0, 63);
}

function openAssetEditor(alias = '', replaceImage = false) {
  const old = ui.state.assets.assets?.[alias];
  const preferred = old ? assetFolderName(alias) : ui.assetFolder;
  const imageField = `<div><label for="field-file">Image</label><input class="file-input" id="field-file" name="file" type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml" ${old && !replaceImage ? '' : 'required'} ${old ? '' : 'multiple'}></div>`;
  const markup = categoryPicker('assets', preferred) + imageField +
    field('Name', 'basename', alias ? assetBaseName(alias) : '', 'text', 'required pattern="[a-z][a-z0-9_-]*" maxlength="64" placeholder="main_auditorium"') +
    `<div><label for="field-description">Description</label><textarea id="field-description" name="description">${escapeHTML(old?.description || '')}</textarea></div>` +
    (old ? `<p class="modal-caption">${ui.state.assetDetails?.[alias]?.width ?? '—'} × ${ui.state.assetDetails?.[alias]?.height ?? '—'} · ${Number(ui.state.assetDetails?.[alias]?.bytes || 0).toLocaleString()} bytes</p>` : '') +
    field('Date added', 'added', old ? (old.added || '') : dateLocal(), 'date') +
    '<button type="button" class="text-button clear-date" id="clear-asset-date">Clear date</button>';
  openModal(old ? (replaceImage ? 'Replace image' : 'Asset details') : 'Add images', markup, old ? 'Apply' : 'Add', async (form) => {
    const category = chosenCategory(form);
    const fileInput = $('field-file');
    const files = [...fileInput.files];
    const description = String(form.get('description'));
    const added = String(form.get('added') || '');
    if (!old && files.length > 1) {
      await uploadDroppedImages(files, category, description, added);
      rememberCategory('assets', category);
      return;
    }
    const destination = assetPath(category, String(form.get('basename')).trim());
    const file = files[0];
    const request = {description, added};
    if (file?.size) {
      if (file.size > 12 * 1024 * 1024) throw new Error('Image must be under 12 MB');
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      request.filename = file.name;
      request.content = btoa(binary);
    }
    if (old) await api('/api/assets/edit', 'POST', {alias, destination, ...request});
    else {
      if (!file?.size) throw new Error('Choose an image');
      await api('/api/assets', 'POST', {alias:destination, category, ...request});
    }
    rememberCategory('assets', category);
    await loadState(true);
  });
  bindCategoryPicker();
  $('clear-asset-date').onclick = () => { $('field-added').value = ''; };
  $('field-file').onchange = () => {
    const files = [...$('field-file').files];
    if (old || !files.length) return;
    const name = $('field-basename');
    if (!name.dataset.userEdited) name.value = fileAlias(files[0].name);
    const multiple = files.length > 1;
    name.closest('div').hidden = multiple;
    name.required = !multiple;
    $('field-description').placeholder = multiple ? 'Description shared by selected images' : 'Purpose of this image';
  };
  $('field-basename').oninput = () => { $('field-basename').dataset.userEdited = 'true'; };
}

async function removeFact(category, key) {
  if (!window.confirm(`Remove fact ${category}.${key}? References remain in the slide sources.`)) return;
  try { await api('/api/facts', 'DELETE', {category, key}); ui.selected.facts.delete(`${category}.${key}`); await loadState(true); }
  catch (error) { toast(error.message); }
}

async function removeAsset(alias) {
  if (!window.confirm(`Remove image alias ${alias}? References remain in the slide sources.`)) return;
  try { await api('/api/assets', 'DELETE', {alias}); ui.selected.assets.delete(alias); await loadState(true); }
  catch (error) { toast(error.message); }
}

function renderLibrary(kind) {
  if (kind === 'facts') renderFacts(); else renderAssets();
}

async function removeSelected(kind) {
  const names = [...ui.selected[kind]];
  if (!names.length) return;
  if (!window.confirm(`Delete ${names.length} selected ${kind === 'facts' ? 'facts' : 'assets'}? References in presentations will remain.\n\n${names.slice(0, 12).join(', ')}${names.length > 12 ? ', …' : ''}`)) return;
  try {
    if (kind === 'facts') {
      const entries = names.map((name) => {
        for (const category of Object.keys(ui.state.facts.categories)) {
          if (name.startsWith(category + '.') && ui.state.facts.categories[category][name.slice(category.length + 1)]) return {category, key: name.slice(category.length + 1)};
        }
        throw new Error('Selected fact no longer exists');
      });
      await api('/api/facts/bulk', 'DELETE', {entries});
    } else await api('/api/assets/bulk', 'DELETE', {aliases: names});
    ui.selected[kind].clear();
    await loadState(true);
  } catch (error) { toast(error.message); }
}


async function renderChanges() {
  const previous = $('diff-file').value;
  ui.diffs = await api('/api/diff');
  const select = $('diff-file');
  select.replaceChildren();
  if (!ui.diffs.length) select.add(new Option('No changes', ''));
  for (const diff of ui.diffs) select.add(new Option(diff.path, diff.path));
  select.value = ui.diffs.some((entry) => entry.path === previous) ? previous : ui.diffs[0]?.path || '';
  paintDiff();
}

function paintDiff() {
  const root = $('diff-content'); root.replaceChildren();
  const current = ui.diffs.find((item) => item.path === $('diff-file').value);
  if (!current) { root.innerHTML = '<div class="empty-list">No unsaved changes</div>'; return; }
  for (const line of current.diff.split('\n')) {
    const row = document.createElement('div'); row.className = 'diff-line';
    if (line.startsWith('+')) row.classList.add('add');
    if (line.startsWith('-')) row.classList.add('remove');
    if (line.startsWith('@@') || line.startsWith('+++') || line.startsWith('---')) row.className = 'diff-line header';
    row.textContent = line || ' ';
    root.append(row);
  }
}

function openSettings() {
  const status = ui.settings || {};
  const markup = `<p class="modal-caption">API key: <strong>${status.hasKey ? 'Configured' : 'Not configured'}</strong></p>` +
    field('OpenRouter API key', 'key', '', 'password', 'autocomplete="off" placeholder="Leave empty to keep current key"') +
    `<div><label><input type="checkbox" name="removeKey" value="yes"> Remove stored API key</label></div>`;
  openModal('OpenRouter API key', markup, 'Save', async (form) => {
    const key = String(form.get('key') || '').trim();
    ui.settings = await api('/api/settings', 'POST', {key:key || null,removeKey:form.has('removeKey')});
    updateActionState();
    if (ui.settings.hasKey) refreshModelCatalog().catch((error) => toast(error.message));
    else { modelState.catalog = []; renderModelOptions(); }
  });
}

async function applyAI() {
  if (ui.busy || !confirmDiscardSource() || !confirmDiscardFactDraft() || !confirmDiscardScript() || !confirmDiscardRecipe()) return;
  const scope = document.querySelector('input[name="scope"]:checked').value;
  const instruction = $('ai-prompt').value.trim();
  ui.busy = true;
  showAIResult('');
  updateActionState();
  try {
    const started = await api('/api/ai', 'POST', { presentation: ui.presentation, variant: ui.variant, slide: ui.slide, scope, target: scope === 'fact_table' ? ui.factCategory : scope === 'asset_folder' ? ui.assetFolder : scope === 'script' ? scriptState.id : scope === 'recipe' ? recipeState.id : '', selection:{presentation:ui.presentation, variant:ui.variant, language:ui.language, slide:ui.slide}, instruction, chatId:$('include-chat-context').checked && !$('include-chat-context').disabled ? chatState.id : null, model:selectedModel('edit'), effort:selectedEffort('edit') });
    ui.aiJob = started.job;
    updateRunningState();
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, 450));
      const job = await api(`/api/ai/status?job=${encodeURIComponent(ui.aiJob)}`);
      if (job.status === 'running' || job.status === 'stopping') {
        $('ai-running-label').textContent = job.status === 'stopping' ? 'Stopping…' : 'Applying change…';
        continue;
      }
      if (job.status === 'complete') {
        await loadState(true);
        showAIResult(`Changes applied.${job.result?.note ? '\n' + job.result.note : ''}${job.result?.images ? '\n' + job.result.images + ' rendered slide images supplied.' : ''}`);
      } else if (job.status === 'cancelled') {
        showAIResult('Edit cancelled. No changes applied.');
      } else {
        showAIResult(job.error || 'The edit failed.', true);
      }
      break;
    }
  } catch (error) { showAIResult(error.message, true); }
  finally { ui.busy = false; ui.aiJob = ''; updateActionState(); }
}

async function stopAI() {
  if (!ui.aiJob) return;
  $('stop-ai').disabled = true;
  $('ai-running-label').textContent = 'Stopping…';
  try { await api('/api/ai/cancel', 'POST', { job: ui.aiJob }); }
  catch (error) { toast(error.message); $('stop-ai').disabled = false; }
}

async function moveHistory(direction) {
  if (!confirmDiscardSource() || !confirmDiscardFactDraft() || !confirmDiscardScript() || !confirmDiscardRecipe()) return;
  try { await api('/api/history', 'POST', { direction }); await loadState(true); showAIResult(''); }
  catch (error) { toast(error.message); }
}

function selectTab(name) {
  ui.tab = name;
  for (const button of document.querySelectorAll('.panel-tab')) button.classList.toggle('active', button.dataset.tab === name);
  $('tab-ai').hidden = name !== 'ai';
  $('tab-changes').hidden = name !== 'changes';
  $('tab-chat').hidden = name !== 'chat';
  if (name === 'chat') { renderChat(); updateChatControls(); }
  if (name === 'changes') renderChanges().catch((error) => toast(error.message));
}

async function setMainMode(mode) {
  if (!['slides', 'source', 'facts', 'assets', 'scripts', 'recipes'].includes(mode)) return;
  if (ui.mainMode === 'source' && mode !== 'source' && !confirmDiscardSource()) return;
  if (ui.mainMode === 'facts' && mode !== 'facts' && !confirmDiscardFactDraft()) return;
  if (ui.mainMode === 'scripts' && mode !== 'scripts' && !confirmDiscardScript()) return;
  if (ui.mainMode === 'recipes' && mode !== 'recipes' && !confirmDiscardRecipe()) return;
  ui.promptByMode[ui.mainMode] = $('ai-prompt').value;
  ui.mainMode = mode;
  ui.viewSource = mode === 'source';
  const frame = $('preview-frame');
  frame.dataset.mode = mode;
  for (const [id, name] of [['mode-slides','slides'], ['view-source','source'], ['mode-facts','facts'], ['mode-assets','assets'], ['mode-scripts','scripts'], ['mode-recipes','recipes']]) {
    $(id).classList.toggle('active', name === mode);
    $(id).setAttribute('aria-pressed', String(name === mode));
  }
  $('tab-facts').hidden = mode !== 'facts';
  $('tab-assets').hidden = mode !== 'assets';
  $('tab-scripts').hidden = mode !== 'scripts';
  $('tab-recipes').hidden = mode !== 'recipes';
  $('hidden-slide-overlay').hidden = true;
  $('slide-iframe').hidden = mode !== 'slides' || !ui.previewUrl;
  $('empty-stage').hidden = mode !== 'slides' || hasPresentation();
  $('preview-error').hidden = true;
  $('loading-preview').hidden = true;
  updateSourceStage(true);
  if (mode === 'facts') renderFacts();
  else if (mode === 'assets') renderAssets();
  else if (mode === 'scripts') await renderScripts();
  else if (mode === 'recipes') await renderRecipes();
  else if (mode === 'slides') {
    if (!ui.previewUrl) await renderPreview();
    else { $('slide-iframe').hidden = false; layoutSlidePreview(); }
    updateSlideUI();
  }
  $('ai-prompt').value = ui.promptByMode[mode] || '';
  updateSlideUI();
  updateAIScope();
}

function bindEvents() {
  $('new-presentation').onclick = createPresentation;
  $('empty-create').onclick = createPresentation;
  $('presentation-settings').onclick = openPresentationSettings;
  $('slide-resources').onclick = openSlideResources;
  $('toggle-hidden-navigation').onclick = toggleHiddenNavigation;
  $('slide-description-button').onclick = () => {
    if (!ui.presentation || !ui.slide) return;
    openModal('Slide description', field('Description', 'description', ui.state.slideDescriptions?.[ui.slide] || '', 'text', 'maxlength="2000"'), 'Save', async (form) => {
      await api('/api/slides/description', 'POST', {presentation:ui.presentation, slide:ui.slide, description:form.get('description')});
      await loadState();
    });
  };

  $('variant-select').onchange = async (event) => { if (!confirmDiscardSource() || !confirmDiscardFactDraft()) { event.target.value = ui.variant; return; } ui.variant = event.target.value; ui.slide = ''; await loadState(true); rememberChoices(); };
  $('settings-button').onclick = openSettings;
  $('ai-help').onclick = () => showAIHelp('edit');
  $('chat-help').onclick = () => showAIHelp('chat');
  $('theme-toggle').onclick = async () => {
    const previous = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
    const next = previous === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try { await api('/api/session', 'POST', {theme:next}); } catch (error) { setTheme(previous); toast(error.message); }
  };
  $('modal-close').onclick = () => $('modal').close();
  $('modal-cancel').onclick = () => $('modal').close();
  $('presentation-select').onchange = async (event) => { if (!confirmDiscardSource() || !confirmDiscardFactDraft()) { event.target.value = ui.presentation; return; } ui.presentation = event.target.value; ui.variant = ''; ui.slide = ''; await loadState(true); rememberChoices(); };
  for (const button of document.querySelectorAll('[data-lang]')) button.onclick = async () => {
    if (!confirmDiscardSource() || !confirmDiscardFactDraft() || !confirmDiscardScript() || !confirmDiscardRecipe()) return;
    ui.language = button.dataset.lang;
    for (const item of document.querySelectorAll('[data-lang]')) item.classList.toggle('active', item === button);
    updateSourceStage(true);
    if (!ui.viewSource) await renderPreview();
    rememberChoices();
  };
  $('previous-slide').onclick = () => { if (confirmDiscardSource()) { goSlide(-1); updateSourceStage(true); } };
  $('next-slide').onclick = () => { if (confirmDiscardSource()) { goSlide(1); updateSourceStage(true); } };
  $('refresh-preview').onclick = () => renderPreview();
  $('toggle-slide-visibility').onclick = toggleSlideVisibility;
  $('view-source').onclick = () => setMainMode('source');
  $('mode-slides').onclick = () => setMainMode('slides');
  $('mode-facts').onclick = () => setMainMode('facts');
  $('mode-assets').onclick = () => setMainMode('assets');
  $('mode-scripts').onclick = () => setMainMode('scripts');
  $('mode-recipes').onclick = () => setMainMode('recipes');
  $('stop-ai').onclick = stopAI;
  $('open-preview').onclick = () => { if (ui.previewUrl) window.open(ui.previewUrl + '#/' + encodeURIComponent(ui.slide), '_blank', 'noopener,noreferrer'); };
  $('export-pdf').onclick = async () => {
    if (!ui.previewUrl) return;
    const tab = window.open('about:blank', '_blank');
    try {
      const query = `presentation=${encodeURIComponent(ui.presentation)}&language=${encodeURIComponent(ui.language)}&variant=${encodeURIComponent(ui.variant)}`;
      const result = await api(`/api/pdf?${query}`);
      if (tab) tab.location.href = result.url;
      else window.open(result.url, '_blank', 'noopener,noreferrer');
    } catch (error) {
      toast(error.message);
      const query = `presentation=${encodeURIComponent(ui.presentation)}&language=${encodeURIComponent(ui.language)}&variant=${encodeURIComponent(ui.variant)}`;
      const result = await api(`/api/preview?${query}`);
      if (tab) tab.location.href = result.url + '?print-pdf&autoprint';
    }
  };
  $('save-button').onclick = async () => {
    if (ui.factDraft) { try { await applyFactTableEdits(); } catch (error) { toast(error.message); return; } }
    if (ui.sourceDraft || scriptState.draft || recipeState.draft) { toast('Apply or discard source edits before saving'); return; }
    try { await api('/api/save', 'POST', {}); await loadState(); toast('Workspace saved'); }
    catch (error) { toast(error.message); }
  };
  $('undo-button').onclick = () => moveHistory(-1);
  $('redo-button').onclick = () => moveHistory(1);
  $('ai-prompt').oninput = updateActionState;
  $('scope-options').onchange = () => { ui.scopeByMode[ui.mainMode] = document.querySelector('input[name=scope]:checked').value; rememberChoices(); updateActionState(); };
  $('apply-ai').onclick = applyAI;
  for (const tab of document.querySelectorAll('[data-tab]')) tab.onclick = () => selectTab(tab.dataset.tab);
  $('diff-file').onchange = paintDiff;
  $('copy-source').onclick = async () => { await navigator.clipboard.writeText($('source-editor').value); toast('Source copied'); };
  function insertSourceText(text, kind) {
    const editor = $('source-diff-editor');
    const previous = $('source-editor').value;
    const caret = SourceDiff.captureCaret(editor);
    const replacement = SourceDiff.replaceSelection(editor, previous, text);
    if (!replacement) return;
    rememberSourceEdit(previous, replacement.source, kind, caret);
    $('source-editor').value = replacement.source;
    updateSourceDraft(false);
    paintSourceHighlight();
    SourceDiff.restoreCaret(editor, replacement.source, {anchor: replacement.caret, focus: replacement.caret});
  }
  $('source-diff-editor').onkeydown = (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    if (event.key.toLowerCase() === 'z') {
      event.preventDefault();
      moveSourceHistory(event.shiftKey ? 1 : -1);
    } else if (event.key.toLowerCase() === 'y') {
      event.preventDefault();
      moveSourceHistory(1);
    }
  };
  $('source-diff-editor').addEventListener('beforeinput', (event) => {
    if (event.inputType === 'insertParagraph' || event.inputType === 'insertLineBreak') {
      event.preventDefault();
      insertSourceText('\n', 'insertLineBreak');
      return;
    }
    ui.sourceInputBefore = {source: $('source-editor').value, caret: SourceDiff.captureCaret($('source-diff-editor')), kind: event.inputType};
  });
  $('source-diff-editor').onpaste = (event) => {
    event.preventDefault();
    ui.sourceInputBefore = null;
    insertSourceText(event.clipboardData.getData('text/plain').replace(/\r\n?/g, '\n'), 'insertFromPaste');
  };
  $('source-diff-editor').oninput = () => {
    const previous = ui.sourceInputBefore;
    const source = SourceDiff.editorValue($('source-diff-editor'));
    rememberSourceEdit(previous?.source ?? $('source-editor').value, source, previous?.kind || 'edit', previous?.caret ?? null);
    ui.sourceInputBefore = null;
    $('source-editor').value = source;
    updateSourceDraft(false);
    if (!ui.sourceComposing) scheduleSourcePaint();
  };
  $('source-diff-editor').oncompositionstart = () => { ui.sourceComposing = true; clearTimeout(ui.sourcePaintTimer); };
  $('source-diff-editor').oncompositionend = () => { ui.sourceComposing = false; scheduleSourcePaint(); };
  $('source-diff-editor').onblur = () => paintSourceHighlight();
  $('source-apply').onclick = applySource;
  $('source-revert').onclick = () => { $('source-editor').value = ui.state.sources[ui.language]; resetSourceHistory(); updateSourceDraft(); paintSourceHighlight(true); };
  window.addEventListener('message', handlePreviewMessage);
  const observer = new ResizeObserver(() => layoutSlidePreview());
  observer.observe($('preview-frame'));
  $('slide-iframe').addEventListener('load', () => layoutSlidePreview());
  window.addEventListener('beforeunload', (event) => { if (ui.state?.dirty || ui.busy || ui.sourceDraft || ui.factDraft || scriptState.draft || recipeState.draft) { event.preventDefault(); event.returnValue = ''; } });
}

async function main() {
  bindEvents();
  setInterval(checkServerHealth, 3000);
  window.addEventListener('focus', checkServerHealth);
  initExplorer();
  initChat();
  initScripts();
  initRecipes();
  await setMainMode('slides');
  try {
    ui.settings = await api('/api/settings');
    const session = await api('/api/session');
    setTheme(session.theme);
    await initModelChoices(session);
    ui.lastCategory.facts = session.factCategory || '';
    ui.lastCategory.assets = session.assetCategory || '';
    ui.presentation = session.presentation || '';
    ui.variant = session.variant || '';
    ui.slide = session.slide || '';
    ui.showHiddenInNavigation = session.showHiddenInNavigation !== 'false';
    ui.language = session.language === 'en' ? 'en' : 'pt-BR';
    for (const button of document.querySelectorAll('[data-lang]')) button.classList.toggle('active', button.dataset.lang === ui.language);
    ui.scopeByMode.slides = session.scope === 'presentation' ? 'presentation' : 'slide';
    updateAIScope();
    await loadState(true);
    await refreshChatList(session.chatId || '');
  } catch (error) { toast(error.message); }
}
main();
