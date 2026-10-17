/** Live, two-member invoice review. Every API call reaches the real backend.
 * Creates labeled demo evidence/runs, records explicit test approvals, and replaces
 * only the source created by this execution. Never use against production data.
 */
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { base, root, launchBrowser, signIn, requireFrontend } from './browser-check.mjs';

export async function runWorkflowBrowser({ onScene = async () => {} } = {}) {
  const output = path.join(root, '.data/workflow-browser-live');
  await mkdir(output, { recursive: true });
  const browser = await launchBrowser();
  const operator = await browser.newContext({ viewport: { width: 1440, height: 1080 }, locale: 'en-US', acceptDownloads: true });
  const auditor = await browser.newContext({ viewport: { width: 1440, height: 1080 }, locale: 'en-US' });
  const page = await operator.newPage(), audit = await auditor.newPage();
  for (const view of [page, audit]) view.setDefaultTimeout(30000);
  const checks = [], errors = [], scenes = [];
  let runId, invoiceRef;
  for (const view of [page, audit]) view.on('pageerror', error => errors.push(error.message));
  const scene = async (view, name) => {
    assert.equal(await view.getByRole('heading', { name: 'Sign in to Relay' }).count(), 0, 'Never capture sign-in credentials');
    await view.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
    scenes.push(name); await onScene(view, name);
  };
  const check = name => { checks.push(name); console.log(`PASS ${name}`); };
  async function json(view, url) {
    const response = await view.request.get(`${base}/api${url}`);
    assert.equal(response.status(), 200, `GET ${url}`);
    return response.json();
  }
  async function poll(predicate, description) {
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      const run = await json(page, `/workflow-runs/${runId}`);
      if (predicate(run)) return run;
      assert.ok(!['failed', 'cancelled', 'rejected'].includes(run.status), `${description}: unexpected ${run.status}`);
      await page.waitForTimeout(500);
    }
    throw new Error(`Timed out: ${description}`);
  }
  async function pick(label, title) {
    const group = page.getByRole('group', { name: label, exact: true });
    await group.getByRole('searchbox').fill(title);
    await group.getByRole('radio', { name: new RegExp(title) }).check();
  }
  async function approve(view, approval, reason) {
    await view.goto(`${base}/#approvals/${encodeURIComponent(approval.id)}`);
    const card = view.locator('.approval-card').filter({ has: view.getByRole('link', { name: runId, exact: true }) });
    await card.getByLabel('Decision reason').fill(reason);
    await scene(view, `${scenes.length + 1}-${approval.gate_kind}-scope`);
    await card.getByRole('button', { name: 'Approve permitted work', exact: true }).click();
    await card.getByRole('button', { name: 'Approve permitted work', exact: true }).waitFor({ state: 'hidden' });
  }
  try {
    const member = await signIn(page), reviewer = await signIn(audit, 'auditor');
    assert.notEqual(member.id, reviewer.id);
    assert.equal(reviewer.role, 'finance_auditor');
    check('separate operator and Finance auditor sessions authenticate through real UI');
    const suffix = Date.now();
    const invoiceName = `DEMO-invoice-${suffix}.csv`, orderName = `DEMO-order-${suffix}.csv`;
    await page.getByRole('link', { name: 'Knowledge', exact: true }).click();
    await page.getByRole('button', { name: 'Upload files', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Files', { exact: true }).setInputFiles([
      { name: invoiceName, mimeType: 'text/csv', buffer: await readFile(path.join(root, 'backend/tests/fixtures/invoices/invoice.csv')) },
      { name: orderName, mimeType: 'text/csv', buffer: await readFile(path.join(root, 'backend/tests/fixtures/invoices/purchase-order.csv')) },
    ]);
    await dialog.getByLabel('Classification and department').selectOption('finance');
    const uploadResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/attachments' && response.request().method() === 'POST');
    await dialog.getByRole('button', { name: 'Upload files', exact: true }).click();
    const uploadedResponse = await uploadResponse;
    assert.equal(uploadedResponse.status(), 201);
    const uploaded = await uploadedResponse.json();
    assert.equal(uploaded.items.length, 2);
    assert.ok(uploaded.items.every(item => !item.error && (item.processing_status || item.status) === 'waiting_approval'));
    invoiceRef = uploaded.items[0].ref || uploaded.items[0].source_ref;
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
    check('real multipart Finance upload creates two protected immutable versions');
    await page.getByRole('link', { name: 'Workflows', exact: true }).click();
    await page.getByRole('button', { name: 'New invoice review', exact: true }).click();
    await pick('Invoice', invoiceName); await pick('Purchase order', orderName);
    await page.getByLabel('Output audience member IDs').fill(`${member.id}, ${reviewer.id}`);
    await page.getByLabel('Output automation').selectOption('review_changes');
    const creation = page.waitForResponse(response => new URL(response.url()).pathname === '/api/workflow-runs' && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Start review', exact: true }).click();
    const created = await creation;
    assert.equal(created.status(), 202); runId = (await created.json()).id;
    assert.ok(runId);
    let run = await poll(run => run.steps.find(step => step.logical_key === 'company_context')?.status === 'completed', 'company branch completes before Finance approval');
    assert.equal(run.steps.find(step => step.logical_key === 'finance_parse').status, 'waiting_approval');
    assert.equal(run.steps.filter(step => step.execution).length, 1);
    assert.equal(run.outputs.length, 0);
    await page.getByRole('heading', { name: 'Persisted workflow state' }).waitFor();
    await scene(page, 'company-complete-finance-waiting');
    assert.equal(await page.getByRole('button', { name: 'Approve permitted work', exact: true }).count(), 0);
    check('persisted independent company branch completes while protected Finance branch waits');
    const finance = run.approvals.find(item => item.gate_kind === 'finance_access' && item.status === 'pending');
    assert.equal(finance.reviewer_id, reviewer.id);
    await approve(audit, finance, 'Authorized fictional demo: inspect these exact CSV versions for this test run only.');
    check('assigned Finance auditor explicitly approves the displayed exact scope');
    for (const kind of ['report_write', 'case_write']) {
      run = await poll(run => run.approvals.some(item => item.gate_kind === kind && item.status === 'pending'), `requester ${kind} review`);
      const outputGate = run.approvals.find(item => item.gate_kind === kind && item.status === 'pending');
      assert.equal(outputGate.reviewer_id, member.id);
      if (kind === 'report_write') assert.equal(run.outputs.length, 0);
      await approve(page, outputGate, `Authorized fictional demo: permit the displayed internal ${kind} changes.`);
    }
    check('requester separately reviews actual proposed report and case changes before publication');
    run = await poll(run => run.status === 'completed', 'six real tool executions complete');
    assert.equal(run.steps.length, 6);
    assert.equal(run.steps.filter(step => step.execution?.status === 'completed').length, 6);
    assert.equal(new Set(run.steps.map(step => step.execution.id)).size, 6);
    assert.ok(run.steps.every(step => step.execution.input_hash));
    assert.equal(run.outputs.length, 2); assert.equal(run.cases.length, 1);
    assert.equal(run.steps.find(step => step.logical_key === 'invoice_compare').result.comparison.difference, '20.00');
    const timeline = await json(page, `/workflow-runs/${runId}/timeline`);
    assert.ok(timeline.items.length > 0, 'Actual decisions and executions persist in timeline');
    await page.goto(`${base}/#workflows/${runId}`);
    await page.getByRole('button', { name: 'Download report', exact: true }).first().waitFor();
    assert.equal(await page.locator('.execution-receipt').count(), 6);
    for (let index = 0; index < 2; index++) {
      const downloadEvent = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download report', exact: true }).nth(index).click();
      const download = await downloadEvent;
      assert.equal(await download.failure(), null);
      const destination = path.join(output, `report-${index}-${download.suggestedFilename()}`);
      await download.saveAs(destination); assert.ok((await readFile(destination)).length > 0);
    }
    await page.getByRole('button', { name: 'View case', exact: true }).click();
    await page.getByRole('heading', { name: 'Current case revision' }).waitFor();
    await page.keyboard.press('Escape');
    await scene(page, 'completed-six-receipts-two-reports-case');
    check('six immutable execution receipts, two real downloadable reports and persisted internal case');
    await page.getByRole('button', { name: 'Ask about this run', exact: true }).click();
    const followupResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/investigate' && response.request().method() === 'POST');
    await page.getByRole('textbox', { name: 'Ask Relay a question' }).fill('What discrepancy did this invoice review find, what did it create, and does it prove a launch blocker?');
    await page.getByRole('button', { name: 'Send question', exact: true }).click();
    const answerResponse = await followupResponse;
    assert.equal(answerResponse.status(), 200);
    const answer = await answerResponse.json();
    assert.ok(answer.answer && answer.answer.length > 30);
    assert.deepEqual(new Set(answer.output_ids || []), new Set(run.outputs.map(item => item.id)), 'Follow-up cites the actual permitted reports');
    if (answer.mode === 'demo') {
      assert.match(answer.answer, /20\.00 USD/);
      assert.match(answer.answer, /does not establish a launch blocker/);
    }
    const memories = await json(page, '/memory');
    assert.ok(memories.items.some(item => item.id === answer.id), 'Follow-up persists as real memory');
    const submitted = answerResponse.request().postDataJSON();
    assert.equal(submitted.workflow_run_id || submitted.run_id, runId);
    await page.getByText('Saved to company memory', { exact: true }).waitFor();
    await scene(page, 'stored-run-followup');
    check('run-scoped follow-up reaches real investigation API and archives source-backed memory');
    await page.getByRole('link', { name: 'Knowledge', exact: true }).click();
    await page.getByRole('searchbox', { name: 'Search knowledge' }).fill(invoiceName);
    await page.getByRole('button', { name: invoiceName, exact: true }).click();
    await page.getByLabel('Replace with a new immutable version').setInputFiles({ name: `DEMO-corrected-${suffix}.csv`, mimeType: 'text/csv', buffer: Buffer.from('item_id,quantity,unit_price,currency\ngateway-seat,2,100.00,USD\n') });
    await page.getByRole('button', { name: 'Save new version', exact: true }).click();
    await page.getByText(/New version saved/).waitFor();
    await page.keyboard.press('Escape');
    run = await poll(run => run.status === 'stale', 'source version replacement invalidates dependent work');
    const previousCompany = run.steps.find(step => step.logical_key === 'company_context').execution.id;
    await page.goto(`${base}/#workflows/${runId}`);
    await page.getByRole('button', { name: 'Revise inputs and plan', exact: true }).click();
    await pick('Invoice', invoiceName);
    await page.getByLabel('Output automation').selectOption('auto_permitted');
    await page.getByRole('button', { name: 'Save revised plan', exact: true }).click();
    run = await poll(run => run.generation === 2 && run.approvals.some(item => item.gate_kind === 'finance_access' && item.status === 'pending'), 'new generation requires fresh Finance approval');
    assert.equal(run.steps.find(step => step.logical_key === 'company_context').execution.id, previousCompany);
    assert.equal(run.steps.find(step => step.logical_key === 'company_context').reused, true);
    const newFinance = run.approvals.find(item => item.gate_kind === 'finance_access' && item.status === 'pending');
    assert.notEqual(newFinance.id, finance.id); assert.notEqual(newFinance.scope_hash, finance.scope_hash);
    await scene(page, 'revised-input-fresh-approval-company-reused');
    check('corrected price 100 creates a new version, stales old work and reuses unaffected company receipt');
    await approve(audit, newFinance, 'Authorized fictional demo: inspect the corrected immutable CSV version in generation two.');
    run = await poll(run => run.status === 'completed', 'corrected generation completes under auto-permitted output preference');
    assert.equal(run.steps.filter(step => step.execution?.status === 'completed').length, 6);
    assert.ok(run.outputs.some(item => !item.stale));
    const comparison = run.steps.find(step => step.logical_key === 'invoice_compare').result;
    await writeFile(path.join(output, 'corrected-comparison.json'), JSON.stringify(comparison, null, 2));
    assert.deepEqual(comparison.comparison.findings, [], 'Corrected evidence must have no discrepancies');
    assert.equal(Number(comparison.comparison.difference), 0);
    assert.equal(run.cases[0].status, 'resolved');
    await page.goto(`${base}/#workflows/${runId}`);
    await page.getByRole('heading', { name: 'Persisted workflow state' }).waitFor();
    await scene(page, 'revised-completed');
    check('fresh approval resumes corrected plan with real new receipts and preserved history');
    const { default: AxeBuilder } = requireFrontend('@axe-core/playwright');
    for (const [label, viewport] of [['desktop', { width: 1440, height: 1080 }], ['mobile', { width: 390, height: 844 }]]) {
      await page.setViewportSize(viewport); await page.emulateMedia({ reducedMotion: 'reduce' });
      const layout = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: window.innerWidth }));
      assert.ok(layout.content <= layout.viewport + 1, `${label} workflow overflow: ${JSON.stringify(layout)}`);
      const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
      await writeFile(path.join(output, `axe-${label}.json`), JSON.stringify(axe, null, 2));
      assert.deepEqual(axe.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) })), []);
      await scene(page, `completed-${label}`);
    }
    check('real workflow desktop and 390px layout pass axe WCAG A/AA checks');
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await page.getByRole('heading', { name: 'Sign in to Relay' }).waitFor();
    assert.equal(await page.locator('.workflow-step-list').count(), 0);
    check('logout clears protected run details');
    assert.deepEqual(errors, []);
    const report = { kind: 'real-two-member-browser-api', passed: true, runId, invoiceRef, checks, scenes, errors, generation: run.generation, receipts: run.steps.map(step => step.execution.id) };
    await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(`${checks.length} live workflow browser checks passed.`); return report;
  } catch (error) {
    await writeFile(path.join(output, 'report.json'), JSON.stringify({ kind: 'real-two-member-browser-api', passed: false, runId, checks, scenes, errors, failure: String(error) }, null, 2));
    throw error;
  } finally { await browser.close(); }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await runWorkflowBrowser();
