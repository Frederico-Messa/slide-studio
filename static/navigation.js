'use strict';

function navigableSlides() {
  const slides = ui.state?.slides || [];
  if (ui.showHiddenInNavigation) return slides;
  const hidden = new Set(currentVariant()?.hidden_slides || []);
  return slides.filter((id) => !hidden.has(id));
}

function resolveNavigableSlide(allSlides, navigable, requested, previous) {
  if (navigable.includes(requested)) return requested;
  const position = allSlides.indexOf(requested);
  if (position === -1) return navigable[0] || '';
  const previousPosition = allSlides.indexOf(previous);
  if (previousPosition > position) {
    return navigable.findLast((slide) => allSlides.indexOf(slide) < position) || navigable.find((slide) => allSlides.indexOf(slide) > position) || '';
  }
  return navigable.find((slide) => allSlides.indexOf(slide) > position) || navigable.findLast((slide) => allSlides.indexOf(slide) < position) || '';
}

function chooseSlide(id, persist = false) {
  const slides = ui.state?.slides || [];
  ui.slide = resolveNavigableSlide(slides, navigableSlides(), id, ui.slide);
  ui.selectedIndex = Math.max(slides.indexOf(ui.slide), 0);
  updateSlideUI();
  if (persist) rememberChoices();
}

function updateSlideUI() {
  const slides = navigableSlides();
  const index = slides.indexOf(ui.slide);
  $('slide-counter').textContent = `${index >= 0 ? index + 1 : 0} / ${slides.length}`;
  $('previous-slide').disabled = !hasPresentation() || index <= 0;
  $('next-slide').disabled = !hasPresentation() || index < 0 || index >= slides.length - 1;
  $('slide-resources').disabled = !hasPresentation() || !ui.slide;
  const navigationButton = $('toggle-hidden-navigation');
  navigationButton.disabled = !hasPresentation();
  navigationButton.classList.toggle('is-hidden', !ui.showHiddenInNavigation);
  $('hidden-navigation-count').textContent = String(currentVariant()?.hidden_slides?.length || 0);
  navigationButton.setAttribute('aria-pressed', String(!ui.showHiddenInNavigation));
  navigationButton.title = ui.showHiddenInNavigation ? 'Hide hidden slides from navigation' : 'Show hidden slides in navigation';
  navigationButton.setAttribute('aria-label', navigationButton.title);
  $('current-slide-name').textContent = ui.slide ? `#${ui.slide}` : 'No slide';
  if (ui.mainMode === 'slides' || ui.mainMode === 'source') $('scope-slide-name').textContent = ui.slide ? `#${ui.slide}` : 'No slide selected';
  const isHidden = Boolean(ui.slide && currentVariant()?.hidden_slides?.includes(ui.slide));
  $('toggle-slide-visibility').disabled = !hasPresentation() || !ui.slide;
  $('slide-description-button').disabled = !hasPresentation() || !ui.slide;
  $('toggle-slide-visibility').classList.toggle('is-hidden', isHidden);
  $('toggle-slide-visibility').title = isHidden ? 'Show slide in this variant' : 'Hide slide in this variant';
  $('toggle-slide-visibility').setAttribute('aria-label', $('toggle-slide-visibility').title);
  $('hidden-slide-overlay').hidden = !isHidden || ui.mainMode !== 'slides' || !ui.previewReady || $('slide-iframe').hidden;
}

function goSlide(offset) {
  const slides = navigableSlides();
  const next = slides[slides.indexOf(ui.slide) + offset];
  if (!next) return;
  chooseSlide(next, true);
  if (ui.previewUrl && ui.mainMode === 'slides') {
    $('slide-iframe').contentWindow?.postMessage({type: 'studio-goto', id: next}, '*');
    $('slide-iframe').contentWindow?.postMessage({type: 'studio-layout'}, '*');
  }
}

function toggleHiddenNavigation() {
  ui.showHiddenInNavigation = !ui.showHiddenInNavigation;
  api('/api/session', 'POST', {showHiddenInNavigation:String(ui.showHiddenInNavigation)}).catch((error) => toast(error.message));
  const previous = ui.slide;
  chooseSlide(previous, true);
  if (previous !== ui.slide && ui.mainMode === 'slides') $('slide-iframe').contentWindow?.postMessage({type:'studio-goto', id:ui.slide}, '*');
}

async function openSlideResources() {
  if (!ui.presentation || !ui.slide) return;
  try {
    const resources = await api(`/api/slides/resources?presentation=${encodeURIComponent(ui.presentation)}&slide=${encodeURIComponent(ui.slide)}`);
    const rows = (kind) => resources[kind].map((entry) => {
      const languages = entry.languages.join(', ');
      const data = entry.metadata;
      const detail = data ? (kind === 'facts' ? String(data.value || '') : String(data.description || '')) : 'Unresolved reference';
      return `<div class="slide-resource-row"><button type="button" class="text-button slide-resource-link" data-kind="${kind}" data-id="${escapeHTML(entry.id)}">${escapeHTML(entry.id)}</button><span class="muted">${escapeHTML(languages)}</span><div class="slide-resource-detail">${escapeHTML(detail)}</div></div>`;
    }).join('');
    const markup = `<div class="slide-resource-list"><strong>Facts (${resources.facts.length})</strong>${rows('facts') || '<p class="muted">No fact references</p>'}<strong>Assets (${resources.assets.length})</strong>${rows('assets') || '<p class="muted">No asset references</p>'}</div>`;
    openModal(`References · ${ui.slide}`, markup, 'Close', async () => {});
    for (const button of document.querySelectorAll('.slide-resource-link')) button.onclick = async () => {
      const id = button.dataset.id;
      $('modal').close();
      if (button.dataset.kind === 'assets') {
        await setMainMode('assets');
        displayAssetFolder(assetFolderName(id));
        if (ui.state.assets.assets[id]) openAssetEditor(id);
        else toast(`Unresolved asset: ${id}`);
      } else {
        const index = id.lastIndexOf('.');
        await setMainMode('facts');
        openFactCategory(id.slice(0, index));
        if (!ui.state.facts.categories[id.slice(0, index)]?.[id.slice(index + 1)]) toast(`Unresolved fact: ${id}`);
      }
    };
  } catch (error) { toast(error.message); }
}

async function toggleSlideVisibility() {
  if (!hasPresentation() || !ui.slide || ui.busy) return;
  const hidden = !currentVariant().hidden_slides.includes(ui.slide);
  try {
    await api('/api/slides/visibility', 'POST', {presentation:ui.presentation, variant:ui.variant, slide:ui.slide, hidden});
    await loadState(false);
    updateSlideUI();
  } catch (error) { toast(error.message); }
}

function handlePreviewMessage(event) {
  if (event.source !== $('slide-iframe').contentWindow || !event.data) return;
  if (event.data.url !== ui.previewUrl) return;
  if (event.data.type === 'studio-ready') {
    ui.previewReady = true;
    $('loading-preview').hidden = true;
    layoutSlidePreview();
    updateSlideUI();
    return;
  }
  if (event.data.type !== 'studio-slide') return;
  const slides = ui.state?.slides || [];
  const requested = slides.includes(event.data.id) ? event.data.id : (Number.isInteger(event.data.index) ? slides[event.data.index] : '');
  if (!requested) return;
  chooseSlide(requested, true);
  if (requested !== ui.slide) $('slide-iframe').contentWindow?.postMessage({type:'studio-goto', id:ui.slide}, '*');
}
