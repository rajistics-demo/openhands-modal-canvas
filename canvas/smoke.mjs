/** Time the real Canvas Pause and sidebar-reopen path on one owned fixture. */
import { readFile } from 'node:fs/promises';
import { performance } from 'node:perf_hooks';

const help = 'Usage: node canvas/smoke.mjs .private/canvas-fixture.json';
const [configPath] = process.argv.slice(2);
if (!configPath || configPath === '--help') {
  console.log(help);
  process.exit(configPath ? 0 : 2);
}

function require(condition, message) {
  if (!condition) throw new Error(message);
}

function id(value) {
  return String(value).replaceAll('-', '').toLowerCase();
}

function exactHttps(value, originOnly = false) {
  const url = new URL(value);
  require(url.protocol === 'https:' && !url.username && !url.password &&
    !url.search && !url.hash && (!originOnly || url.pathname === '/'),
  'Use HTTPS URLs without credentials or query strings.');
  return url;
}

async function run(config) {
  const origin = exactHttps(config.origin, true).origin;
  const preview = exactHttps(config.preview);
  require(preview.origin !== origin && preview.pathname.endsWith('/'),
    'Use an isolated preview origin and a path ending in a slash.');
  require(/^[A-Za-z0-9-]{1,128}$/.test(config.sandboxId) &&
    /^[0-9a-f]{32}$/.test(id(config.conversationId)) &&
    /^[0-9a-f]{32}$/.test(id(config.orgId)) &&
    typeof config.title === 'string' && config.title.length > 0 &&
    typeof config.historyMarker === 'string' && config.historyMarker.length > 0 &&
    config.isolated === true, 'Select an isolated, explicitly owned fixture.');

  const { chromium, request } = await import('playwright');
  const browser = await chromium.launch();
  const sandboxPath = `/api/v1/sandboxes/${config.sandboxId}`;
  const apiHeaders = { 'X-Org-Id': config.orgId };
  let stage = 'Browser sign-in';
  try {
    const context = await browser.newContext({ storageState: config.storageState });
    const get = async (path) => {
      const result = await context.request.get(origin + path, {
        headers: apiHeaders, maxRedirects: 0, timeout: 10000,
      });
      require(result.ok(), `${stage}: expected an authorized app API response.`);
      return result.json();
    };
    const first = (items) => {
      require(Array.isArray(items) && items.length === 1, `${stage}: expected one record.`);
      return items[0];
    };
    stage = 'Ownership and Pause capability';
    const me = await get('/api/v1/users/me');
    const principal = me.id || me.user_id;
    require(principal && principal === config.principalId, 'Unexpected signed-in account.');
    const conversationPath = `/api/v1/app-conversations?ids=${encodeURIComponent(config.conversationId)}`;
    const conversation = first(await get(conversationPath));
    require(id(conversation.id) === id(config.conversationId) &&
      conversation.sandbox_id === config.sandboxId && conversation.created_by_user_id === principal &&
      conversation.sandbox_supports_runtime_pause, 'Conversation is not the owner’s test fixture with Pause enabled.');
    async function sandbox() {
      const found = first(await get(`/api/v1/sandboxes?id=${encodeURIComponent(config.sandboxId)}`));
      require(found.id === config.sandboxId && found.created_by_user_id === principal &&
        found.credential_org_id === config.orgId, 'Unexpected sandbox owner or organization.');
      return found;
    }
    require((await sandbox()).status === 'RUNNING', 'Start the fixture before running the browser test.');
    if (config.authenticatedPreview) {
      stage = 'Anonymous preview rejection';
      const anonymous = await request.newContext();
      try {
        const response = await anonymous.get(new URL('state', preview).href, { maxRedirects: 0 });
        require([401, 403].includes(response.status()), 'Anonymous preview did not reject access.');
      } finally {
        await anonymous.dispose();
      }
    }

    const page = await context.newPage();
    const actions = [];
    const timing = {};
    let reopened;
    const elapsed = (start) => (performance.now() - start) / 1000;
    const route = (url) => url.origin === origin && id(url.pathname.split('/').at(-1)) === id(config.conversationId);
    const lifecycle = (url, action) => url.origin === origin && (
      url.pathname === `${sandboxPath}/${action}` ||
      [...url.searchParams.values()].some((value) => value.endsWith(`${sandboxPath}/${action}`))
    );
    page.on('request', (event) => {
      if (event.method() !== 'POST') return;
      const url = new URL(event.url());
      for (const action of ['pause', 'resume']) {
        if (!lifecycle(url, action)) continue;
        actions.push(action);
        if (reopened !== undefined && action === 'resume') timing.resume_request_s = elapsed(reopened);
      }
    });
    page.on('response', (response) => {
      if (reopened === undefined || response.request().method() !== 'POST') return;
      if (lifecycle(new URL(response.url()), 'resume') && response.ok()) {
        timing.resume_ack_s = elapsed(reopened);
      }
    });
    const titlePattern = new RegExp('^' + config.title.replace(/[.*+?^\${}()|[\]\\]/g, '\\$&') + '$');
    const card = page.getByTestId('conversation-card-title').filter({ hasText: titlePattern });
    const history = page.getByText(config.historyMarker, { exact: true }).first();

    async function checkPreview() {
      const frame = page.frameLocator('[data-testid="canvas-pilot-live-preview"]');
      const state = frame.locator('#state');
      await state.filter({ hasText: '"boot"' }).waitFor({ timeout: 35000 });
      const check = frame.getByRole('button', { name: 'Check live process' });
      const [response] = await Promise.all([
        page.waitForResponse((value) => value.url() === new URL('check', preview).href &&
          value.request().method() === 'POST', { timeout: 12000 }),
        check.click(),
      ]);
      require(response.ok(), 'Preview check did not return a successful response.');
      const reply = await response.json();
      require(typeof reply.boot === 'string' && Number.isInteger(reply.count), 'Unexpected preview fixture state.');
      return reply;
    }
    async function waitState(expected) {
      const until = performance.now() + 35000;
      while (performance.now() < until) {
        if ((await sandbox()).status === expected) return;
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      throw new Error('Sandbox did not settle.');
    }

    stage = 'Initial conversation and preview';
    await page.goto(origin + '/canvas/', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await card.click({ timeout: 30000 });
    await page.waitForURL(route, { timeout: 25000 });
    await history.waitFor({ timeout: 25000 });
    const before = await checkPreview();

    stage = 'Pause and read-only checks';
    const paused = performance.now();
    await page.getByTestId('pause-cloud-runtime-button').click({ timeout: 15000 });
    await waitState('PAUSED');
    timing.pause_to_settled_s = elapsed(paused);
    await card.waitFor({ timeout: 22000 });
    const events = await get(`/api/v1/conversation/${encodeURIComponent(config.conversationId)}/events/search?limit=40`);
    require(events.items?.some((event) => JSON.stringify(event).includes(config.historyMarker)),
      'Enterprise has no persisted history marker while paused.');
    if (config.checkPausedPreview) {
      const result = await context.request.get(new URL('state', preview).href, { maxRedirects: 0, timeout: 10000 });
      require(result.status() === 409, 'Expected a paused preview to fail closed.');
    }
    require((await sandbox()).status === 'PAUSED' && !actions.includes('resume'), 'A passive read resumed the sandbox.');

    stage = 'Same conversation reopen';
    reopened = performance.now();
    await card.click();
    const [historySeconds, [after, previewSeconds]] = await Promise.all([
      history.waitFor({ timeout: 35000 }).then(() => elapsed(reopened)),
      checkPreview().then((reply) => [reply, elapsed(reopened)]),
    ]);
    await page.waitForURL(route, { timeout: 10000 });
    await waitState('RUNNING');
    const restored = first(await get(conversationPath));
    require(restored.sandbox_id === config.sandboxId && actions.join() === 'pause,resume', 'Unexpected lifecycle path.');
    require(before.boot === after.boot && before.count + 1 === after.count,
      'Preview process marker or count did not survive.');
    timing.reopen_to_history_s = historySeconds;
    timing.reopen_to_preview_s = previewSeconds;
    console.log(JSON.stringify({
      passed: true,
      same_conversation: true,
      persisted_history_while_paused: true,
      preview_state_preserved: true,
      ...Object.fromEntries(Object.entries(timing).map(([name, value]) => [name, +value.toFixed(3)])),
    }));
  } catch (error) {
    // Browser errors can contain site URLs and user content. Keep console output sanitized.
    console.error(`Canvas smoke failed during ${stage} (${error.name}).`);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

try {
  require(configPath.split(/[\\/]/).includes('.private'), 'Keep browser and fixture inputs in an ignored .private directory.');
  const config = JSON.parse(await readFile(configPath, 'utf8'));
  require(typeof config.storageState === 'string' && config.storageState.split(/[\\/]/).includes('.private'),
    'Keep the browser storage state in an ignored .private directory.');
  await run(config);
} catch (error) {
  console.error(`Canvas smoke could not start (${error.name}). ${help}`);
  process.exitCode = 1;
}
