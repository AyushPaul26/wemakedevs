/** Real authenticated browser/API checks. No API responses are mocked. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const requireFrontend = createRequire(path.join(root, 'frontend/package.json'));
export const base = process.env.RELAY_BROWSER_URL || 'http://127.0.0.1:5173';
export async function credentials(role = 'operator') {
  let entry;
  const file = process.env.RELAY_BROWSER_CREDENTIALS_FILE;
  if (file) {
    const info = await stat(file);
    assert.equal(info.mode & 0o077, 0, 'Browser credential file must have mode 600 or stricter');
    try { entry = JSON.parse(await readFile(file, 'utf8'))[role]; }
    catch { throw new Error('Private browser credential file must contain valid account JSON'); }
  }
  const prefix = role === 'auditor' ? 'RELAY_BROWSER_AUDITOR_' : 'RELAY_BROWSER_';
  const username = process.env[`${prefix}USERNAME`] || entry?.username;
  const password = process.env[`${prefix}PASSWORD`] || entry?.password;
  assert.ok(username && password, `Provide ${role} credentials through environment variables or RELAY_BROWSER_CREDENTIALS_FILE`);
  return { username, password };
}
export async function signIn(page, role = 'operator') {
  const account = await credentials(role);
  await page.goto(base);
  await page.getByRole('heading', { name: 'Sign in to Relay' }).waitFor();
  // Never capture a screenshot, video frame, trace, or credential values here.
  let stage = 'username entry';
  let loginStatus;
  page.on('response', response => { if (new URL(response.url()).pathname === '/api/auth/login') loginStatus = response.status(); });
  try {
    await page.getByLabel('Username', { exact: true }).fill(account.username);
    stage = 'password entry';
    await page.getByLabel('Password', { exact: true }).fill(account.password);
    stage = 'sign-in submission';
    const loginResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/auth/login');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    assert.equal((await loginResponse).status(), 200, 'Sign-in must succeed');
    stage = 'authenticated workspace';
    await page.getByRole('button', { name: 'Sign out', exact: true }).waitFor();
  } catch {
    throw new Error(`Sign-in failed for the ${role} test account at ${stage}; login HTTP status ${loginStatus ?? 'not received'}`);
  }
  const response = await page.request.get(`${base}/api/auth/session`);
  assert.equal(response.status(), 200, 'Authenticated session must be available');
  const session = await response.json();
  // Return only the non-secret identity; keep the CSRF token in the app's memory.
  return session.member;
}
export async function launchBrowser() {
  const { chromium } = requireFrontend('playwright');
  return chromium.launch({ executablePath: process.env.RELAY_BROWSER_EXECUTABLE || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
}
export async function runBrowserChecks() {
  const { default: AxeBuilder } = requireFrontend('@axe-core/playwright');
  const output = path.join(root, '.data/screenshots');
  await mkdir(output, { recursive: true });
  const browser = await launchBrowser();
  const context = await browser.newContext({ viewport: { width: 1512, height: 1080 }, locale: 'en-US' });
  const page = await context.newPage();
  page.setDefaultTimeout(25000);
  const checks = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = async (name, run) => { await run(); checks.push(name); console.log(`PASS ${name}`); };
  const waitRipple = value => page.waitForFunction(expected => document.querySelector('.impact-count strong')?.textContent === expected, value);
  const closeDialog = async () => { await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'hidden' }); };
  const noOverflow = async () => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1), 'Page must not overflow');
  async function accessibility(label) {
    const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
    await writeFile(path.join(output, `axe-${label}.json`), JSON.stringify(result, null, 2));
    assert.deepEqual(result.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) })), []);
  }
  try {
    await check('real session sign-in, database graph and baseline Ripple', async () => {
      await signIn(page);
      await page.getByRole('heading', { name: 'Your company, connected.' }).waitFor();
      await waitRipple('3');
      assert.equal(await page.locator('.react-flow__node').count(), 10);
      await noOverflow();
      await page.screenshot({ path: path.join(output, 'relay-overview.png'), fullPage: true });
    });
    await check('backup assumption reduces exposure while billing remains', async () => {
      await page.getByRole('switch', { name: /Assume backup is ready/ }).check();
      await waitRipple('1');
      assert.match(await page.locator('.impact-paths').innerText(), /Billing reconciliation/);
      await page.screenshot({ path: path.join(output, 'relay-ripple.png'), fullPage: true });
      await page.getByRole('switch', { name: /Assume backup is ready/ }).uncheck();
      await waitRipple('3');
    });
    await check('keyboard graph evidence and focus restoration', async () => {
      await page.getByText('Browse map entities', { exact: true }).click();
      const entity = page.getByRole('button', { name: 'Payment gateway', exact: true });
      await entity.focus(); await page.keyboard.press('Enter');
      await page.getByRole('dialog').waitFor();
      assert.match(await page.getByRole('dialog').innerText(), /Devon Park/);
      await closeDialog();
      await page.waitForFunction(() => document.activeElement?.textContent?.trim() === 'Payment gateway');
      assert.equal(await entity.evaluate(node => node === document.activeElement), true);
    });
    const question = 'What happens to the Atlas launch if payments fail?';
    await check('real investigation, citations and three agent handoffs', async () => {
      await page.getByRole('textbox', { name: 'Ask Relay a question' }).fill(question);
      await page.getByRole('button', { name: 'Send question' }).click();
      await page.getByText('Saved to company memory', { exact: true }).waitFor();
      assert.match(await page.locator('.assistant-message').last().innerText(), /Checkout.*Atlas launch/s);
      await page.locator('.agent-steps summary').last().click();
      assert.equal(await page.locator('.agent-steps').last().locator('li').count(), 3);
      await page.locator('.assistant-message .source-link').first().click();
      await page.locator('.source-original').first().waitFor();
      assert.match(await page.getByRole('dialog').innerText(), /FICTIONAL MERIDIAN SAMPLE/);
      await closeDialog();
    });
    await check('manual task approval and completion persist through real CSRF-protected API', async () => {
      await page.getByRole('link', { name: /^Actions/ }).click();
      const proposal = page.locator('.action-card').filter({ has: page.getByRole('button', { name: 'Approve task', exact: true }) }).first();
      await proposal.waitFor();
      const title = await proposal.locator('h3').innerText();
      const index = await proposal.evaluate(node => [...document.querySelectorAll('.action-card')].indexOf(node));
      await proposal.getByRole('button', { name: 'Approve task', exact: true }).click();
      const selected = page.locator('.action-card').nth(index);
      await selected.getByRole('button', { name: 'Mark complete', exact: true }).click();
      await selected.getByText('Complete', { exact: true }).waitFor();
      const response = await page.request.get(`${base}/api/actions`);
      assert.equal(response.status(), 200);
      assert.ok((await response.json()).items.some(item => item.title === title && item.status === 'done'));
    });
    await check('saved investigation survives reload', async () => {
      await page.getByRole('link', { name: 'Memory', exact: true }).click();
      await page.reload();
      await page.locator('.memory-card h2').filter({ hasText: question }).first().click();
      assert.match(await page.getByRole('dialog').innerText(), /Payment gateway/);
      await closeDialog();
    });
    await check('note validation, preserved draft, real storage and metadata search', async () => {
      await page.getByRole('button', { name: 'Add knowledge', exact: true }).click();
      await page.getByRole('button', { name: 'Save source', exact: true }).click();
      const title = page.getByRole('textbox', { name: 'Source title', exact: true });
      assert.equal(await title.getAttribute('aria-invalid'), 'true');
      assert.equal(await title.evaluate(node => node === document.activeElement), true);
      const uniqueTitle = `Browser demo note ${Date.now()}`;
      await title.fill(uniqueTitle);
      await page.getByRole('textbox', { name: 'Content', exact: true }).fill('Fictional demo: keep Billing reconciliation under review after checkout failover.');
      await closeDialog();
      await page.getByRole('button', { name: 'Add knowledge', exact: true }).click();
      assert.equal(await title.inputValue(), uniqueTitle);
      await page.getByRole('button', { name: 'Save source', exact: true }).click();
      await page.getByRole('dialog').waitFor({ state: 'hidden' });
      await page.getByRole('link', { name: 'Knowledge', exact: true }).click();
      await page.getByRole('searchbox', { name: 'Search knowledge' }).fill(uniqueTitle);
      await page.getByRole('button', { name: uniqueTitle, exact: true }).click();
      await page.locator('.source-original').waitFor();
      assert.match(await page.locator('.source-original').innerText(), /Billing reconciliation/);
      await closeDialog();
      await page.getByRole('searchbox', { name: 'Search knowledge' }).fill('no-matching-source-938192');
      await page.getByRole('heading', { name: 'No matching sources' }).waitFor();
      await page.getByRole('button', { name: 'Clear knowledge search' }).click();
    });
    await check('desktop accessibility and layout', async () => {
      await page.getByRole('link', { name: 'Overview', exact: true }).click();
      await waitRipple('3'); await accessibility('desktop'); await noOverflow();
    });
    await check('mobile layout, reduced motion and accessible note dialog', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await noOverflow();
      await page.screenshot({ path: path.join(output, 'relay-mobile.png'), fullPage: true });
      await page.getByRole('button', { name: 'Add knowledge', exact: true }).click();
      const box = await page.getByRole('dialog').boundingBox();
      assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.width <= 391 && box.y + box.height <= 845);
      await accessibility('mobile-dialog'); await closeDialog();
    });
    await check('sign-out removes the scoped workspace', async () => {
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await page.getByRole('heading', { name: 'Sign in to Relay' }).waitFor();
      assert.equal(await page.locator('.react-flow__node').count(), 0);
    });
    assert.deepEqual(errors, [], 'Uncaught browser exceptions');
    await writeFile(path.join(output, 'browser-results.json'), JSON.stringify({ kind: 'real-authenticated-browser-api', checks, errors, passed: true }, null, 2));
    console.log(`${checks.length} real browser workflows passed.`);
  } catch (error) {
    await writeFile(path.join(output, 'browser-results.json'), JSON.stringify({ kind: 'real-authenticated-browser-api', checks, errors, passed: false, failure: String(error) }, null, 2));
    // No failure screenshot: login fields may still contain credentials.
    throw error;
  } finally { await browser.close(); }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await runBrowserChecks();
