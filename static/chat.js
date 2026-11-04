'use strict';

const chatState = {id:'',chat:null,job:'',active:false,list:[]};

async function refreshChatList(preferred = chatState.id) {
  chatState.list = await api('/api/chats');
  const select = $('chat-select');
  select.replaceChildren(new Option('New chat', ''));
  for (const item of chatState.list) select.add(new Option(item.name, item.id));
  if (!chatState.list.some((item) => item.id === preferred)) preferred = '';
  chatState.id = preferred;
  select.value = preferred;
  chatState.chat = preferred ? await api(`/api/chat?id=${encodeURIComponent(preferred)}`) : null;
  setChatModelFromConversation(chatState.chat);
  renderChat();
  updateChatControls();
}

function updateChatControls() {
  const chosen = Boolean(chatState.chat);
  const history = chatState.chat?.messages || [];
  const busy = chatState.active || ui.busy;
  for (const id of ['chat-new','chat-save-as','chat-delete','chat-select']) {
    const button = $(id);
    button.disabled = busy || ((id === 'chat-save-as' || id === 'chat-delete') && !chosen);
  }
  $('chat-send').disabled = busy || !ui.settings?.hasKey || !selectedModel('chat') || !$('chat-prompt').value.trim();
  $('chat-stop').hidden = !chatState.active;
  $('chat-send').hidden = chatState.active;
  $('chat-running').hidden = !chatState.active;
  const includeChat = $('include-chat-context');
  includeChat.disabled = !history.length || busy;
  includeChat.parentElement.title = history.length ? 'Include messages from the selected AI Chat conversation in this editing request.' : 'Include messages from an AI Chat conversation in this editing request. Start a conversation in AI Chat first.';
  if (!history.length) includeChat.checked = false;
  updateReasoningOptions('chat');
}

function chatPointMenu(event, until) {
  event.preventDefault();
  if (!chatState.id || chatState.active || ui.busy) return;
  showExplorerMenu(event, [
    ['Branch from here', () => createChatBranch(until).catch((error) => toast(error.message))],
    ['Restore to here', () => restoreChatTo(until).catch((error) => toast(error.message))]
  ]);
}

function renderChat() {
  const messages = $('chat-messages');
  messages.replaceChildren();
  const history = chatState.chat?.messages || [];
  if (!history.length) {
    const empty = document.createElement('div');
    empty.className = 'chat-empty';
    empty.textContent = 'No messages';
    messages.append(empty);
    renderChatUsage();
    return;
  }
  for (let i = 0; i < history.length; i += 2) {
    const turn = document.createElement('article');
    turn.className = 'chat-turn';
    const user = document.createElement('div');
    user.className = 'chat-message user';
    user.textContent = history[i]?.content || '';
    turn.append(user);
    if (history[i + 1]) {
      const assistant = document.createElement('div');
      assistant.className = 'chat-message assistant';
      assistant.textContent = history[i + 1].content;
      turn.append(assistant);
    }
    const actions = document.createElement('div');
    actions.className = 'chat-turn-actions';
    const menu = document.createElement('button');
    menu.type = 'button';
    menu.className = 'chat-message-menu';
    menu.textContent = '⋯';
    menu.title = 'Conversation actions';
    menu.setAttribute('aria-label', 'Conversation actions');
    menu.onclick = () => {
      const rect = menu.getBoundingClientRect();
      chatPointMenu({preventDefault() {}, clientX:rect.right,clientY:rect.bottom}, i + 2);
    };
    turn.oncontextmenu = (event) => chatPointMenu(event, i + 2);
    actions.append(menu);
    turn.append(actions);
    messages.append(turn);
  }
  messages.scrollTop = messages.scrollHeight;
  renderChatUsage();
}

async function createChatBranch(until) {
  if (!chatState.chat) return;
  const item = await api('/api/chats', 'POST', {name:`${chatState.chat.name} branch`,source:chatState.id,until,model:selectedModel('chat'),effort:selectedEffort('chat')});
  await refreshChatList(item.id);
  await api('/api/session','POST',{chatId:item.id});
}

async function restoreChatTo(until) {
  if (!chatState.chat || !confirm('Discard later messages from this conversation?')) return;
  await api('/api/chats/restore','POST',{id:chatState.id,until});
  await refreshChatList(chatState.id);
}

async function chatSend() {
  if (chatState.active || ui.busy || !$('chat-prompt').value.trim() || !selectedModel('chat')) return;
  const content = $('chat-prompt').value.trim();
  chatState.active = true;
  updateChatControls();
  try {
    const started = await api('/api/chat/message', 'POST', {id:chatState.id,message:content,model:selectedModel('chat'),effort:selectedEffort('chat'),selection:{presentation:ui.presentation,variant:ui.variant,language:ui.language,slide:ui.slide}});
    chatState.job = started.job;
    $('chat-status').textContent = 'Generating…';
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      const job = await api(`/api/ai/status?job=${encodeURIComponent(chatState.job)}`);
      if (job.status === 'running' || job.status === 'stopping') {
        $('chat-status').textContent = job.status === 'stopping' ? 'Stopping…' : 'Generating…';
        continue;
      }
      if (job.status === 'complete') {
        $('chat-prompt').value = '';
        $('chat-status').textContent = '';
        const id = job.result?.chat || chatState.id;
        await refreshChatList(id);
        await api('/api/session', 'POST', {chatId:id});
      } else {
        $('chat-status').textContent = job.status === 'cancelled' ? 'Cancelled' : (job.error || 'Chat failed');
      }
      break;
    }
  } catch (error) { $('chat-status').textContent = error.message; }
  finally { chatState.active = false; chatState.job = ''; updateChatControls(); }
}

function initChat() {
  $('chat-new').onclick = async () => {
    try { await refreshChatList(''); await api('/api/session','POST',{chatId:''}); $('chat-prompt').focus(); }
    catch (error) { toast(error.message); }
  };
  $('chat-select').onchange = async (event) => {
    try { await refreshChatList(event.target.value); await api('/api/session','POST',{chatId:chatState.id}); }
    catch (error) { toast(error.message); }
  };
  $('chat-save-as').onclick = () => {
    if (!chatState.chat) return;
    openModal('Chat name', field('Name','name',chatState.chat.name,'text','required maxlength="120"'), 'Save', async (form) => {
      await api('/api/chats/rename','POST',{id:chatState.id,name:String(form.get('name'))});
      await refreshChatList(chatState.id);
    });
  };
  $('chat-delete').onclick = async () => {
    if (!chatState.chat || !confirm(`Delete chat “${chatState.chat.name}”?`)) return;
    try {
      await api('/api/chats','DELETE',{id:chatState.id});
      await refreshChatList('');
      await api('/api/session','POST',{chatId:''});
    } catch (error) { toast(error.message); }
  };
  $('chat-send').onclick = chatSend;
  $('chat-stop').onclick = () => api('/api/ai/cancel','POST',{job:chatState.job}).catch((error) => toast(error.message));
  $('chat-prompt').oninput = updateChatControls;
  $('chat-prompt').onkeydown = (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); chatSend(); }
  };
}
