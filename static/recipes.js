'use strict';

const recipeState = {id: '', recipe: null, draft: false, job: ''};

function confirmDiscardRecipe() {
  if (!recipeState.draft) return true;
  if (!confirm('Discard unapplied recipe changes?')) return false;
  recipeState.draft = false;
  $('recipe-editor').value = recipeState.recipe?.instructions || '';
  updateRecipeActions();
  updateSaveIndicator();
  return true;
}

function updateRecipeActions() {
  const selected = Boolean(recipeState.recipe);
  const active = ui.busy || Boolean(recipeState.job);
  $('recipe-editor').disabled = !selected || active;
  $('recipe-metadata').disabled = !selected || active;
  $('recipe-remove').disabled = !selected || active;
  $('recipe-new').disabled = active;
  $('recipe-select').disabled = active;
  $('recipe-apply').disabled = !recipeState.draft || active;
  $('recipe-revert').disabled = !recipeState.draft || active;
  $('recipe-run').disabled = !selected || recipeState.draft || active || !ui.settings?.hasKey;
  $('recipe-stop').hidden = !recipeState.job;
}

async function selectRecipe(id, force = false) {
  if (!force && !confirmDiscardRecipe()) { $('recipe-select').value = recipeState.id; return; }
  recipeState.id = id;
  recipeState.recipe = id ? await api(`/api/recipe?id=${encodeURIComponent(id)}`) : null;
  $('recipe-select').value = id;
  $('recipe-editor').value = recipeState.recipe?.instructions || '';
  $('recipe-description').textContent = recipeState.recipe?.description || '';
  recipeState.draft = false;
  updateRecipeActions();
  updateSaveIndicator();
  updateAIScope();
}

async function renderRecipes() {
  const recipes = ui.state?.recipes || [];
  const select = $('recipe-select');
  select.replaceChildren(new Option(recipes.length ? 'Select recipe…' : 'No recipes', ''));
  for (const recipe of recipes) select.add(new Option(recipe.name, recipe.id));
  if (!recipes.some((recipe) => recipe.id === recipeState.id)) recipeState.id = recipes[0]?.id || '';
  await selectRecipe(recipeState.id, true);
}

function openRecipeMetadata(recipe = null) {
  const prior = recipe?.id || null;
  const metadata = recipe || {id:'', name:'', description:''};
  const markup = field('Identifier', 'id', metadata.id, 'text', 'required pattern="[a-z][a-z0-9_-]*" maxlength="64"') +
    field('Name', 'name', metadata.name, 'text', 'required maxlength="100"') +
    '<div><label for="recipe-description-input">Description</label><textarea id="recipe-description-input" name="description" maxlength="2000"></textarea></div>';
  openModal(prior ? 'Recipe settings' : 'New recipe', markup, prior ? 'Apply' : 'Create', async (form) => {
    const id = String(form.get('id')).trim();
    const instructions = prior ? $('recipe-editor').value : 'Describe what the AI should do when this recipe is run.';
    await api('/api/recipes', 'POST', {id, previous:prior, metadata:{name:String(form.get('name')), description:String(form.get('description'))}, instructions});
    recipeState.id = id;
    recipeState.draft = false;
    await loadState(false);
    await renderRecipes();
  });
  $('recipe-description-input').value = metadata.description;
}

async function applyRecipeInstructions() {
  if (!recipeState.recipe || !recipeState.draft) return;
  try {
    const {id, instructions:unused, ...metadata} = recipeState.recipe;
    await api('/api/recipes', 'POST', {id, previous:id, instructions:$('recipe-editor').value, metadata});
    recipeState.draft = false;
    await loadState(false);
    await renderRecipes();
    toast('Recipe instructions applied');
  } catch (error) { toast(error.message); }
}

async function removeCurrentRecipe() {
  if (!recipeState.recipe || !confirm(`Delete recipe "${recipeState.recipe.name}"?`)) return;
  try {
    await api('/api/recipes', 'DELETE', {id:recipeState.id});
    recipeState.id = '';
    recipeState.draft = false;
    await loadState(false);
    await renderRecipes();
  } catch (error) { toast(error.message); }
}

function openRunRecipe() {
  if (!recipeState.recipe || recipeState.draft || ui.busy) return;
  const recipe = recipeState.recipe;
  if (!ui.settings?.hasKey) { toast('Configure an OpenRouter API key'); return; }
  const models = modelState.catalog.slice();
  const preferredModel = selectedModel('edit');
  if (preferredModel && !models.some((model) => model.id === preferredModel)) models.unshift({id:preferredModel,name:preferredModel});
  const options = models.map((model) => `<option value="${escapeHTML(model.id)}">${escapeHTML(model.name)}</option>`).join('');
  const markup = `<p class="modal-caption">This recipe can modify any presentation and its slides, as well as all facts, assets, scripts, recipes, and other application resources. Changes can be reviewed before saving.</p>` +
    `<div><label for="recipe-run-model">Model</label><select id="recipe-run-model" name="model" required><option value="">Choose model…</option>${options}</select></div>` +
    '<div><label for="recipe-run-effort">Reasoning effort</label><select id="recipe-run-effort" name="effort"></select></div>';
  openModal(`Run recipe: ${recipe.name}`, markup, 'Run', async (form) => {
    const model = String(form.get('model'));
    const effort = String(form.get('effort'));
    if (!model) throw new Error('Choose an OpenRouter model');
    if (!confirmDiscardSource() || !confirmDiscardFactDraft() || !confirmDiscardScript()) return false;
    const selection = {presentation:ui.presentation, variant:ui.variant, language:ui.language, slide:ui.slide};
    const started = await api('/api/recipes/run', 'POST', {id:recipe.id, model, effort, selection});
    recipeState.job = started.job;
    ui.aiJob = started.job;
    ui.busy = true;
    $('recipe-status').textContent = 'Running';
    updateActionState();
    updateRecipeActions();
    watchRecipeJob(started.job);
  });
  $('recipe-run-model').value = preferredModel;
  const updateEfforts = () => {
    const id = $('recipe-run-model').value;
    const info = modelState.catalog.find((entry) => entry.id === id);
    const supported = Array.isArray(info?.reasoningEfforts) ? reasoningChoices.filter((value) => info.reasoningEfforts.includes(value)) : reasoningChoices;
    const effortSelect = $('recipe-run-effort');
    const requested = effortSelect.value || selectedEffort('edit');
    effortSelect.replaceChildren(new Option('Default', 'default'));
    for (const value of supported) effortSelect.add(new Option(value === 'xhigh' ? 'Extra high' : value[0].toUpperCase() + value.slice(1), value));
    effortSelect.value = ['default', ...supported].includes(requested) ? requested : 'default';
  };
  $('recipe-run-model').onchange = updateEfforts;
  updateEfforts();
}

async function watchRecipeJob(job) {
  try {
    while (recipeState.job === job) {
      await new Promise((resolve) => setTimeout(resolve, 450));
      const status = await api(`/api/ai/status?job=${encodeURIComponent(job)}`);
      if (status.status === 'running' || status.status === 'stopping') {
        $('recipe-status').textContent = status.status === 'stopping' ? 'Stopping…' : 'Running';
        continue;
      }
      if (status.status === 'complete') {
        $('recipe-status').textContent = status.result?.note || 'Completed · Changes applied to working state';
        await loadState(true);
      } else if (status.status === 'cancelled') $('recipe-status').textContent = 'Cancelled · No changes applied';
      else $('recipe-status').textContent = `Failed: ${status.error || 'Unknown error'}`;
      break;
    }
  } catch (error) {
    $('recipe-status').textContent = `Connection error: ${error.message}. Check the working state before retrying.`;
  } finally {
    if (recipeState.job === job) {
      recipeState.job = '';
      ui.aiJob = '';
      ui.busy = false;
      updateActionState();
      updateRecipeActions();
    }
  }
}

function initRecipes() {
  $('recipe-select').onchange = (event) => selectRecipe(event.target.value);
  $('recipe-new').onclick = () => openRecipeMetadata();
  $('recipe-metadata').onclick = () => { if (recipeState.recipe) openRecipeMetadata(recipeState.recipe); };
  $('recipe-remove').onclick = removeCurrentRecipe;
  $('recipe-editor').oninput = () => {
    recipeState.draft = Boolean(recipeState.recipe && $('recipe-editor').value !== recipeState.recipe.instructions);
    updateRecipeActions();
    updateSaveIndicator();
  };
  $('recipe-apply').onclick = applyRecipeInstructions;
  $('recipe-revert').onclick = () => { $('recipe-editor').value = recipeState.recipe?.instructions || ''; $('recipe-editor').dispatchEvent(new Event('input')); };
  $('recipe-run').onclick = openRunRecipe;
  $('recipe-stop').onclick = async () => {
    if (recipeState.job) {
      try { await api('/api/ai/cancel', 'POST', {job:recipeState.job}); }
      catch (error) { toast(error.message); }
    }
  };
}
