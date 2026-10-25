'use strict';
const el = id => document.getElementById(id);
let order, events = [];
let xamanEnabled = false, connection = null, activeRequest = null, walletSocket = null;
let verificationTimer = null, checkingWallet = false, verificationAttempts = 0;
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
  walletControls();
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
  finally { button.disabled = false; walletControls(); }
}
el('event').onchange = eventInfo;
el('checkout-form').onsubmit = event => {
  event.preventDefault();
  busy(el('reserve'), async () => showOrder(await api('orders', {
    event_id: el('event').value, buyer: el('buyer').value.trim(),
    ...(connection ? {connection_id: connection.id} : {})
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
  xamanEnabled = (await api('xaman/config')).enabled;
  walletControls();
  const savedConnection = sessionStorage.getItem('xaman-connection');
  if (xamanEnabled && savedConnection) {
    try {
      const value = await api('xaman/status', {request_id: savedConnection});
      if (value.status === 'connected') setConnection(value);
      else sessionStorage.removeItem('xaman-connection');
    } catch (_) { sessionStorage.removeItem('xaman-connection'); }
  }
  const orderId = new URLSearchParams(location.hash.slice(1)).get('order');
  if (orderId) {
    el('choose-panel').hidden = true;
    showOrder(await api(`orders/${encodeURIComponent(orderId)}`));
    await restoreWalletRequest();
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
  await restoreWalletRequest();
}

function walletControls() {
  el('xaman-check').disabled = !activeRequest || checkingWallet;
  el('connect-xaman').disabled = !xamanEnabled || Boolean(activeRequest);
  el('connect-xaman').textContent = connection ? 'Change Xaman wallet' : 'Connect Xaman';
  el('wallet-status').textContent = !xamanEnabled
    ? 'Xaman is not configured yet. The organizer needs to add developer app credentials. Manual checkout is available below.'
    : connection ? `Connected: ${connection.account} · Testnet payments only`
    : 'Connect your Testnet account. Wallet approval stays in Xaman.';
  el('buyer').readOnly = Boolean(connection);
  const matched = connection && order && connection.account === order.buyer;
  el('pay-xaman').disabled = !xamanEnabled || !matched || Boolean(activeRequest) || order?.status === 'paid';
  el('xaman-pay-hint').textContent = connection && order && !matched
    ? 'Connect the wallet shown under “Pay from” to pay for this reservation.'
    : 'Approve the Testnet payment in Xaman. Your ticket appears after ledger verification.';
}
function setConnection(value) {
  connection = {id: value.id, account: value.account};
  sessionStorage.setItem('xaman-connection', value.id);
  el('buyer').value = value.account;
  walletControls();
}
function stopWalletWatch() {
  if (walletSocket) { walletSocket.onclose = null; walletSocket.close(); walletSocket = null; }
  clearTimeout(verificationTimer);
}
function finishWalletRequest() {
  stopWalletWatch();
  activeRequest = null;
  sessionStorage.removeItem('xaman-request');
  el('xaman-qr').hidden = true;
  el('xaman-open').hidden = true;
  walletControls();
}
function showWalletRequest(value) {
  stopWalletWatch();
  activeRequest = value;
  verificationAttempts = 0;
  sessionStorage.setItem('xaman-request', value.id);
  el('xaman-request').hidden = false;
  if (value.kind === 'connect' && ['failed', 'uncertain'].includes(value.status)) {
    finishWalletRequest();
    el('xaman-status').textContent = value.message || 'Sign-in could not be started. Click Connect Xaman to try again.';
    return;
  }
  el('xaman-qr').hidden = !value.qr_url;
  el('xaman-open').hidden = !value.open_url;
  if (value.qr_url) el('xaman-qr').src = value.qr_url;
  if (value.open_url) el('xaman-open').href = value.open_url;
  el('xaman-status').textContent = value.status === 'uncertain'
    ? value.message || 'The request could not be confirmed. Check Xaman and use “Check wallet response” before paying again.'
    : value.kind === 'connect' ? 'Scan or open Xaman to approve sign-in.'
    : 'Scan or open Xaman to approve this Testnet payment.';
  walletControls();
  if (value.websocket_url) {
    walletSocket = new WebSocket(value.websocket_url);
    walletSocket.onopen = () => checkWallet();
    walletSocket.onmessage = event => {
      try {
        const signal = JSON.parse(event.data);
        // Notifications are only a trigger. The server fetches and verifies the real payload.
        if (typeof signal.signed === 'boolean' || signal.expired === true) checkWallet();
      } catch (_) { /* Ignore malformed notifications; manual status check remains available. */ }
    };
    walletSocket.onerror = () => {
      el('xaman-status').textContent = 'Live updates are unavailable. Approve in Xaman, then select “Check wallet response”.';
    };
  }
}
async function checkWallet() {
  if (!activeRequest || checkingWallet) return;
  checkingWallet = true;
  const requestId = activeRequest.id;
  try {
    const value = await api('xaman/status', {request_id: requestId});
    if (activeRequest?.id !== requestId) return;
    if (value.kind === 'connect' && ['failed', 'uncertain'].includes(value.status)) {
      finishWalletRequest();
      el('xaman-status').textContent = value.message || 'Sign-in failed. Click Connect Xaman to try again.';
    } else if (value.status === 'connected') {
      finishWalletRequest();
      setConnection(value);
      el('xaman-request').hidden = true;
    } else if (value.status === 'paid') {
      finishWalletRequest();
      el('xaman-request').hidden = true;
      showOrder(value.order);
    } else if (value.status === 'rejected' || value.status === 'cancelled') {
      finishWalletRequest();
      el('xaman-status').textContent = 'Request declined or cancelled. You can try again when ready.';
    } else if (value.status === 'expired') {
      stopWalletWatch();
      el('xaman-qr').hidden = true;
      el('xaman-open').hidden = true;
      el('xaman-status').textContent = 'Request expired. If you already opened it in Xaman, check its result before paying again.';
      // A payment opened before expiration can still be signed; do not create a replacement.
      if (value.kind === 'connect') finishWalletRequest();
    } else if (value.status === 'verifying') {
      el('xaman-status').textContent = value.message || 'Approved in Xaman. Waiting for ledger confirmation…';
      clearTimeout(verificationTimer);
      if (++verificationAttempts <= 20) verificationTimer = setTimeout(checkWallet, 5000);
    } else {
      el('xaman-status').textContent = value.message || 'Waiting for your approval in Xaman…';
    }
  } catch (error) { el('xaman-status').textContent = error.message; }
  finally { checkingWallet = false; walletControls(); }
}
async function restoreWalletRequest() {
  const id = sessionStorage.getItem('xaman-request');
  if (!id || !xamanEnabled || order?.status === 'paid') return;
  const value = await api('xaman/status', {request_id: id});
  if (value.kind === 'payment' && value.order_id !== order?.id) return;
  showWalletRequest(value);
  await checkWallet();
}
el('connect-xaman').onclick = () => busy(el('connect-xaman'), async () => {
  showWalletRequest(await api('xaman/connect', {}));
});
el('pay-xaman').onclick = () => busy(el('pay-xaman'), async () => {
  const value = await api('xaman/pay', {connection_id: connection.id, order_id: order.id});
  if (value.status === 'paid') showOrder(value.order);
  else showWalletRequest(value);
});
el('xaman-check').onclick = () => busy(el('xaman-check'), checkWallet);
window.addEventListener('beforeunload', stopWalletWatch);
init().catch(error => { el('message').textContent = error.message; });
