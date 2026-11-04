'use strict';

function initExplorer() {
  $('preview-frame').append($('tab-facts'), $('tab-assets'));
  $('preview-frame').dataset.mode = 'slides';
  $('facts-search').oninput = renderFacts;
  $('facts-usage').onchange = renderFacts;
  $('assets-search').oninput = renderAssets;
  $('assets-sort').onchange = renderAssets;
  $('assets-usage').onchange = renderAssets;
  $('facts-back').onclick = () => openFactCategory('');
  $('assets-back').onclick = () => displayAssetFolder(ui.assetFolder.includes('/') ? ui.assetFolder.slice(0, ui.assetFolder.lastIndexOf('/')) : '');
  for (const button of document.querySelectorAll('#facts-table [data-sort]')) button.onclick = () => {
    if (ui.factDraft) { toast('Apply or discard edits before sorting'); return; }
    const field = button.dataset.sort;
    ui.factSort = { field, descending: ui.factSort?.field === field ? !ui.factSort.descending : false };
    renderFacts();
  };
  $('facts-new-category').onclick = createFactCategoryDialog;
  $('add-fact').onclick = () => openFactEditor(ui.factCategory);
  $('facts-apply-batch').onclick = () => applyFactTableEdits().catch((error) => toast(error.message));
  $('facts-bulk-remove').onclick = () => removeSelected('facts');
  $('facts-merge').onclick = () => mergeSelected('facts');
  $('facts-move').onclick = () => moveSelectedFactsDialog();
  $('facts-select-visible').onchange = (event) => {
    for (const id of ui.visible.facts) {
      if (event.target.checked) ui.selected.facts.add(id);
      else ui.selected.facts.delete(id);
    }
    renderFacts();
  };
  $('assets-new-folder').onclick = createAssetFolderDialog;
  $('add-asset').onclick = () => openAssetEditor();
  $('assets-bulk-remove').onclick = () => removeSelected('assets');
  $('assets-merge').onclick = () => mergeSelected('assets');
  $('assets-move-selected').onclick = () => moveSelectedAssetsDialog();
  $('assets-select-visible').onchange = (event) => {
    for (const alias of ui.visible.assets) {
      if (event.target.checked) ui.selected.assets.add(alias);
      else ui.selected.assets.delete(alias);
    }
    renderAssets();
  };
  $('assets-list').addEventListener('dragover', (event) => {
    if ([...event.dataTransfer.types].some((type) => ['Files', 'application/x-studio-assets', 'application/x-studio-folder'].includes(type))) event.preventDefault();
  });
  $('assets-list').addEventListener('drop', (event) => {
    if (event.target.closest('.asset-file-tile,.folder-tile')) return;
    dropAssetsOnFolder(event, ui.assetFolder);
  });
  installAssetMarquee();
  installAssetAutoScroll();
  $('assets-list').onkeydown = async (event) => {
    if (event.target.closest('input,textarea,button')) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
      event.preventDefault();
      for (const alias of ui.visible.assets) ui.selected.assets.add(alias);
      renderAssets();
    }
    if (event.key === 'Delete' && ui.selected.assets.size) { event.preventDefault(); await removeSelected('assets'); }
    if (event.key === 'F2' && ui.selectedFolder) { event.preventDefault(); renameAssetFolderDialog(ui.selectedFolder); }
    if (event.key === 'Enter' && ui.selectedFolder) { event.preventDefault(); displayAssetFolder(ui.selectedFolder); }
    if (event.key === 'Backspace' && ui.assetFolder) {
      event.preventDefault();
      displayAssetFolder(ui.assetFolder.includes('/') ? ui.assetFolder.slice(0, ui.assetFolder.lastIndexOf('/')) : '');
    }
    if (event.key === 'F2' && ui.selected.assets.size === 1) { event.preventDefault(); renameAssetDialog([...ui.selected.assets][0]); }
  };
}

function confirmDiscardFactDraft() {
  if (!ui.factDraft) return true;
  if (!window.confirm('Discard unapplied fact table edits?')) return false;
  ui.factDraft = false;
  updateSaveIndicator();
  return true;
}

function openFactCategory(category) {
  if (ui.mainMode === 'facts') queueMicrotask(updateAIScope);
  if (!confirmDiscardFactDraft()) return;
  ui.factCategory = category;
  ui.selected.facts.clear();
  renderFacts();
}

function createFactCategoryDialog() {
  openModal('New fact table', field('Table name', 'category', '', 'text', 'required maxlength="60"'), 'Create', async (form) => {
    const category = String(form.get('category')).trim();
    await api('/api/facts/categories', 'POST', {category});
    ui.factCategory = category;
    await loadState();
  });
}

function renameFactCategoryDialog(category) {
  if (ui.factDraft) { toast('Apply or discard table edits first'); return; }
  openModal('Rename fact table', field('Table name', 'name', category, 'text', 'required maxlength="60"'), 'Rename', async (form) => {
    const name = String(form.get('name')).trim();
    if (name !== category) await api('/api/facts/categories/rename', 'POST', {old: category, new: name});
    if (ui.factCategory === category) ui.factCategory = name;
    await loadState(true);
  });
}

async function removeFactCategory(category) {
  const count = Object.keys(ui.state.facts.categories?.[category] || {}).length;
  if (!window.confirm(`Delete table “${category}” and its ${count} facts? References in slide sources will remain.`)) return;
  try {
    await api('/api/facts/categories', 'DELETE', {category});
    if (ui.factCategory === category) ui.factCategory = '';
    ui.factDraft = false;
  updateSaveIndicator();
    ui.selected.facts.clear();
    await loadState(true);
  } catch (error) { toast(error.message); }
}

function factMatching(category, key, fact) {
  const search = $('facts-search').value.toLowerCase().trim();
  return `${category} ${key} ${fact.value} ${fact.description || ''}`.toLowerCase().includes(search) && matchesUsage('facts', `${category}.${key}`);
}

function renderFacts() {
  if (!ui.state) return;
  const categories = ui.state.facts.categories || {};
  if (ui.factCategory && !Object.hasOwn(categories, ui.factCategory)) ui.factCategory = '';
  const current = ui.factCategory;
  const inCategory = Boolean(current);
  const root = $('facts-list');
  const panel = $('facts-table-panel');
  root.hidden = inCategory;
  panel.hidden = !inCategory;
  $('facts-back').disabled = !inCategory;
  $('facts-new-category').hidden = inCategory;
  $('add-fact').hidden = !inCategory;
  $('facts-selection-control').hidden = !inCategory;
  const crumb = $('facts-breadcrumb');
  crumb.replaceChildren();
  const home = document.createElement('button'); home.className = 'text-button'; home.textContent = 'Facts';
  home.onclick = () => openFactCategory('');
  crumb.append(home);
  if (inCategory) { const sep = document.createElement('span'); sep.textContent = '/'; crumb.append(sep); const name = document.createElement('strong'); name.textContent = current; crumb.append(name); }
  if (!inCategory) {
    ui.visible.facts = [];
    root.replaceChildren();
    for (const category of Object.keys(categories).sort((a, b) => a.localeCompare(b))) {
      const entries = Object.entries(categories[category]);
      const count = entries.filter(([key, fact]) => factMatching(category, key, fact)).length;
      if (entries.length && !count) continue;
      const tile = document.createElement('button');
      tile.className = 'folder-tile fact-folder';
      tile.type = 'button';
      tile.innerHTML = '<span class="folder-icon">▤</span><span class="tile-name"></span><span class="tile-meta"></span>';
      tile.querySelector('.tile-name').textContent = category;
      tile.querySelector('.tile-meta').textContent = `${count} fact${count === 1 ? '' : 's'}`;
      tile.onclick = () => openFactCategory(category);
      tile.onkeydown = (event) => { if (event.key === 'Enter') openFactCategory(category); };
      tile.oncontextmenu = (event) => { event.preventDefault(); showExplorerMenu(event, [
        ['Open', () => openFactCategory(category)],
        ['Rename', () => renameFactCategoryDialog(category)],
        ['Delete table', () => removeFactCategory(category)],
      ]); };
      root.append(tile);
    }
    if (!root.children.length) root.innerHTML = '<div class="library-empty">No matching categories</div>';
    updateExplorerSelections('facts');
    return;
  }
  let entries = Object.entries(categories[current]).filter(([key, fact]) => factMatching(current, key, fact));
  const sort = ui.factSort || {field:'key', descending:false};
  entries.sort((a,b) => {
    const value = ([key, fact]) => sort.field === 'key' ? key : String(fact[sort.field] ?? '');
    return value(a).localeCompare(value(b), undefined, {numeric: true, sensitivity: 'base'}) * (sort.descending ? -1 : 1);
  });
  for (const button of document.querySelectorAll('#facts-table [data-sort]')) {
    const active = button.dataset.sort === sort.field;
    button.classList.toggle('active', active);
    button.querySelector('span').textContent = active ? (sort.descending ? '▼' : '▲') : '';
    button.setAttribute('aria-sort', active ? (sort.descending ? 'descending' : 'ascending') : 'none');
  }
  ui.visible.facts = entries.map(([key]) => `${current}.${key}`);
  const body = $('facts-table').querySelector('tbody');
  if (ui.factDraft) { updateExplorerSelections('facts'); return; }
  body.replaceChildren();
  for (const [key, fact] of entries) {
    const tr = document.createElement('tr');
    const id = `${current}.${key}`;
    const checked = ui.selected.facts.has(id);
    tr.innerHTML = `<td><input class="fact-select" type="checkbox" aria-label="Select fact" ${checked ? 'checked' : ''}></td><td><input class="fact-cell fact-key" data-field="key" type="text" aria-label="Fact key"></td><td><input class="fact-cell" data-field="value" type="text"></td><td><input class="fact-cell" data-field="updated" type="date"></td><td><input class="fact-cell" data-field="description" type="text"></td><td><button class="icon-button fact-copy" title="Copy reference" aria-label="Copy reference"><svg viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7 .3l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7-.3l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg></button></td>`;
    tr.dataset.key = key;
    tr.querySelector('[data-field=key]').value = key;
    tr.querySelector('[data-field=value]').value = fact.value ?? '';
    tr.querySelector('[data-field=updated]').value = fact.updated || '';
    tr.querySelector('[data-field=description]').value = fact.description || '';
    const copyReference = () => navigator.clipboard.writeText(`{{fact:${current}.${key}}}`).then(() => toast('Fact reference copied')).catch((error) => toast(error.message));
    tr.querySelector('.fact-copy').onclick = copyReference;
    tr.querySelector('[data-field=key]').oncontextmenu = (event) => { event.preventDefault(); showExplorerMenu(event, [['Copy reference', copyReference], ['Show usages', () => openUsages('facts', id)], ['Move to table…', () => moveSelectedFactsDialog([id])]]); };
    tr.querySelector('.fact-select').onchange = (event) => { if (event.target.checked) ui.selected.facts.add(id); else ui.selected.facts.delete(id); updateExplorerSelections('facts'); };
    for (const input of tr.querySelectorAll('.fact-cell')) input.oninput = () => {
      ui.factDraft = true;
      $('facts-apply-batch').disabled = false;
      $('facts-apply-batch').hidden = false;
      updateSaveIndicator();
    };
    body.append(tr);
  }
  updateExplorerSelections('facts');
}

function moveSelectedFactsDialog(identifiers = [...ui.selected.facts]) {
  if (ui.factDraft) { toast('Apply or discard table edits before moving facts'); return; }
  if (!identifiers.length) return;
  const tables = Object.keys(ui.state.facts.categories || {}).sort((a, b) => a.localeCompare(b));
  const choices = tables.map((table) => `<option value="${escapeHTML(table)}" ${table === ui.factCategory ? 'disabled' : ''}>${escapeHTML(table)}</option>`).join('');
  openModal('Move facts', `<div><label for="destination-table">Destination table</label><select id="destination-table" name="table" required><option value="">Choose a table…</option>${choices}</select></div><p class="modal-caption">Move ${identifiers.length} fact${identifiers.length === 1 ? '' : 's'} and update references in all presentations.</p>`, 'Move', async (form) => {
    const target = String(form.get('table'));
    const entries = identifiers.map((id) => { const dot = id.lastIndexOf('.'); return {category:id.slice(0, dot), key:id.slice(dot + 1)}; });
    await api('/api/facts/move', 'POST', {entries, target});
    ui.factCategory = target;
    ui.selected.facts.clear();
    await loadState(true);
  });
}

function renameFactDialog(category, key) {
  if (ui.factDraft) { toast('Apply table changes before renaming'); return; }
  const markup = field('Category', 'category', category, 'text', 'required maxlength="60"') + field('Identifier', 'key', key, 'text', 'required pattern="[a-z][a-z0-9_-]*"');
  openModal('Rename / move fact', markup, 'Apply', async (form) => {
    await api('/api/facts/rename', 'POST', {category, key, newCategory: String(form.get('category')).trim(), newKey: form.get('key')});
    ui.selected.facts.clear();
    ui.factCategory = String(form.get('category')).trim();
    await loadState(true);
  });
}

async function applyFactTableEdits() {
  if (!ui.factDraft) return;
  const category = ui.factCategory;
  const changes = [...$('facts-table').querySelectorAll('tbody tr')].map((tr) => ({
    key: tr.dataset.key,
    newKey: tr.querySelector('[data-field=key]').value.trim(),
    value: tr.querySelector('[data-field=value]').value,
    updated: tr.querySelector('[data-field=updated]').value,
    description: tr.querySelector('[data-field=description]').value,
  }));
  if (!changes.length) return;
  await api('/api/facts/batch', 'POST', {category, changes});
  ui.factDraft = false;
  updateSaveIndicator();
  $('facts-apply-batch').disabled = true;
  $('facts-apply-batch').hidden = true;
  await loadState(true);
}

function assetFolderName(alias) {
  return alias.includes('/') ? alias.slice(0, alias.lastIndexOf('/')) : '';
}

function assetPath(folder, name) {
  return folder ? `${folder}/${name}` : name;
}

function assetBaseName(alias) {
  return alias.slice(alias.lastIndexOf('/') + 1);
}

function knownAssetFolders() {
  const folders = new Set(ui.state.assets.folders || []);
  for (const [alias, asset] of Object.entries(ui.state.assets.assets || {})) {
    const folder = assetFolderName(alias);
    if (!folder) continue;
    const components = folder.split('/');
    for (let i = 1; i <= components.length; i++) folders.add(components.slice(0, i).join('/'));
  }
  return [...folders].sort((a, b) => a.localeCompare(b));
}

function displayAssetFolder(folder) {
  if (ui.mainMode === 'assets') queueMicrotask(updateAIScope);
  if (!confirmDiscardFactDraft()) return;
  ui.assetFolder = folder;
  $('assets-back').disabled = !folder;
  ui.selected.assets.clear();
  ui.assetAnchor = '';
  ui.selectedFolder = '';
  renderAssets();
}

function createAssetFolderDialog() {
  const parent = ui.assetFolder;
  openModal('New folder', field('Folder name', 'folder', '', 'text', 'required maxlength="60"'), 'Create', async (form) => {
    const name = String(form.get('folder')).trim();
    const path = parent ? `${parent}/${name}` : name;
    await api('/api/assets/folders', 'POST', {folder: path});
    ui.assetFolder = path;
    await loadState();
  });
}

function moveAssetFolderDialog(folder) {
  const parent = assetFolderName(folder);
  const folders = ['', ...knownAssetFolders().filter((candidate) => candidate !== folder && !candidate.startsWith(folder + '/'))].filter((candidate) => candidate !== parent);
  const choices = folders.map((target) => `<option value="${escapeHTML(target)}">${escapeHTML(target || 'Assets (root)')}</option>`).join('');
  openModal('Move folder', `<div><label for="folder-destination">Destination folder</label><select id="folder-destination" name="destination" required>${choices}</select></div>`, 'Move', async (form) => {
    await moveAssetFolder(folder, String(form.get('destination')));
  });
}

async function moveAssetFolder(source, destinationParent) {
  const target = assetPath(destinationParent, assetBaseName(source));
  if (source === target) return;
  await api('/api/assets/folders/move', 'POST', {old:source, new:target});
  if (ui.assetFolder === source || ui.assetFolder.startsWith(source + '/')) ui.assetFolder = target + ui.assetFolder.slice(source.length);
  ui.selectedFolder = '';
  ui.selected.assets.clear();
  await loadState(true);
}

function renameAssetFolderDialog(folder) {
  const oldName = folder.slice(folder.lastIndexOf('/') + 1);
  const parent = folder.includes('/') ? folder.slice(0, folder.lastIndexOf('/')) : '';
  openModal('Rename folder', field('Name', 'name', oldName, 'text', 'required maxlength="60"'), 'Rename', async (form) => {
    const name = String(form.get('name')).trim();
    const target = parent ? `${parent}/${name}` : name;
    if (target !== folder) await api('/api/assets/folders/move', 'POST', {old: folder, new: target});
    if (ui.assetFolder === folder || ui.assetFolder.startsWith(folder + '/')) ui.assetFolder = target + ui.assetFolder.slice(folder.length);
    ui.selected.assets.clear();
    await loadState(true);
  });
}

async function deleteAssetFolder(folder) {
  const entries = Object.keys(ui.state.assets.assets || {}).filter((alias) => alias.startsWith(folder + '/'));
  if (!window.confirm(`Delete folder “${folder}”, its subfolders, and ${entries.length} assets? References in presentations will remain.`)) return;
  try {
    await api('/api/assets/folders', 'DELETE', {folder});
    if (ui.assetFolder === folder || ui.assetFolder.startsWith(folder + '/')) ui.assetFolder = folder.includes('/') ? folder.slice(0, folder.lastIndexOf('/')) : '';
    ui.selected.assets.clear();
    await loadState(true);
  } catch (error) { toast(error.message); }
}

function moveSelectedAssetsDialog(aliases = [...ui.selected.assets]) {
  if (!aliases.length) return;
  const folders = ['', ...knownAssetFolders()];
  const current = new Set(aliases.map(assetFolderName));
  const choices = folders.map((folder) => {
    const depth = folder ? folder.split('/').length : 0;
    const name = folder ? folder.slice(folder.lastIndexOf('/') + 1) : 'Assets (root)';
    return `<button type="button" class="folder-picker-option" data-folder="${escapeHTML(folder)}" title="${escapeHTML(folder || 'Assets (root)')}" style="--folder-depth:${depth}"><span class="folder-picker-icon">${folder ? '▰' : '⌂'}</span><span>${escapeHTML(name)}</span>${current.has(folder) ? '<small>Current</small>' : ''}</button>`;
  }).join('');
  openModal('Move assets', `<div><label>Destination folder</label><div class="folder-picker" role="group" aria-label="Destination folder">${choices}</div><input type="hidden" name="folder" id="destination-folder"></div>`, 'Move', async (form) => {
    const folder = String(form.get('folder'));
    const moves = Object.fromEntries(aliases.map((alias) => [alias, assetPath(folder, assetBaseName(alias))]));
    if (aliases.every((alias) => alias === moves[alias])) throw new Error('Choose a different destination');
    await api('/api/assets/move', 'POST', {moves});
    ui.selected.assets.clear();
    await loadState(true);
  });
  $('modal-submit').disabled = true;
  for (const button of document.querySelectorAll('.folder-picker-option')) {
    button.onclick = () => {
      for (const item of document.querySelectorAll('.folder-picker-option')) item.classList.toggle('active', item === button);
      const folder = button.dataset.folder;
      $('destination-folder').value = folder;
      $('modal-submit').disabled = aliases.every((alias) => assetFolderName(alias) === folder);
    };
  }
}

function renameAssetDialog(alias) {
  const folder = assetFolderName(alias);
  openModal('Rename asset', field('Name', 'name', assetBaseName(alias), 'text', 'required pattern="[a-z][a-z0-9_-]*"'), 'Rename', async (form) => {
    const destination = assetPath(folder, String(form.get('name')).trim());
    if (destination !== alias) await api('/api/assets/move', 'POST', {moves: {[alias]: destination}});
    ui.selected.assets.clear();
    await loadState(true);
  });
}

function makeAssetBreadcrumb() {
  const crumb = $('assets-breadcrumb');
  crumb.replaceChildren();
  $('assets-back').disabled = !ui.assetFolder;
  const root = document.createElement('button');
  root.className = 'text-button';
  root.textContent = 'Assets';
  root.onclick = () => displayAssetFolder('');
  root.ondragover = (event) => { event.preventDefault(); root.classList.add('drop-target'); };
  root.ondragleave = () => root.classList.remove('drop-target');
  root.ondrop = (event) => { root.classList.remove('drop-target'); dropAssetsOnFolder(event, ''); };
  crumb.append(root);
  let prefix = '';
  for (const part of ui.assetFolder.split('/').filter(Boolean)) {
    const separator = document.createElement('span'); separator.textContent = '/'; crumb.append(separator);
    prefix = prefix ? prefix + '/' + part : part;
    const thisFolder = prefix;
    const button = document.createElement('button');
    button.className = 'text-button';
    button.textContent = part;
    button.onclick = () => displayAssetFolder(thisFolder);
    button.ondragover = (event) => { event.preventDefault(); button.classList.add('drop-target'); };
    button.ondragleave = () => button.classList.remove('drop-target');
    button.ondrop = (event) => { button.classList.remove('drop-target'); dropAssetsOnFolder(event, thisFolder); };
    crumb.append(button);
  }
}

function showExplorerMenu(event, entries) {
  document.getElementById('explorer-context')?.remove();
  const menu = document.createElement('div');
  menu.id = 'explorer-context';
  menu.className = 'explorer-context';
  for (const [name, action] of entries) {
    const button = document.createElement('button'); button.textContent = name;
    button.onclick = () => { menu.remove(); action(); };
    menu.append(button);
  }
  document.body.append(menu);
  menu.style.left = `${Math.min(event.clientX, window.innerWidth - menu.offsetWidth - 8)}px`;
  menu.style.top = `${Math.min(event.clientY, window.innerHeight - menu.offsetHeight - 8)}px`;
  const dismiss = (click) => {
    if (!menu.contains(click.target)) menu.remove();
    if (!menu.isConnected) document.removeEventListener('pointerdown', dismiss, true);
  };
  document.addEventListener('pointerdown', dismiss, true);
  window.addEventListener('keydown', (key) => { if (key.key === 'Escape') menu.remove(); }, {once:true});
}

function makeFolderTile(folder, number) {
  const tile = document.createElement('div');
  tile.className = 'folder-tile';
  tile.tabIndex = 0;
  tile.innerHTML = '<span class="folder-icon">▰</span><span class="tile-name"></span><span class="tile-meta"></span>';
  tile.querySelector('.tile-name').textContent = folder.slice(folder.lastIndexOf('/') + 1);
  tile.querySelector('.tile-meta').textContent = number ? `${number} images` : 'Folder';
  tile.onclick = () => displayAssetFolder(folder);
  tile.onkeydown = (event) => { if (event.key === 'Enter') displayAssetFolder(folder); };
  tile.oncontextmenu = (event) => {
    event.preventDefault();
    showExplorerMenu(event, [['Open', () => displayAssetFolder(folder)], ['Move folder…', () => moveAssetFolderDialog(folder)], ['Rename folder', () => renameAssetFolderDialog(folder)], ['Delete folder', () => deleteAssetFolder(folder)]]);
  };
  tile.draggable = true;
  tile.ondragstart = (event) => {
    event.dataTransfer.setData('application/x-studio-folder', folder);
    event.dataTransfer.effectAllowed = 'move';
  };
  tile.ondragover = (event) => { event.preventDefault(); tile.classList.add('drop-target'); };
  tile.ondragleave = () => tile.classList.remove('drop-target');
  tile.ondrop = (event) => { tile.classList.remove('drop-target'); dropAssetsOnFolder(event, folder); };
  return tile;
}

async function dropAssetsOnFolder(event, folder) {
  event.preventDefault();
  event.stopPropagation();
  try {
    const sourceFolder = event.dataTransfer.getData('application/x-studio-folder');
    if (sourceFolder) {
      await moveAssetFolder(sourceFolder, folder);
      return;
    }
    const value = event.dataTransfer.getData('application/x-studio-assets');
    if (value) {
      const aliases = JSON.parse(value);
      const moves = Object.fromEntries(aliases.map((alias) => [alias, assetPath(folder, assetBaseName(alias))]));
      if (!aliases.every((alias) => moves[alias] === alias)) await api('/api/assets/move', 'POST', {moves});
      ui.selected.assets.clear();
      await loadState(true);
    } else if (event.dataTransfer.files.length) {
      await uploadDroppedImages([...event.dataTransfer.files], folder);
    }
  } catch (error) { toast(error.message); }
}

async function uploadDroppedImages(files, category, description = '', added = dateLocal()) {
  const supported = files.filter((file) => /^image\/(png|jpeg|webp|gif|svg\+xml)$/.test(file.type));
  if (supported.length !== files.length) throw new Error('Unsupported image format');
  if (supported.some((file) => file.size > 12 * 1024 * 1024)) throw new Error('Images must be under 12 MB each');
  const occupied = new Set(Object.keys(ui.state.assets.assets || {}));
  for (const file of supported) {
    const alias = assetPath(category, fileAlias(file.name));
    if (occupied.has(alias)) throw new Error(`${alias} already exists`);
    occupied.add(alias);
  }
  try {
  for (const file of supported) {
    const alias = assetPath(category, fileAlias(file.name));
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    await api('/api/assets', 'POST', {alias, filename:file.name, content:btoa(binary), description, category, added});
  }
  } finally {
    await loadState(true);
  }
}

function selectAssetTile(alias, event) {
  const order = ui.visible.assets;
  if (event.shiftKey && ui.assetAnchor && order.includes(ui.assetAnchor)) {
    const a = order.indexOf(ui.assetAnchor), b = order.indexOf(alias);
    if (!event.ctrlKey && !event.metaKey) ui.selected.assets.clear();
    for (let i = Math.min(a, b); i <= Math.max(a, b); i++) ui.selected.assets.add(order[i]);
  } else if (event.ctrlKey || event.metaKey) {
    if (ui.selected.assets.has(alias)) ui.selected.assets.delete(alias);
    else ui.selected.assets.add(alias);
    ui.assetAnchor = alias;
  } else {
    ui.selected.assets.clear();
    ui.selected.assets.add(alias);
    ui.assetAnchor = alias;
  }
  for (const tile of $('assets-list').querySelectorAll('.asset-file-tile')) {
    tile.classList.toggle('selected', ui.selected.assets.has(tile.dataset.alias));
    tile.querySelector('input').checked = ui.selected.assets.has(tile.dataset.alias);
  }
  updateExplorerSelections('assets');
}

function duplicateAssetDialog(alias) {
  const taken = new Set(Object.keys(ui.state.assets.assets || {}));
  const basename = assetBaseName(alias);
  let proposed = assetPath(assetFolderName(alias), `${basename}-copy`);
  let suffix = 2;
  while (taken.has(proposed)) proposed = assetPath(assetFolderName(alias), `${basename}-copy-${suffix++}`);
  openModal('Duplicate asset', field('New alias', 'destination', proposed, 'text', 'required'), 'Duplicate', async (form) => {
    const destination = String(form.get('destination')).trim();
    await api('/api/assets/duplicate', 'POST', {alias, destination});
    ui.selected.assets.clear();
    ui.assetFolder = assetFolderName(destination);
    await loadState(true);
  });
}

function makeAssetTile(alias, asset) {
  const tile = document.createElement('div');
  tile.className = 'asset-file-tile';
  tile.tabIndex = 0;
  tile.draggable = true;
  tile.dataset.alias = alias;
  if (ui.selected.assets.has(alias)) tile.classList.add('selected');
  const check = document.createElement('input');
  check.type = 'checkbox'; check.className = 'entity-check';
  check.checked = ui.selected.assets.has(alias);
  check.setAttribute('aria-label', `Select ${alias}`);
  check.onclick = (event) => { event.stopPropagation(); selectAssetTile(alias, {...event, ctrlKey:true}); };
  const image = document.createElement('img');
  image.src = `/api/asset-image?alias=${encodeURIComponent(alias)}&v=${encodeURIComponent(asset.file)}`;
  image.alt = asset.description || alias;
  image.loading = 'lazy';
  const name = document.createElement('span'); name.className = 'tile-name'; name.textContent = assetBaseName(alias);
  const date = document.createElement('span'); date.className = 'tile-meta'; date.textContent = asset.added || 'Date unknown';
  tile.append(check, image, name, date);
  image.onclick = (event) => { event.stopPropagation(); openAssetImage(alias); };
  tile.onclick = (event) => {
    if (event.shiftKey || event.ctrlKey || event.metaKey) selectAssetTile(alias, event);
    else openAssetImage(alias);
  };
  tile.onkeydown = (event) => { if (event.key === 'Enter') openAssetImage(alias); };
  tile.oncontextmenu = (event) => {
    event.preventDefault();
    if (!ui.selected.assets.has(alias)) selectAssetTile(alias, event);
    const selection = ui.visible.assets.filter((name) => ui.selected.assets.has(name));
    const multiple = selection.length > 1;
    const entries = [];
    if (!multiple) {
      entries.push(['Open details', () => openAssetEditor(alias)]);
      entries.push(['Replace image…', () => openAssetEditor(alias, true)]);
      entries.push(['View image', () => openAssetImage(alias)]);
      entries.push(['Duplicate asset…', () => duplicateAssetDialog(alias)]);
      entries.push(['Show usages', () => openUsages('assets', alias)]);
    }
    entries.push([multiple ? 'Copy references' : 'Copy reference', () => navigator.clipboard.writeText(selection.map((name) => `{{asset:${name}}}`).join('\n')).then(() => toast(multiple ? 'References copied' : 'Reference copied')).catch((error) => toast(error.message))]);
    if (!multiple) entries.push(['Rename', () => renameAssetDialog(alias)]);
    entries.push(['Move selected', () => moveSelectedAssetsDialog()]);
    entries.push(['Delete selected', () => removeSelected('assets')]);
    showExplorerMenu(event, entries);
  };
  tile.ondragstart = (event) => {
    if (!ui.selected.assets.has(alias)) selectAssetTile(alias, event);
    event.dataTransfer.setData('application/x-studio-assets', JSON.stringify([...ui.selected.assets]));
    event.dataTransfer.effectAllowed = 'move';
  };
  return tile;
}

function assetScrollSpeed(container, pointerY) {
  const bounds = container.getBoundingClientRect();
  if (pointerY < bounds.top || pointerY > bounds.bottom) return 0;
  const edge = Math.min(75, bounds.height / 3);
  if (pointerY < bounds.top + edge) return -Math.max(0, 16 * (bounds.top + edge - pointerY) / edge);
  if (pointerY > bounds.bottom - edge) return Math.max(0, 16 * (pointerY - (bounds.bottom - edge)) / edge);
  return 0;
}

function installAssetAutoScroll() {
  const root = $('assets-list');
  let pointerY = null;
  let frame = 0;
  const scroll = () => {
    if (pointerY === null) { frame = 0; return; }
    root.scrollTop += assetScrollSpeed(root, pointerY);
    frame = requestAnimationFrame(scroll);
  };
  const stop = () => {
    pointerY = null;
    cancelAnimationFrame(frame);
    frame = 0;
  };
  root.addEventListener('dragover', (event) => {
    pointerY = event.clientY;
    if (!frame) frame = requestAnimationFrame(scroll);
  });
  root.addEventListener('dragleave', (event) => {
    const bounds = root.getBoundingClientRect();
    if (event.clientY < bounds.top || event.clientY > bounds.bottom || event.clientX < bounds.left || event.clientX > bounds.right) stop();
  });
  window.addEventListener('dragend', stop, true);
  window.addEventListener('drop', stop, true);
  window.addEventListener('blur', stop);
}

function installAssetMarquee() {
  const root = $('assets-list');
  const surface = $('tab-assets');
  let drag = null;
  let frame = 0;
  const update = () => {
    if (!drag) { frame = 0; return; }
    const delta = assetScrollSpeed(root, drag.pointerY);
    if (delta) {
      const before = root.scrollTop;
      root.scrollTop += delta;
      if (root.scrollTop !== before) updateMarquee(drag.pointerX, drag.pointerY);
    }
    frame = requestAnimationFrame(update);
  };
  const updateMarquee = (clientX, clientY) => {
    if (!drag) return;
    const bounds = root.getBoundingClientRect();
    const current = {x:Math.max(0,Math.min(root.clientWidth,clientX-bounds.left))+root.scrollLeft,y:Math.max(0,Math.min(root.clientHeight,clientY-bounds.top))+root.scrollTop};
    const left = Math.min(drag.origin.x,current.x), top = Math.min(drag.origin.y,current.y);
    const width = Math.abs(drag.origin.x-current.x), height = Math.abs(drag.origin.y-current.y);
    if (width > 3 || height > 3) drag.moved = true;
    Object.assign(drag.marquee.style,{left:left+'px',top:top+'px',width:width+'px',height:height+'px'});
    const chosen = new Set(drag.initial);
    for (const tile of root.querySelectorAll('.asset-file-tile')) {
      const rect = tile.getBoundingClientRect();
      const x = rect.left-bounds.left+root.scrollLeft, y=rect.top-bounds.top+root.scrollTop;
      if (x < left+width && x+rect.width > left && y < top+height && y+rect.height > top) chosen.add(tile.dataset.alias);
    }
    ui.selected.assets = chosen;
    for (const tile of root.querySelectorAll('.asset-file-tile')) {
      const selected = chosen.has(tile.dataset.alias);
      tile.classList.toggle('selected',selected);
      tile.querySelector('input').checked = selected;
    }
    updateExplorerSelections('assets');
  };
  const finish = () => { cancelAnimationFrame(frame); frame = 0; drag?.marquee.remove(); drag = null; };
  surface.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || event.target.closest('.folder-tile,.asset-file-tile,button,input,select,.explorer-nav,.explorer-toolbar')) return;
    if (!event.target.closest('#tab-assets')) return;
    const bounds = root.getBoundingClientRect();
    const origin = {x: Math.max(0, Math.min(root.clientWidth, event.clientX - bounds.left)) + root.scrollLeft, y: Math.max(0, Math.min(root.clientHeight, event.clientY - bounds.top)) + root.scrollTop};
    const additive = event.ctrlKey || event.metaKey;
    const initial = new Set(additive ? ui.selected.assets : []);
    const marquee = document.createElement('div');
    marquee.className = 'selection-rectangle';
    root.append(marquee);
    drag = {origin, initial, marquee, moved: false, pointerX:event.clientX, pointerY:event.clientY};
    if (!frame) frame = requestAnimationFrame(update);
    surface.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  surface.addEventListener('pointermove', (event) => {
    if (!drag) return;
    drag.pointerX = event.clientX;
    drag.pointerY = event.clientY;
    updateMarquee(event.clientX, event.clientY);
  });
  surface.addEventListener('pointerup', () => {
    if (!drag) return;
    const restore = !drag.moved;
    const initial = drag.initial;
    finish();
    if (restore) { ui.selected.assets = new Set(initial); renderAssets(); }
  });
  surface.addEventListener('pointercancel', finish);
}

function renderAssets() {
  if (!ui.state) return;
  const assets = ui.state.assets.assets || {};
  const folders = knownAssetFolders();
  if (ui.assetFolder && !folders.includes(ui.assetFolder)) ui.assetFolder = '';
  const folder = ui.assetFolder;
  const search = $('assets-search').value.trim().toLowerCase();
  const matching = sortedEntries(Object.entries(assets).map(([alias, asset]) => [alias, {...asset, bytes: ui.state.assetSizes?.[alias] || 0}]).filter(([alias, asset]) =>
    `${alias} ${asset.description || ''} ${asset.category || ''}`.toLowerCase().includes(search) && matchesUsage('assets', alias)), 'assets');
  const descendants = matching.filter(([alias]) => folder ? alias.startsWith(folder + '/') : true);
  ui.visible.assets = descendants.filter(([alias]) => assetFolderName(alias) === folder).map(([alias]) => alias);
  makeAssetBreadcrumb();
  const root = $('assets-list'); root.replaceChildren();
  const childFolders = folders.filter((path) => {
    if (path === folder || (folder && !path.startsWith(folder + '/'))) return false;
    const rest = folder ? path.slice(folder.length + 1) : path;
    if (rest.includes('/')) return false;
    return !search && $('assets-usage').value === 'all' || matching.some(([alias]) => alias.startsWith(path + '/'));
  });
  for (const child of childFolders) { const tile = makeFolderTile(child, matching.filter(([alias]) => alias.startsWith(child + '/')).length); tile.classList.toggle('selected', ui.selectedFolder === child); root.append(tile); }
  for (const [alias, asset] of descendants) if (assetFolderName(alias) === folder) root.append(makeAssetTile(alias, asset));
  if (!root.children.length) root.innerHTML = '<div class="library-empty">No items in this folder</div>';
  $('assets-count').textContent = `${descendants.length} matching image${descendants.length === 1 ? '' : 's'}`;
  updateExplorerSelections('assets');
}

function updateExplorerSelections(kind) {
  const selected = ui.selected[kind];
  const visible = ui.visible[kind];
  const check = $(`${kind}-select-visible`);
  check.checked = visible.length > 0 && visible.every((id) => selected.has(id));
  check.indeterminate = !check.checked && visible.some((id) => selected.has(id));
  $(`${kind}-bulk-remove`).disabled = selected.size === 0;
  $(`${kind}-bulk-remove`).hidden = selected.size === 0;
  $(`${kind}-bulk-remove`).textContent = `Delete (${selected.size})`;
  $(`${kind}-merge`).hidden = selected.size < 2;
  $(`${kind}-merge`).disabled = selected.size < 2;
  if (kind === 'assets') {
    $('assets-move-selected').disabled = selected.size === 0;
    $('assets-move-selected').hidden = selected.size === 0;
  } else {
    $('facts-move').hidden = selected.size === 0;
    $('facts-move').disabled = selected.size === 0 || ui.factDraft;
    $('facts-selected-count').hidden = selected.size === 0;
    $('facts-selected-count').textContent = `${selected.size} selected`;
    $('facts-apply-batch').hidden = !ui.factDraft;
  }
}


function mergeSelected(kind) {
  const aliases = [...ui.selected[kind]];
  if (aliases.length < 2) return;
  if (kind === 'facts' && ui.factDraft) { toast('Apply table edits before merging'); return; }
  const entries = aliases.map((alias) => ({alias, label: alias}));
  const options = entries.map((item) => `<option value="${escapeHTML(item.alias)}">${escapeHTML(item.label)}</option>`).join('');
  openModal(`Merge ${kind}`, `<p class="modal-caption">Choose which ${kind === 'facts' ? 'value' : 'image'} to retain. All references to the other identifiers will point to this one.</p><div><label for="merge-survivor">Keep</label><select id="merge-survivor" name="survivor">${options}</select></div>`, 'Merge', async (form) => {
    const survivor = String(form.get('survivor'));
    if (!window.confirm(`Merge ${aliases.length} ${kind} into “${survivor}”?`)) return;
    if (kind === 'assets') {
      await api('/api/assets/merge','POST',{aliases,survivor});
    } else {
      const parse = (id) => {const position = id.lastIndexOf('.'); return {category:id.slice(0,position),key:id.slice(position+1)};};
      await api('/api/facts/merge','POST',{entries:aliases.map(parse),survivor:parse(survivor)});
    }
    ui.selected[kind].clear();
    await loadState(true);
  });
}

async function openUsages(kind, identifier) {
  try {
    const rows = await api(`/api/usages?kind=${encodeURIComponent(kind)}&id=${encodeURIComponent(identifier)}`);
    const html = rows.length ? rows.map((item, index) => `<button type="button" class="usage-result" data-index="${index}">${escapeHTML(item.name)} · ${escapeHTML(item.language)} · ${escapeHTML(item.slide)}</button>`).join('') : '<p class="muted">No references</p>';
    openModal(`Usages · ${identifier}`, `<div class="usage-list">${html}</div>`, 'Close', async () => {});
    for (const button of document.querySelectorAll('.usage-result')) button.onclick = async () => {
      const target = rows[Number(button.dataset.index)];
      $('modal').close();
      if (ui.factDraft && !confirmDiscardFactDraft()) return;
      ui.presentation = target.presentation;
      ui.language = target.language;
      ui.slide = target.slide;
      ui.mainMode = 'slides';
      await loadState(true);
      chooseSlide(target.slide, true);
      document.getElementById('mode-slides').click();
      rememberChoices();
    };
  } catch (error) { toast(error.message); }
}

function openAssetImage(alias) {
  const url = `/api/asset-image?alias=${encodeURIComponent(alias)}`;
  const content = `<div class="asset-viewer"><div class="asset-viewer-toolbar"><button type="button" id="asset-fit">Fit</button><button type="button" id="asset-actual">100%</button><button type="button" id="asset-open-details">Details</button><button type="button" id="asset-duplicate">Duplicate</button><span id="asset-zoom-label"></span></div><div class="asset-viewport" id="asset-viewport"><img id="asset-large-image" src="${url}" draggable="false" alt="${escapeHTML(alias)}"></div></div>`;
  openModal(`Image · ${alias}`, content, 'Close', async () => {});
  const viewport = document.getElementById('asset-viewport');
  const image = document.getElementById('asset-large-image');
  const label = document.getElementById('asset-zoom-label');
  let zoom = 1, x = 0, y = 0, fitZoom = 1;
  const paint = () => { image.style.transform = `translate(${x}px, ${y}px) scale(${zoom})`; label.textContent = `${Math.round(zoom * 100)}%`; };
  const fit = () => { fitZoom = Math.min(viewport.clientWidth / image.naturalWidth, viewport.clientHeight / image.naturalHeight, 1); zoom = fitZoom; x = 0; y = 0; paint(); };
  image.onload = fit;
  document.getElementById('asset-fit').onclick = fit;
  document.getElementById('asset-actual').onclick = () => { zoom = 1; x = 0; y = 0; paint(); };
  document.getElementById('asset-open-details').onclick = () => { $('modal').close(); openAssetEditor(alias); };
  document.getElementById('asset-duplicate').onclick = () => { $('modal').close(); duplicateAssetDialog(alias); };
  viewport.onwheel = (event) => { event.preventDefault(); zoom = Math.max(.05, Math.min(12, zoom * (event.deltaY < 0 ? 1.15 : 1/1.15))); paint(); };
  let start = null;
  viewport.onpointerdown = (event) => { start = {x:event.clientX - x, y:event.clientY - y}; viewport.setPointerCapture(event.pointerId); };
  viewport.onpointermove = (event) => { if (start) { x = event.clientX - start.x; y = event.clientY - start.y; paint(); } };
  viewport.onpointerup = () => { start = null; };
}
