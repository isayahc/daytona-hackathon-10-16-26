'use strict';
const el = id => document.getElementById(id);
let order, events = [];
async function api(path, body) {
  const response = await fetch(`/api/tickets/${path}`, body === undefined ? {cache: 'no-store'} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Could not complete the request.');
  return value;
}
function showOrder(value) {
  order = value;
  el('choose-panel').hidden = true;
  el('payment-panel').hidden = value.status === 'paid';
  el('ticket-panel').hidden = value.status !== 'paid';
  el('order-title').textContent = value.title;
  el('price').textContent = `${value.price_xrp} XRP · Testnet`;
  el('receiver').textContent = value.receiver;
  el('tag').textContent = value.destination_tag;
  el('payer').textContent = value.buyer;
  el('payment-json').textContent = JSON.stringify(value.payment_request, null, 2);
  if (value.status === 'paid') {
    el('ticket-event').textContent = `${value.title} · One admission`;
    el('ticket-code').textContent = value.ticket_code;
    el('check-in-status').textContent = value.checked_in ? 'Already checked in' : 'Ready for entry';
    el('receipt-link').href = value.explorer_url;
  }
  history.replaceState(null, '', `#order=${encodeURIComponent(value.id)}`);
}
function eventInfo() {
  const event = events.find(item => item.id === el('event').value);
  el('event-info').textContent = event ? `${event.kind} · ${event.price_xrp} XRP · ${event.available} available` : '';
  el('reserve').disabled = !event || event.available <= 0;
}
async function busy(button, action) {
  button.disabled = true;
  el('message').textContent = '';
  try { await action(); } catch (error) { el('message').textContent = error.message; }
  finally { button.disabled = false; }
}
el('event').onchange = eventInfo;
el('checkout-form').onsubmit = event => {
  event.preventDefault();
  busy(el('reserve'), async () => showOrder(await api('orders', {
    event_id: el('event').value, buyer: el('buyer').value.trim()
  })));
};
el('verify-form').onsubmit = event => {
  event.preventDefault();
  busy(el('verify'), async () => showOrder(await api('verify', {
    order_id: order.id, tx_hash: el('tx-hash').value.trim()
  })));
};
el('copy').onclick = () => busy(el('copy'), async () => {
  await navigator.clipboard.writeText(JSON.stringify(order.payment_request, null, 2));
  el('copy').textContent = 'Copied';
});
async function init() {
  const orderId = new URLSearchParams(location.hash.slice(1)).get('order');
  if (orderId) {
    el('choose-panel').hidden = true;
    showOrder(await api(`orders/${encodeURIComponent(orderId)}`));
    return;
  }
  events = (await api('events')).events;
  el('event').replaceChildren();
  for (const event of events) {
    const option = document.createElement('option');
    option.value = event.id; option.textContent = event.title;
    el('event').append(option);
  }
  el('event').disabled = !events.length;
  if (!events.length) el('message').textContent = 'No events are on sale yet. Check back with the organizer.';
  eventInfo();
}
init().catch(error => { el('message').textContent = error.message; });
