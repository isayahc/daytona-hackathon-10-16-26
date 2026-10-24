/* Persistent, event-scoped agent chat. Drafting never dispatches outreach. */
'use strict';
(() => {
  let eventId = null, timer, signature = '', running = false, submitting = false, refreshVersion = 0;
  const prompts = new Map(), edits = new Map();
  const roles = {venues:'Venues', sponsors:'Sponsors', catering:'Catering', contacts:'Contacts'};

  async function request(url, body) {
    const response = await fetch(url, body === undefined ? {} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'Could not reach the event agent.');
    return value;
  }

  function buttons() {
    $('chat-submit').disabled = !eventId || running || submitting;
    $('chat-submit').textContent = running ? 'Agent drafting…' : submitting ? 'Starting…' : 'Draft messages →';
    $('chat-badge').textContent = running ? 'Drafting…' : 'Plan together';
  }

  function renderRuns(runs) {
    running = runs.some(run => run.status === 'running');
    buttons();
    const next = JSON.stringify(runs);
    if (next === signature) return;
    signature = next;
    $('chat-history').innerHTML = runs.length ? runs.map(run =>
      `<article class="chat-message user-message"><strong>You</strong><p>${esc(run.prompt)}</p></article>` +
      `<article class="chat-message"><strong>Planning agent</strong><p>${esc(run.status === 'running' ? 'Preparing messages for your event’s parties. This may take a few minutes.' : run.status === 'failed' ? run.error : run.reply)}</p></article>`
    ).join('') : '<p class="empty">Tell me your event idea and what you need from each party. I’ll prepare messages for this event.</p>';
    $('chat-history').scrollTop = $('chat-history').scrollHeight;
    const latest = [...runs].reverse().find(run => run.status === 'completed');
    $('draft-count').textContent = latest ? `${latest.drafts.length} drafts · not sent` : 'Not sent';
    if (!latest) {
      $('party-drafts').innerHTML = `<p class="empty">${running ? 'The agent is preparing your drafts…' : 'Open Event chat to create your first messages.'}</p>`;
      return;
    }
    $('party-drafts').innerHTML = `<p class="research-intro">Latest completed request: ${esc(latest.prompt)}. New requests create a new set of drafts.</p><div class="party-grid">` +
      Object.entries(roles).map(([role, label]) => `<section class="party-group"><h3>${label}</h3>${latest.drafts.filter(d => d.target.role === role).map(d => {
        const value = edits.get(d.id) || d;
        return `<form class="message-draft" data-run="${esc(latest.id)}" data-draft="${esc(d.id)}"><h4>${esc(d.target.name)}</h4><span class="tag">${d.target.is_mock ? 'Fictional sample' : d.target.unassigned ? 'Recipient needed' : 'Proposed recipient'}</span><label>Subject<input name="subject" required maxlength="300" value="${esc(value.subject)}"></label><label>Message<textarea name="body" rows="8" required maxlength="12000">${esc(value.body)}</textarea></label><div class="draft-actions"><button type="submit" class="secondary">Save edits</button><button type="button" class="secondary copy-message">Copy message</button></div><small class="save-state">${edits.has(d.id) ? 'Unsaved edits' : d.edited ? 'Edits saved locally' : 'Agent draft · saved locally'}</small></form>`;
      }).join('')}</section>`).join('') + '</div>';
    $('party-drafts').querySelectorAll('form').forEach(form => {
      const values = () => ({subject:form.elements.subject.value, body:form.elements.body.value});
      form.oninput = () => { edits.set(form.dataset.draft, values()); form.querySelector('.save-state').textContent = 'Unsaved edits'; };
      form.onsubmit = async event => {
        event.preventDefault();
        const button = form.querySelector('[type=submit]'), submitted = values();
        button.disabled = true;
        try {
          await request('/api/message-drafts', {run_id:form.dataset.run, draft_id:form.dataset.draft, ...submitted});
          if (JSON.stringify(values()) === JSON.stringify(submitted)) {
            edits.delete(form.dataset.draft);
            form.querySelector('.save-state').textContent = 'Edits saved locally';
          }
        } catch (error) { form.querySelector('.save-state').textContent = error.message; }
        finally { button.disabled = false; }
      };
      form.querySelector('.copy-message').onclick = async () => {
        try {
          await navigator.clipboard.writeText(`${form.elements.subject.value}\n\n${form.elements.body.value}`);
          $('draft-feedback').textContent = 'Message copied. Nothing has been sent.';
        } catch { $('draft-feedback').textContent = 'Clipboard unavailable. Select the message text to copy it manually.'; }
      };
    });
  }

  async function refresh(id) {
    const version = ++refreshVersion;
    clearTimeout(timer);
    try {
      const value = await request(`/api/chat?event_id=${encodeURIComponent(id)}`);
      if (id !== eventId || version !== refreshVersion) return;
      renderRuns(value.runs);
      $('chat-status').textContent = '';
      if (running) timer = setTimeout(() => refresh(id), 2000);
    } catch (error) {
      if (id !== eventId || version !== refreshVersion) return;
      $('chat-status').textContent = error.message;
      timer = setTimeout(() => refresh(id), 5000);
    }
  }

  document.addEventListener('workspace-event', event => {
    if (event.detail === eventId) return;
    eventId = event.detail;
    signature = ''; running = false;
    $('chat-event-name').textContent = data.events.find(e => e.id === eventId).title;
    $('chat-prompt').value = prompts.get(eventId) || '';
    $('chat-history').innerHTML = '<p class="empty">Loading conversation…</p>';
    $('party-drafts').innerHTML = '<p class="empty">Loading drafts…</p>';
    $('draft-count').textContent = 'Not sent';
    $('draft-feedback').textContent = '';
    buttons(); refresh(eventId);
  });
  $('chat-prompt').oninput = () => prompts.set(eventId, $('chat-prompt').value);
  $('view-drafts').onclick = () => { $('event-chat').open = false; };
  $('chat-form').onsubmit = async event => {
    event.preventDefault();
    const id = eventId, prompt = $('chat-prompt').value.trim();
    if (!id || !prompt || submitting || running) return;
    submitting = true; buttons();
    const report = reports.get(id), candidates = {};
    if (report) Object.keys(roles).forEach(role => {
      candidates[role] = (report.findings[role] || []).slice(0, 3).map(c => c.name);
    });
    try {
      await request('/api/chat', {event_id:id, prompt, candidates});
      prompts.delete(id);
      if (eventId === id) { $('chat-prompt').value = ''; await refresh(id); }
    } catch (error) { if (eventId === id) $('chat-status').textContent = error.message; }
    finally { submitting = false; buttons(); }
  };
  if (data) document.dispatchEvent(new CustomEvent('workspace-event', {detail:selectedId}));
})();
