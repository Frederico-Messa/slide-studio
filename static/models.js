'use strict';

const modelState = {catalog: [], preferences: {edit: {model:'', effort:'default'}, chat:{model:'', effort:'default'}}, selections: {edit: {model:'', effort:'default'}, chat:{model:'', effort:'default'}}};
const reasoningChoices = ['none','minimal','low','medium','high','xhigh','max'];

function selectedModel(kind) {
  return modelState.selections[kind].model;
}

function selectedEffort(kind) {
  return modelState.selections[kind].effort;
}

function renderModelOptions() {
  for (const kind of ['edit','chat']) {
    const select = $(`${kind}-model`);
    const chosen = modelState.selections[kind].model;
    select.replaceChildren(new Option('Choose model…', ''));
    if (chosen && !modelState.catalog.some((item) => item.id === chosen)) select.add(new Option(chosen, chosen));
    for (const model of modelState.catalog) select.add(new Option(model.name, model.id));
    select.value = chosen;
    updateReasoningOptions(kind);
  }
  updateActionState();
}

function updateReasoningOptions(kind) {
  const select = $(`${kind}-effort`);
  const choice = modelState.selections[kind];
  const model = modelState.catalog.find((item) => item.id === choice.model);
  let efforts = reasoningChoices;
  if (model && Array.isArray(model.reasoningEfforts)) efforts = reasoningChoices.filter((value) => model.reasoningEfforts.includes(value));
  select.replaceChildren(new Option('Default', 'default'));
  for (const effort of efforts) select.add(new Option(effort === 'xhigh' ? 'Extra high' : effort[0].toUpperCase() + effort.slice(1), effort));
  if (!['default', ...efforts].includes(choice.effort)) choice.effort = 'default';
  select.value = choice.effort;
  select.disabled = ui.busy || (kind === 'chat' && chatState.active) || !choice.model;
  $(`${kind}-model`).disabled = ui.busy || (kind === 'chat' && chatState.active);
  if (kind === 'chat') renderChatUsage();
}

async function refreshModelCatalog() {
  if (!ui.settings?.hasKey) return;
  const models = await api('/api/models');
  modelState.catalog = models;
  for (const model of models) ui.modelCapabilities.set(model.id, model.imageInput);
  renderModelOptions();
}

async function persistModelSelection(kind) {
  const current = modelState.selections[kind];
  modelState.preferences[kind] = {...current};
  try {
    await api('/api/session','POST',{[`${kind}Model`]:current.model,[`${kind}Effort`]:current.effort});
    if (kind === 'chat' && chatState.id) {
      chatState.chat = await api('/api/chats/settings','POST',{id:chatState.id,model:current.model,effort:current.effort});
    }
  } catch (error) { toast(error.message); }
}

function setChatModelFromConversation(chat) {
  modelState.selections.chat = chat ? {model:chat.model || modelState.preferences.chat.model,effort:chat.reasoning_effort || modelState.preferences.chat.effort} : {...modelState.preferences.chat};
  renderModelOptions();
}

async function initModelChoices(session) {
  for (const kind of ['edit','chat']) {
    modelState.preferences[kind] = {model:session[`${kind}Model`] || '',effort:session[`${kind}Effort`] || 'default'};
    modelState.selections[kind] = {...modelState.preferences[kind]};
    $(`${kind}-model`).onchange = async (event) => {
      modelState.selections[kind].model = event.target.value;
      updateReasoningOptions(kind);
      await persistModelSelection(kind);
      updateActionState();
    };
    $(`${kind}-effort`).onchange = async (event) => {
      modelState.selections[kind].effort = event.target.value;
      await persistModelSelection(kind);
      updateActionState();
    };
  }
  renderModelOptions();
  refreshModelCatalog().catch((error) => { console.warn('Model catalog unavailable:', error.message); });
}

function renderChatUsage() {
  const meter = $('chat-token-indicator');
  if (!meter) return;
  const assistant = [...(chatState.chat?.messages || [])].reverse().find((item) => item.role === 'assistant' && item.usage);
  const usage = assistant?.usage;
  const input = usage?.prompt_tokens;
  const output = usage?.completion_tokens;
  const limit = usage?.context_length || modelState.catalog.find((item) => item.id === assistant?.model)?.contextLength;
  const valid = Number.isInteger(input) && Number.isInteger(output);
  const percent = valid && Number.isFinite(limit) && limit > 0 ? Math.min(100, Math.round(100 * input / limit)) : null;
  meter.classList.toggle('unknown', !valid);
  meter.style.setProperty('--usage-percentage', `${percent || 0}%`);
  $('chat-context-percent').textContent = percent === null ? (valid ? 'i' : '—') : `${percent}%`;
  meter.title = !valid ? 'No token usage reported for this conversation' :
    `Last completed request (${assistant.model || 'model unknown'})\nInput: ${input.toLocaleString()} tokens\nOutput: ${output.toLocaleString()} tokens` +
    (Number.isInteger(usage.cached_tokens) ? `\nCached input: ${usage.cached_tokens.toLocaleString()} tokens` : '') +
    (Number.isFinite(limit) && limit > 0 ? `\nContext window: ${limit.toLocaleString()} tokens\nInput utilization: ${percent}%` : '\nContext window: unknown');
}
