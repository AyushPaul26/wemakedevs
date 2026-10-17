/** Capture real Guided demo interactions into a silent MP4 using system ffmpeg. */
import { createRequire } from 'node:module';
import { mkdir, mkdtemp, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { signIn } from './browser-check.mjs';
import { runWorkflowBrowser } from './browser-workflow-live.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = require('playwright');
const frames = await mkdtemp(path.join(tmpdir(), 'relay-demo-'));
const destination = path.join(root, '.data/relay-demo.mp4');
await mkdir(path.dirname(destination), { recursive: true });
const legacy = process.env.RELAY_RECORD_LEGACY === '1';
const browser = legacy ? await chromium.launch({ executablePath: process.env.RELAY_BROWSER_EXECUTABLE || '/usr/bin/chromium', args: ['--no-sandbox'] }) : null;
let page = legacy ? await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 }) : null;
page?.setDefaultTimeout(20000);
let frame = 0;
async function show(seconds) {
  for (let i = 0; i < seconds * 4; i++) {
    await page.screenshot({ path: path.join(frames, `frame-${String(frame++).padStart(4, '0')}.jpg`), type: 'jpeg', quality: 85 });
    await page.waitForTimeout(150);
  }
}
if (!legacy) {
  await runWorkflowBrowser({ onScene: async (view, name) => {
    page = view;
    if (name.includes('scope')) {
      await page.locator('.approval-scope').scrollIntoViewIfNeeded(); await show(2);
      await page.getByRole('button', { name: 'Approve permitted work', exact: true }).scrollIntoViewIfNeeded(); await show(2);
    } else if (name.includes('followup')) {
      await page.locator('.assistant-message').last().scrollIntoViewIfNeeded(); await show(4);
    } else {
      if (await page.locator('.run-summary').count()) await page.locator('.run-summary').scrollIntoViewIfNeeded();
      await show(2);
      await page.getByRole('heading', { name: 'Reports and internal cases', exact: true }).scrollIntoViewIfNeeded(); await show(2);
    }
  } });
} else try {
  await signIn(page);
  await page.waitForFunction(() => document.querySelector('.impact-count strong')?.textContent === '3');
  await show(4);
  await page.locator('.ripple-card').scrollIntoViewIfNeeded();
  await show(4);
  await page.getByRole('switch', { name: /Assume backup is ready/ }).check();
  await page.waitForFunction(() => document.querySelector('.impact-count strong')?.textContent === '1');
  await page.getByText('Scenario assumptions', { exact: true }).click();
  await show(5);
  await page.locator('.ripple-evidence .source-link').first().click();
  await page.locator('.source-original').waitFor();
  await show(4);
  await page.keyboard.press('Escape');
  await page.getByRole('textbox', { name: 'Ask Relay a question' }).fill('Who owns the payment gateway?');
  await page.getByRole('button', { name: 'Send question' }).click();
  await page.getByText('Saved to company memory', { exact: true }).waitFor();
  await page.locator('.agent-steps summary').click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await show(5);
  await page.getByRole('link', { name: /^Actions/ }).click();
  const proposal = page.locator('.action-card').filter({ has: page.getByRole('button', { name: 'Approve task', exact: true }) }).first();
  await proposal.waitFor();
  await proposal.scrollIntoViewIfNeeded();
  await show(3);
  await proposal.getByRole('button', { name: 'Approve task', exact: true }).click();
  await show(3);
  await page.getByRole('link', { name: 'Memory', exact: true }).click();
  await page.locator('.memory-card').first().waitFor();
  await page.locator('.memory-card h2 button').first().click();
  await show(4);
} finally {
  await browser.close();
}
const result = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-framerate', '4', '-i', path.join(frames, 'frame-%04d.jpg'), '-vf', 'scale=1440:1080:force_original_aspect_ratio=decrease,pad=1440:1080:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1', '-filter_threads', '1', '-c:v', 'libx264', '-threads', '2', '-preset', 'fast', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', destination], { stdio: 'inherit' });
if (result.error || result.status !== 0) throw result.error || new Error(`ffmpeg exited ${result.status}`);
if (!(await stat(destination)).size) throw new Error('Recording is empty');
await rm(frames, { recursive: true, force: true });
console.log(`Recorded ${frame / 4}s of real interactions: ${destination}`);
