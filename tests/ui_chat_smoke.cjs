/* Browser check with a real local server and mocked paid-agent API responses.
 * Install Playwright, then run: node tests/ui_chat_smoke.cjs
 */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {mkdtempSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'event-chat-'));
  const server = spawn(process.env.PYTHON || 'python3', ['-m','operator_app.server','--port','0','--database',path.join(dir,'workspace.sqlite3')], {cwd:path.resolve(__dirname,'..')});
  let browser;
  try {
    const url = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Server startup timed out')), 10000);
      server.on('error', error => {clearTimeout(timer); reject(error);});
      server.on('exit', code => {clearTimeout(timer); reject(new Error(`Server exited: ${code}`));});
      server.stdout.on('data', chunk => {
        const match = chunk.toString().match(/http:\/\/127\.0\.0\.1:\d+/);
        if (match) {clearTimeout(timer); resolve(match[0]);}
      });
    });
    browser = await chromium.launch({headless:true});
    const page = await browser.newPage({viewport:{width:1440,height:1080}});
    const errors = [], runs = new Map();
    let polls = 0;
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/chat?*', route => {
      const id = new URL(route.request().url()).searchParams.get('event_id');
      const entries = runs.get(id) || [];
      if (entries[0]?.status === 'running' && ++polls > 1) entries[0].status = 'completed';
      return route.fulfill({json:{runs:entries}});
    });
    await page.route('**/api/chat', route => {
      const body = route.request().postDataJSON();
      if (body.prompt === 'Missing configuration') return route.fulfill({status:503,json:{error:'Configure model-provider credentials in .env.'}});
      const run = {id:'run-1',event_id:body.event_id,prompt:body.prompt,status:'running',reply:'Drafted the party messages.',drafts:['venues','sponsors','catering','contacts'].map(role => ({id:role,target:{role,name:`${role} recipient`,is_mock:false},subject:`Hello ${role}`,body:'Could you help with our event?'}))};
      runs.set(body.event_id, [run]);
      return route.fulfill({status:202,json:run});
    });
    await page.route('**/api/message-drafts', route => {
      const body = route.request().postDataJSON();
      const draft = [...runs.values()].flatMap(entries => entries[0].drafts).find(d => d.id === body.draft_id);
      Object.assign(draft, {subject:body.subject,body:body.body,edited:true});
      return route.fulfill({json:draft});
    });
    await page.goto(url);
    await page.waitForFunction(() => !document.querySelector('#chat-submit').disabled);
    assert.equal(await page.locator('#event-chat').getAttribute('open'), null);
    await page.locator('#event-chat > summary').click();
    await page.locator('#chat-prompt').fill('Missing configuration');
    await page.locator('#chat-submit').click();
    await page.getByText('Configure model-provider credentials in .env.', {exact:true}).waitFor();
    await page.locator('#chat-prompt').fill('Organize a repair day <script>bad()</script>');
    await page.locator('#chat-submit').click();
    await page.getByText('Agent drafting…', {exact:true}).waitFor();
    await page.locator('.message-draft').first().waitFor();
    assert.equal(await page.locator('.message-draft').count(), 4);
    assert.equal(await page.locator('#chat-history script').count(), 0);
    await page.locator('#view-drafts').click();
    const first = page.locator('.message-draft').first();
    await first.locator('[name=body]').fill('Please donate tools for our repair day.');
    await first.getByRole('button',{name:'Save edits'}).click();
    await first.getByText('Edits saved locally').waitFor();
    await page.reload();
    await page.locator('.message-draft').first().waitFor();
    assert.equal(await page.locator('.message-draft [name=body]').first().inputValue(), 'Please donate tools for our repair day.');
    const ids = await page.locator('#event-select option').evaluateAll(options => options.map(o => o.value));
    await page.locator('#event-select').selectOption(ids[1]);
    await page.getByText('Open Event chat to create your first messages.', {exact:true}).waitFor();
    assert.equal(await page.locator('.message-draft').count(), 0);
    await page.locator('#event-select').selectOption(ids[0]);
    await page.locator('.message-draft').first().waitFor();
    await page.setViewportSize({width:390,height:844});
    await page.locator('#event-chat > summary').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log('PASS: collapse, configuration error, async generation, party routing, editing, reload, event switching, mobile layout');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    await new Promise(resolve => server.exitCode !== null ? resolve() : server.once('exit', resolve));
    rmSync(dir, {recursive:true,force:true});
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
