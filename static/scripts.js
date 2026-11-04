'use strict';

const scriptState = {id: '', script: null, draft: false, job: '', timer: null};

function confirmDiscardScript() {
  if (!scriptState.draft) return true;
  if (!confirm('Discard unapplied script changes?')) return false;
  scriptState.draft = false;
  updateSaveIndicator();
  $('script-editor').value = scriptState.script?.source || '';
  $('script-apply').disabled = true;
  $('script-revert').disabled = true;
  return true;
}

async function selectScript(id, force = false) {
  if (!force && !confirmDiscardScript()) { $('script-select').value = scriptState.id; return; }
  scriptState.id = id;
  scriptState.script = id ? await api(`/api/script?id=${encodeURIComponent(id)}`) : null;
  $('script-select').value = id;
  $('script-editor').value = scriptState.script?.source || '';
  $('script-description').textContent = scriptState.script?.description || '';
  $('script-editor').disabled = !id || ui.busy || Boolean(scriptState.job);
  $('script-metadata').disabled = !id || ui.busy;
  $('script-remove').disabled = !id || ui.busy;
  $('script-run').disabled = !id || ui.busy || Boolean(scriptState.job);
  scriptState.draft = false;
  updateSaveIndicator();
  $('script-apply').disabled = true;
  $('script-revert').disabled = true;
  updateAIScope();
}

async function renderScripts() {
  const entries = ui.state?.scripts || [];
  const select = $('script-select');
  select.replaceChildren(new Option(entries.length ? 'Select script…' : 'No scripts', ''));
  for (const entry of entries) select.add(new Option(entry.name, entry.id));
  if (!entries.some((entry) => entry.id === scriptState.id)) scriptState.id = entries[0]?.id || '';
  await selectScript(scriptState.id, true);
}

function scriptMetadataMarkup(script = null) {
  const metadata = script || {id:'',name:'',description:'',parameters:[]};
  return field('Identifier', 'id', metadata.id, 'text', 'required pattern="[a-z][a-z0-9_-]*" maxlength="64"') +
    field('Name', 'name', metadata.name, 'text', 'required maxlength="100"') +
    '<div><label for="script-description-input">Description</label><textarea id="script-description-input" name="description" maxlength="2000"></textarea></div>' +
    '<div><label for="script-parameters-input">Parameters (JSON array)</label><textarea id="script-parameters-input" name="parameters" class="script-json" spellcheck="false"></textarea></div>';
}

function openScriptMetadata(script = null) {
  const prior = script?.id || null;
  openModal(prior ? 'Script settings' : 'New script', scriptMetadataMarkup(script), prior ? 'Apply' : 'Create', async (form) => {
    const identifier = String(form.get('id')).trim();
    const metadata = {name:String(form.get('name')).trim(), description:String(form.get('description')), parameters:JSON.parse(String(form.get('parameters')))};
    const source = prior ? $('script-editor').value : 'import json\nimport os\nfrom pathlib import Path\n\nworkspace = Path(os.environ["SLIDE_STUDIO_WORKSPACE"])\nparameters = json.loads(os.environ.get("SLIDE_STUDIO_PARAMETERS", "{}"))\n';
    await api('/api/scripts', 'POST', {id:identifier, previous:prior, source, metadata});
    scriptState.id = identifier;
    scriptState.draft = false;
  updateSaveIndicator();
    await loadState(false);
    await renderScripts();
  });
  $('script-description-input').value = script?.description || '';
  $('script-parameters-input').value = JSON.stringify(script?.parameters || [], null, 2);
}

async function applyScriptSource() {
  if (!scriptState.script || !scriptState.draft) return;
  try {
    const {id, source:unused, ...metadata} = scriptState.script;
    await api('/api/scripts', 'POST', {id, previous:id, source:$('script-editor').value, metadata});
    scriptState.draft = false;
  updateSaveIndicator();
    await loadState(false);
    await renderScripts();
    toast('Script source applied');
  } catch (error) { toast(error.message); }
}

async function removeCurrentScript() {
  if (!scriptState.id || !confirm(`Delete script "${scriptState.script?.name}"?`)) return;
  try {
    await api('/api/scripts', 'DELETE', {id:scriptState.id});
    scriptState.id = '';
    await loadState(false);
    await renderScripts();
  } catch (error) { toast(error.message); }
}

function openRunScript() {
  if (!scriptState.script) return;
  if (scriptState.draft) { toast('Apply script edits before running'); return; }
  const script = scriptState.script;
  const parts = script.parameters.map((parameter) => {
    const label = escapeHTML(parameter.label);
    const name = escapeHTML(parameter.name);
    if (parameter.type === 'boolean') return `<label class="visual-context"><input name="${name}" type="checkbox" ${parameter.default ? 'checked' : ''}> ${label}</label>`;
    return field(parameter.label, parameter.name, parameter.default == null ? '' : String(parameter.default), parameter.type === 'number' ? 'number' : 'text', parameter.required ? 'required' : '');
  }).join('');
  const warning = `<p class="modal-caption">This Python script runs with your user account's permissions. It is not sandboxed against access outside the temporary workspace.</p>`;
  openModal(`Run: ${script.name}`, (parts || '<p class="modal-caption">No parameters</p>') + warning, 'Run', async (form) => {
    const parameters = {};
    for (const parameter of script.parameters) {
      parameters[parameter.name] = parameter.type === 'boolean' ? form.has(parameter.name) : parameter.type === 'number' ? Number(form.get(parameter.name)) : String(form.get(parameter.name));
    }
    const started = await api('/api/scripts/run', 'POST', {id:script.id, parameters});
    scriptState.job = started.job;
    $('script-output').textContent = '';
    $('script-status').textContent = 'Running';
    $('script-run').disabled = true;
    $('script-stop').hidden = false;
    $('script-editor').disabled = true;
    watchScriptJob();
  });
}

async function watchScriptJob() {
  const job = scriptState.job;
  while (job && scriptState.job === job) {
    try {
      const result = await api(`/api/scripts/status?job=${encodeURIComponent(job)}`);
      $('script-output').textContent = result.output;
      $('script-status').textContent = result.status === 'running' ? 'Running' : result.status === 'complete' ? `Completed · ${result.changed.length} files changed` : result.status === 'cancelled' ? 'Cancelled' : `Failed: ${result.error}`;
      if (result.status !== 'running') {
        scriptState.job = '';
        $('script-stop').hidden = true;
        $('script-run').disabled = !scriptState.id;
        $('script-editor').disabled = !scriptState.id;
        await loadState(true);
        return;
      }
    } catch (error) {
      $('script-status').textContent = error.message;
      scriptState.job = '';
      $('script-run').disabled = !scriptState.id;
      $('script-editor').disabled = !scriptState.id;
      $('script-stop').hidden = true;
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
}

function initScripts() {
  $('script-select').onchange = (event) => selectScript(event.target.value);
  $('script-new').onclick = () => openScriptMetadata();
  $('script-metadata').onclick = () => { if (scriptState.script) openScriptMetadata(scriptState.script); };
  $('script-remove').onclick = removeCurrentScript;
  $('script-editor').oninput = () => {
    scriptState.draft = Boolean(scriptState.script && $('script-editor').value !== scriptState.script.source);
    $('script-apply').disabled = !scriptState.draft;
    $('script-revert').disabled = !scriptState.draft;
    updateActionState();
    updateSaveIndicator();
  };
  $('script-apply').onclick = applyScriptSource;
  $('script-revert').onclick = () => { $('script-editor').value = scriptState.script?.source || ''; $('script-editor').dispatchEvent(new Event('input')); };
  $('script-run').onclick = openRunScript;
  $('script-stop').onclick = async () => { if (scriptState.job) await api('/api/scripts/stop', 'POST', {job:scriptState.job}); };
}
