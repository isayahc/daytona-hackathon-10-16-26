/* Testnet-only payments; seeds and signed blobs never enter the browser. */
'use strict';
(() => {
  const el = id => document.getElementById(id);
  let state, busy = false;
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function request(path, payload) {
    const response = await fetch(path, payload ? {method:'POST', headers:{'Content-Type':'application/json','X-Operator-Request':'1'}, body:JSON.stringify(payload)} : {});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Payment request failed.');
    return result;
  }
  function render() {
    const eventId = el('payment-event').value, totals = state.totals[eventId];
    el('payment-addresses').textContent = `Event wallet: ${state.addresses.event}\nDemo attendee: ${state.addresses.attendee}\nApproved vendor: ${state.addresses.vendor}`;
    el('payment-totals').textContent = `Collected ${totals.received_xrp} · Paid ${totals.paid_xrp} · Approved expenses ${totals.committed_xrp} · Cash surplus before network fees ${totals.cash_surplus_xrp} · After all commitments ${totals.after_commitments_xrp} · Expense cap ${state.budget_xrp} test XRP. Faucet funds are excluded from sales.`;
    const invoices = state.invoices.filter(i => i.event_id === eventId);
    el('payment-invoices').innerHTML = invoices.length ? invoices.map(i => `<article class="payment-invoice"><strong>${escape(i.label)}</strong> · ${escape(i.kind)} · ${escape(i.amount_xrp)} test XRP · <b>${escape(i.status)}</b><p>Sales threshold: ${escape(i.min_sales_xrp)} test XRP</p><details><summary>Invoice / external payment instructions</summary><p>Send exactly ${escape(i.amount_xrp)} test XRP to ${escape(i.destination)} with InvoiceID:</p><code>${escape(i.id)}</code></details>${i.explorer_url ? `<p><a target="_blank" rel="noopener noreferrer" href="${escape(i.explorer_url)}">View Testnet transaction ↗</a></p>` : ''}${i.status === 'open' ? `<button data-pay="${i.id}">${i.kind === 'ticket' ? 'Pay with demo attendee' : 'Check policy & pay vendor'}</button>` : ''}${i.status !== 'paid' && i.status !== 'failed' ? `<button data-reconcile="${i.id}">Reconcile receipt</button>` : ''}</article>`).join('') : '<p>No invoices yet. Create a ticket invoice to start.</p>';
    el('payment-invoices').querySelectorAll('[data-pay]').forEach(button => button.onclick = () => action(async () => {
      const invoice = await request('/api/xrpl/pay', {invoice_id:button.dataset.pay});
      return invoice.status === 'pending' ? 'Submission is pending. Reconcile the same transaction; do not create a replacement.' : 'Validated payment recorded.';
    }));
    el('payment-invoices').querySelectorAll('[data-reconcile]').forEach(button => button.onclick = () => {
      const invoice = state.invoices.find(i => i.id === button.dataset.reconcile);
      const hash = invoice.tx_hash || prompt('Paste the Testnet transaction hash for this invoice:');
      if (hash) action(async () => {
        const updated = await request('/api/xrpl/reconcile', {invoice_id:invoice.id, tx_hash:hash.trim()});
        return `Receipt status: ${updated.status}.`;
      });
    });
  }
  async function refresh() {
    state = await request('/api/xrpl');
    el('payments-enabled').hidden = !state.enabled;
    if (!state.enabled) {
      el('payments-status').textContent = 'Payments disabled. Run python -m operator_app.payments --setup, set XRPL_ENABLED=true in .env, and restart the server.';
      return;
    }
    if (!el('payment-event').options.length) {
      const workspace = await request('/api/workspace');
      workspace.events.forEach(event => el('payment-event').add(new Option(event.title, event.id)));
    }
    render();
  }
  async function action(operation) {
    if (busy) return;
    busy = true;
    el('payments-panel').setAttribute('aria-busy', 'true');
    el('payments-status').textContent = 'Working… Testnet validation may take several seconds.';
    let message;
    try { message = await operation(); } catch (error) { message = error.message; }
    try { await refresh(); } catch (error) { message = `${message || ''} Refresh failed: ${error.message}`; }
    if (message) el('payments-status').textContent = message;
    busy = false;
    el('payments-panel').removeAttribute('aria-busy');
  }
  el('invoice-form').onsubmit = event => {
    event.preventDefault();
    const form = new FormData(event.target);
    action(async () => {
      await request('/api/xrpl/invoices', {event_id:el('payment-event').value, kind:form.get('kind'), label:form.get('label'), amount_xrp:form.get('amount_xrp'), min_sales_xrp:form.get('min_sales_xrp'), approved:form.get('approved') === 'on'});
      event.target.elements.approved.checked = false;
      return 'Invoice created. Payments require a separate action.';
    });
  };
  el('payment-event').onchange = () => render();
  el('payments-refresh').onclick = () => action(async () => 'Payment records refreshed.');
  refresh().then(() => {if (state.enabled) el('payments-status').textContent = 'Connected to the Testnet payment workflow. Test XRP has no monetary value.';}).catch(error => {el('payments-status').textContent = error.message;});
})();
