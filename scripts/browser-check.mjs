/** Real UI workflows, bounded failure injection, and accessibility checks. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = require('playwright');
const { default: AxeBuilder } = require('@axe-core/playwright');
const output = path.join(root, '.data/screenshots');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.RELAY_BROWSER_EXECUTABLE || '/usr/bin/chromium',
  headless: true,
  args: ['--no-sandbox'],
});
const context = await browser.newContext({ viewport: { width: 1512, height: 1080 }, locale: 'en-US' });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const base = process.env.RELAY_BROWSER_URL || 'http://127.0.0.1:5173';
const checks = [];
const errors = [];
page.on('pageerror', error => errors.push(error.message));
async function check(name, run) { await run(); checks.push(name); console.log(`PASS ${name}`); }
async function waitRipple(value) {
  await page.waitForFunction(expected => document.querySelector('.impact-count strong')?.textContent === expected, value);
}
async function closeDialog() { await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'hidden' }); }
async function noPageOverflow() {
  const size = await page.evaluate(() => ({ width: document.documentElement.clientWidth, content: document.documentElement.scrollWidth }));
  assert.ok(size.content <= size.width + 1, `Page overflows: ${JSON.stringify(size)}`);
}
async function accessibility(label) {
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  await writeFile(path.join(output, `axe-${label}.json`), JSON.stringify(result, null, 2));
  assert.deepEqual(result.violations.map(item => ({ id: item.id, impact: item.impact, nodes: item.nodes.map(n => n.target) })), []);
}

try {
  await check('real database graph and baseline Ripple', async () => {
    await page.goto(base);
    await page.getByRole('heading', { name: 'Your company, connected.' }).waitFor();
    await waitRipple('3');
    assert.equal(await page.locator('.react-flow__node').count(), 10);
    await noPageOverflow();
    await page.screenshot({ path: path.join(output, 'relay-overview.png'), fullPage: true });
  });
  await check('backup assumption reduces exposure without hiding billing', async () => {
    await page.route('**/api/ripple', async route => {
      await new Promise(resolve => setTimeout(resolve, 350));
      await route.continue();
    }, { times: 1 });
    await page.getByRole('switch', { name: /Assume backup is ready/ }).check();
    await page.getByText('Tracing dependencies through the company graph…', { exact: true }).waitFor();
    await waitRipple('1');
    assert.match(await page.locator('.impact-paths').innerText(), /Billing reconciliation/);
    await page.screenshot({ path: path.join(output, 'relay-ripple.png'), fullPage: true });
    await page.getByRole('switch', { name: /Assume backup is ready/ }).uncheck();
    await waitRipple('3');
  });
  await check('late scenario response cannot replace the current selection', async () => {
    await page.route('**/api/ripple', async route => {
      if (route.request().postDataJSON().mitigation) await new Promise(resolve => setTimeout(resolve, 600));
      await route.continue();
    }, { times: 2 });
    const lateResponse = page.waitForResponse(response => response.url().endsWith('/api/ripple') && response.request().postDataJSON().mitigation);
    await page.getByRole('switch', { name: /Assume backup is ready/ }).check();
    await page.getByText('Tracing dependencies through the company graph…', { exact: true }).waitFor();
    await page.getByRole('switch', { name: /Assume backup is ready/ }).uncheck();
    await waitRipple('3');
    await lateResponse;
    await page.evaluate(() => new Promise(requestAnimationFrame));
    assert.equal(await page.locator('.impact-count strong').innerText(), '3');
  });
  await check('keyboard graph evidence and dialog focus restoration', async () => {
    await page.getByText('Browse map entities', { exact: true }).click();
    const entity = page.getByRole('button', { name: 'Payment gateway', exact: true });
    await entity.focus();
    await page.keyboard.press('Enter');
    await page.getByRole('dialog').waitFor();
    assert.match(await page.getByRole('dialog').innerText(), /Devon Park/);
    await closeDialog();
    assert.equal(await entity.evaluate(node => node === document.activeElement), true);
  });
  const question = 'What happens to the Atlas launch if payments fail?';
  await check('investigation runs with citations and three agent handoffs', async () => {
    const input = page.getByRole('textbox', { name: 'Ask Relay a question' });
    await input.fill(question);
    await page.getByRole('button', { name: 'Send question' }).click();
    await page.getByText('Saved to company memory', { exact: true }).waitFor();
    assert.match(await page.locator('.assistant-message').innerText(), /Checkout.*Atlas launch/s);
    await page.locator('.agent-steps summary').click();
    assert.equal(await page.locator('.agent-steps li').count(), 3);
    await page.locator('.assistant-message .source-link').first().click();
    await page.locator('.source-original').waitFor();
    assert.match(await page.locator('.source-original').innerText(), /FICTIONAL MERIDIAN SAMPLE/);
    await closeDialog();
  });
  await check('approval then completion persists in the real API', async () => {
    await page.getByRole('link', { name: /^Actions/ }).click();
    const proposal = page.locator('.action-card').filter({ has: page.getByRole('button', { name: 'Approve task', exact: true }) }).first();
    await proposal.waitFor();
    const cardIndex = await proposal.evaluate(node => [...document.querySelectorAll('.action-card')].indexOf(node));
    const selected = page.locator('.action-card').nth(cardIndex);
    const title = await proposal.locator('h3').innerText();
    await selected.getByRole('button', { name: 'Approve task', exact: true }).click();
    await selected.getByRole('button', { name: 'Mark complete', exact: true }).click();
    await selected.getByText('Complete', { exact: true }).waitFor();
    const response = await page.request.get(`${base}/api/actions`);
    assert.ok((await response.json()).items.some(item => item.title === title && item.status === 'done'));
  });
  await check('saved investigation survives reload', async () => {
    await page.getByRole('link', { name: 'Memory', exact: true }).click();
    await page.reload();
    await page.locator('.memory-card h2').filter({ hasText: question }).first().waitFor();
    await page.locator('.memory-card h2').filter({ hasText: question }).first().click();
    await page.getByRole('dialog').waitFor();
    assert.match(await page.getByRole('dialog').innerText(), /Payment gateway/);
    await closeDialog();
  });
  await check('note validation, preserved draft, storage, and search', async () => {
    await page.getByRole('button', { name: 'Add knowledge', exact: true }).click();
    await page.getByRole('button', { name: 'Save source', exact: true }).click();
    const title = page.getByRole('textbox', { name: 'Source title', exact: true });
    assert.equal(await title.getAttribute('aria-invalid'), 'true');
    assert.equal(await title.evaluate(node => node === document.activeElement), true);
    const uniqueTitle = `Browser review ${Date.now()}`;
    await title.fill(uniqueTitle);
    await page.getByRole('textbox', { name: 'Content', exact: true }).fill('Keep Billing reconciliation under review after checkout failover.');
    await closeDialog();
    await page.getByRole('button', { name: 'Add knowledge', exact: true }).click();
    assert.equal(await title.inputValue(), uniqueTitle);
    await page.route('**/api/sources', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Source storage unavailable. Retry.' }) }), { times: 1 });
    await page.getByRole('button', { name: 'Save source', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Source storage unavailable' }).waitFor();
    assert.equal(await title.inputValue(), uniqueTitle);
    await page.getByRole('button', { name: 'Save source', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    await page.getByRole('searchbox', { name: 'Search knowledge' }).fill(uniqueTitle);
    await page.getByRole('button', { name: uniqueTitle, exact: true }).click();
    await page.locator('.source-original').waitFor();
    assert.match(await page.locator('.source-original').innerText(), /Billing reconciliation/);
    await closeDialog();
    await page.getByRole('searchbox', { name: 'Search knowledge' }).fill('no-matching-source-938192');
    await page.getByRole('heading', { name: 'No matching sources' }).waitFor();
    await page.getByRole('button', { name: 'Clear knowledge search' }).click();
  });
  await check('investigation failure preserves question and retry works', async () => {
    const input = page.getByRole('textbox', { name: 'Ask Relay a question' });
    await input.fill('Who owns the payment gateway?');
    await page.route('**/api/investigate', route => route.fulfill({ status: 502, contentType: 'application/json', body: JSON.stringify({ detail: 'Model unavailable. Retry.' }) }), { times: 1 });
    await page.getByRole('button', { name: 'Send question' }).click();
    await page.getByRole('alert').filter({ hasText: 'Model unavailable' }).waitFor();
    assert.equal(await input.inputValue(), 'Who owns the payment gateway?');
    await page.getByRole('button', { name: 'Send question' }).click();
    await page.getByText('Saved to company memory', { exact: true }).waitFor();
    assert.match(await page.locator('.assistant-message').innerText(), /Devon Park/);
  });
  await check('desktop accessibility and layout', async () => {
    await page.getByRole('link', { name: 'Overview', exact: true }).click();
    await waitRipple('3');
    await accessibility('desktop');
    await noPageOverflow();
  });
  await check('mobile layout, reduced motion, and accessible dialog', async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await noPageOverflow();
    await page.screenshot({ path: path.join(output, 'relay-mobile.png'), fullPage: true });
    await page.getByRole('button', { name: 'Add knowledge', exact: true }).click();
    const box = await page.getByRole('dialog').boundingBox();
    assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.width <= 391 && box.y + box.height <= 845);
    await accessibility('mobile-dialog');
    await closeDialog();
  });
  await check('bootstrap error remains recoverable', async () => {
    await page.route('**/api/bootstrap', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'FalkorDB is unavailable. Start the database and retry.' }) }));
    await page.reload();
    await page.getByRole('alert').filter({ hasText: 'FalkorDB is unavailable' }).waitFor();
    await page.unroute('**/api/bootstrap');
    await page.getByRole('button', { name: 'Reconnect', exact: true }).click();
    await waitRipple('3');
  });
  assert.deepEqual(errors, [], 'Uncaught browser exceptions');
  await writeFile(path.join(output, 'browser-results.json'), JSON.stringify({ checks, errors, passed: true }, null, 2));
  console.log(`${checks.length} browser workflows passed.`);
} catch (error) {
  await writeFile(path.join(output, 'browser-results.json'), JSON.stringify({ checks, errors, passed: false, failure: String(error) }, null, 2));
  try {
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true, timeout: 5000 });
  } catch (screenshotError) {
    console.error('Failure screenshot unavailable:', screenshotError.message);
  }
  throw error;
} finally {
  await browser.close();
}
