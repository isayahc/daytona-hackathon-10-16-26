// Regression checks for the actual browser script; no network or real wallet.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function browser(savedRequest = null) {
  const elements = new Map();
  const storage = new Map(savedRequest ? [['xaman-request', savedRequest]] : []);
  const element = id => {
    if (!elements.has(id)) elements.set(id, {value: '', hidden: false, disabled: false,
      textContent: '', replaceChildren() {}, append() {}});
    return elements.get(id);
  };
  const failed = {id: 'failed-connect', kind: 'connect', status: 'failed', message: 'Could not reach Xaman.'};
  const context = vm.createContext({
    document: {getElementById: element, createElement: () => ({})},
    sessionStorage: {getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k)},
    location: {hash: ''}, history: {replaceState() {}}, URLSearchParams,
    navigator: {clipboard: {writeText: async () => {}}},
    window: {addEventListener() {}}, setTimeout: () => 1, clearTimeout() {},
    WebSocket: class {close() {}},
    fetch: async url => ({ok: true, json: async () => {
      if (url.endsWith('/xaman/config')) return {enabled: true};
      if (url.endsWith('/events')) return {events: []};
      if (url.endsWith('/xaman/connect') || url.endsWith('/xaman/status')) return failed;
      throw new Error(`Unexpected request: ${url}`);
    }})
  });
  await vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/tickets.js'), 'utf8'), context);
  return {context, element, storage};
}

(async () => {
  const fresh = await browser();
  await fresh.element('connect-xaman').onclick();
  assert.equal(fresh.element('connect-xaman').disabled, false, 'Failed sign-in must allow retry');
  assert.equal(fresh.element('xaman-status').textContent, 'Could not reach Xaman.');
  assert.equal(fresh.storage.has('xaman-request'), false);
  assert.equal(fresh.element('xaman-check').disabled, true, 'No status check for an unrecoverable sign-in');

  const restored = await browser('old-uncertain-connect');
  assert.equal(restored.element('connect-xaman').disabled, false, 'Reloading an old failed sign-in must unlock Connect');
  assert.equal(restored.storage.has('xaman-request'), false);

  vm.runInContext(`showWalletRequest({id:'payment',kind:'payment',status:'uncertain',message:'Check payment status.'})`, fresh.context);
  assert.equal(fresh.element('connect-xaman').disabled, true, 'Uncertain payments must remain protected');
  assert.equal(fresh.element('xaman-check').disabled, false);
  assert.equal(fresh.storage.get('xaman-request'), 'payment');
  console.log('Wallet UI regression checks passed: failed sign-in retry, saved-session recovery, and uncertain payment protection.');
})().catch(error => { console.error(error); process.exitCode = 1; });
