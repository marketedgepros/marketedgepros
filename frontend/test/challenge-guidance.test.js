import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';

const require = createRequire(import.meta.url);
assert.equal(require('jsdom/package.json').version, '28.1.0', 'challenge DOM evidence requires the direct pinned jsdom package');

const bootstrap = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://challenge-guidance-bootstrap.invalid/' });
const bootstrapKeys = ['window', 'document', 'navigator', 'HTMLElement', 'HTMLAnchorElement', 'HTMLInputElement', 'Node', 'Element', 'Event', 'MouseEvent', 'KeyboardEvent', 'IS_REACT_ACT_ENVIRONMENT'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({
  window: bootstrap.window,
  document: bootstrap.window.document,
  navigator: bootstrap.window.navigator,
  HTMLElement: bootstrap.window.HTMLElement,
  HTMLAnchorElement: bootstrap.window.HTMLAnchorElement,
  HTMLInputElement: bootstrap.window.HTMLInputElement,
  Node: bootstrap.window.Node,
  Element: bootstrap.window.Element,
  Event: bootstrap.window.Event,
  MouseEvent: bootstrap.window.MouseEvent,
  KeyboardEvent: bootstrap.window.KeyboardEvent,
  IS_REACT_ACT_ENVIRONMENT: true,
})) Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
const reactModule = await import('react');
const React = reactModule.default;
const { act } = reactModule;
const { createRoot } = await import('react-dom/client');
const { Link, MemoryRouter, Route, Routes, useLocation, useNavigate } = await import('react-router-dom');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrap.window.close();

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = (...parts) => path.join(frontend, 'src', ...parts);
const sourceUrl = (...parts) => pathToFileURL(sourcePath(...parts)).href;
const dependencyUrl = (specifier) => pathToFileURL(require.resolve(specifier)).href;
const externalImports = new Map([
  ['react', dependencyUrl('react')],
  ['react/jsx-runtime', dependencyUrl('react/jsx-runtime')],
  ['react/jsx-dev-runtime', dependencyUrl('react/jsx-dev-runtime')],
  ['react-router-dom', dependencyUrl('react-router-dom')],
  ['lucide-react', dependencyUrl('lucide-react')],
]);
const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'challenge-guidance-dom-'));

function makeImportable(source) {
  for (const [specifier, absolute] of externalImports) {
    source = source
      .replaceAll(`from '${specifier}'`, `from ${JSON.stringify(absolute)}`)
      .replaceAll(`from "${specifier}"`, `from ${JSON.stringify(absolute)}`);
  }
  return source;
}
function writeModule(name, source) {
  const target = path.join(temporaryDirectory, name);
  fs.writeFileSync(target, source);
  return pathToFileURL(target).href;
}
async function compile(name, source) {
  const transformed = await transformWithEsbuild(makeImportable(source), `${name}.jsx`, {
    loader: 'jsx', jsx: 'automatic', format: 'esm',
  });
  const target = path.join(temporaryDirectory, `${name}.mjs`);
  fs.writeFileSync(target, makeImportable(transformed.code));
  return import(`${pathToFileURL(target).href}?challenge-guidance=${process.pid}`);
}

const authStub = writeModule('auth-store.mjs', `
  export default function useAuthStore(selector) {
    const state = globalThis.__challengeGuidanceAuth || { user: null, isAuthenticated: false };
    return typeof selector === 'function' ? selector(state) : state;
  }
`);
const pageSource = fs.readFileSync(sourcePath('pages', 'ChallengeDetails.jsx'), 'utf8')
  .replace("from '../services/api';", `from ${JSON.stringify(sourceUrl('services', 'api.js'))};`)
  .replace("from '../services/challengeViewService';", `from ${JSON.stringify(sourceUrl('services', 'challengeViewService.js'))};`)
  .replace("from '../store/authStore';", `from ${JSON.stringify(authStub)};`)
  .replace("from '../constants/roles.js';", `from ${JSON.stringify(sourceUrl('constants', 'roles.js'))};`);
const challengeDetail = await compile('ChallengeDetails', pageSource);
const api = (await import(sourceUrl('services', 'api.js'))).default;

const owner = Object.freeze({ user_id: 9, tenant_id: 7 });
const principal = Object.freeze({ key: '[true,"number:9","number:7","string:trader"]', ready: true, expectedOwner: owner });

function detailPayload(id, {
  legacyStatus = 'active',
  ownerContext = owner,
  profitTargetPercent = '0.00000000000000000000000000000000001',
  minTradingDays = 0,
} = {}) {
  return {
    owner_context: ownerContext,
    data_status: 'unverified_legacy',
    provider_authenticated: false,
    challenge: {
      id,
      user_id: 9,
      program: { id: 7, name: `Synthetic Evaluation ${id}` },
      legacy_status: legacyStatus,
      legacy_payment_status: 'recorded_paid',
      current_phase: 0,
      total_phases: 2,
      initial_balance: '0.00',
      current_balance: '0',
      max_drawdown_observed: '-0.00000000000000000001',
      start_date: null,
      end_date: null,
      passed_at: null,
      created_at: '2026-10-11T12:00:00+00:00',
      data_status: 'unverified_legacy',
      provider_authenticated: false,
    },
    progress: {
      initial_balance: '0.00',
      current_balance: '0',
      profit_loss: '0.00000000000000000000',
      profit_target_percent: profitTargetPercent,
      profit_target_amount: '0.00000000000000000000000000000000001',
      profit_progress_percent: '0',
      trading_days: 0,
      min_trading_days: minTradingDays,
      data_status: 'unverified_legacy',
      provider_authenticated: false,
    },
    mt5_account: {
      login: `recorded-${id}`,
      server: 'legacy.example.invalid',
      group: 'legacy',
      status: legacyStatus,
      balance: '0',
      equity: '0.00000000000000000000',
      margin: '0.00',
      free_margin: null,
      margin_level: '0',
      updated_at: '2026-10-11T12:00:00+00:00',
      data_status: 'unverified_legacy',
      provider_authenticated: false,
    },
  };
}
function response(config, data) {
  return { data, status: 200, statusText: 'OK', headers: {}, config, request: {} };
}

function installDom(url = 'http://challenge-guidance.invalid/challenges/41') {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { url, pretendToBeVisual: true });
  const keys = [
    'window', 'document', 'navigator', 'HTMLElement', 'HTMLAnchorElement', 'HTMLInputElement', 'Node', 'Element',
    'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle', 'requestAnimationFrame',
    'cancelAnimationFrame', 'IS_REACT_ACT_ENVIRONMENT',
  ];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const values = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLAnchorElement: dom.window.HTMLAnchorElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Node: dom.window.Node,
    Element: dom.window.Element,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { value, writable: true, configurable: true });
  const root = createRoot(dom.window.document.getElementById('root'));
  return {
    dom,
    root,
    host: dom.window.document.getElementById('root'),
    async close() {
      await act(async () => root.unmount());
      for (const [key, descriptor] of prior) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
      dom.window.close();
    },
  };
}

const delay = () => new Promise((resolve) => setTimeout(resolve, 0));
async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await delay();
}
async function waitFor(predicate, label) {
  let failure;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const value = predicate();
      if (value) return value;
    } catch (error) { failure = error; }
    await act(async () => { await settle(); });
  }
  throw failure || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected a current interactive element');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}
async function press(element, key) {
  assert.ok(element, `expected a tab for ${key}`);
  await act(async () => {
    element.dispatchEvent(new window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
    await settle();
  });
}
function text(node) { return node.textContent.replace(/\s+/g, ' ').trim(); }
function location(host) { return host.querySelector('[data-challenge-guidance-location]')?.textContent; }
function definitionValue(scope, label) {
  const term = [...scope.querySelectorAll('dt')].find((candidate) => text(candidate) === label);
  assert.ok(term, `missing definition term ${label}`);
  return text(term.parentElement.querySelector('dd'));
}

function LocationProbe() {
  const current = useLocation();
  const navigate = useNavigate();
  return React.createElement('aside', null,
    React.createElement('output', { 'data-challenge-guidance-location': true }, current.pathname),
    React.createElement('button', { type: 'button', onClick: () => navigate(-1) }, 'Back'));
}
function destination(label) {
  return React.createElement('main', { 'data-destination': label }, label);
}
function challengeRouter(id, pageKey = `challenge-${id}`) {
  return React.createElement(MemoryRouter, { key: pageKey, initialEntries: [`/challenges/${id}`] },
    React.createElement(React.Fragment, null,
      React.createElement(Routes, null,
        React.createElement(Route, { path: '/challenges/:id', element: React.createElement(challengeDetail.ChallengeDetailsContent, { id: String(id), principal }) }),
        React.createElement(Route, { path: '/programs/:id', element: destination('Program destination') }),
        React.createElement(Route, { path: '/support/my-tickets', element: destination('Support destination') }),
      ),
      React.createElement(LocationProbe),
    ));
}

test('Challenge guidance maps only missing and failed/rejected legacy records to conservative support actions', () => {
  const missing = challengeDetail.challengeGuidanceForStatus(null);
  const rejected = challengeDetail.challengeGuidanceForStatus('REJECTED');
  const failed = challengeDetail.challengeGuidanceForStatus('failed');
  const unknown = challengeDetail.challengeGuidanceForStatus('operator_custom_state');

  assert.equal(missing.kind, 'missing-status');
  assert.equal(missing.includesProgram, false);
  assert.equal(rejected.kind, 'review-record');
  assert.equal(failed.kind, 'review-record');
  assert.equal(rejected.includesProgram, false);
  assert.match(rejected.description, /does not offer a retry, purchase, trading, or provider action/i);
  assert.equal(unknown.kind, 'review-program');
  assert.equal(unknown.includesProgram, true);
  assert.doesNotMatch(`${unknown.title} ${unknown.description}`, /operator_custom_state/i, 'unknown raw status never becomes action copy');

  for (const status of ['passed', 'funded']) {
    const guidance = challengeDetail.challengeGuidanceForStatus(status);
    assert.equal(guidance.kind, 'review-program');
    assert.match(guidance.description, /No approval, funding, payment acceptance, or live account access is implied/i);
    assert.doesNotMatch(`${guidance.title} ${guidance.description}`, new RegExp(status, 'i'), `${status} is not promoted to a live claim`);
  }
});

test('Challenge details preserve exact recorded values, expose keyboard tabs without GET fanout, and navigate to live program/support routes', { concurrency: false }, async () => {
  const view = installDom();
  const previousAdapter = api.defaults.adapter;
  const requests = [];
  api.defaults.adapter = async (config) => {
    requests.push({ url: config.url, method: config.method, signal: config.signal });
    assert.equal(config.url, '/challenges/41/progress');
    assert.equal(config.method, 'get');
    assert.ok(config.signal instanceof AbortSignal);
    return response(config, detailPayload(41, { legacyStatus: 'funded' }));
  };

  try {
    await act(async () => {
      view.root.render(challengeRouter(41));
      await settle();
    });
    await waitFor(() => view.host.querySelector('[data-challenge-requirements]'), 'recorded requirement source');
    assert.equal(requests.length, 1, 'the detail view keeps its single existing GET');

    const requirements = view.host.querySelector('[data-challenge-requirements]');
    assert.equal(definitionValue(requirements, 'Recorded catalog profit target percent'), '0.00000000000000000000000000000000001');
    assert.equal(definitionValue(requirements, 'Recorded catalog minimum trading days'), '0', 'zero is recorded, not treated as unavailable');
    assert.match(text(view.host.querySelector('[data-challenge-next-action]')), /No approval, funding, payment acceptance, or live account access is implied/i);
    assert.doesNotMatch(text(view.host.querySelector('[data-challenge-next-action]')), /funded/i, 'funded legacy status is not an action label');

    const tabs = [...view.host.querySelectorAll('[role="tab"]')];
    assert.equal(tabs.length, 2);
    assert.equal(tabs[0].getAttribute('aria-selected'), 'true');
    assert.equal(tabs[1].getAttribute('tabindex'), '-1');
    tabs[0].focus();
    await press(tabs[0], 'ArrowRight');
    assert.equal(document.activeElement, tabs[1]);
    assert.equal(tabs[1].getAttribute('aria-selected'), 'true');
    assert.equal(view.host.querySelector('[role="tabpanel"]').getAttribute('aria-labelledby'), tabs[1].id);
    assert.match(text(view.host.querySelector('[role="tabpanel"]')), /recorded-41/);
    assert.equal(requests.length, 1, 'selecting an account tab cannot fetch');
    await press(tabs[1], 'Home');
    assert.equal(document.activeElement, tabs[0]);
    assert.equal(tabs[0].getAttribute('aria-selected'), 'true');
    await press(tabs[0], 'End');
    assert.equal(document.activeElement, tabs[1]);
    await press(tabs[1], 'ArrowLeft');
    assert.equal(document.activeElement, tabs[0]);
    assert.equal(requests.length, 1, 'ArrowLeft/Right/Home/End remain local state only');

    await click(view.host.querySelector('a[href="/programs/7"]'));
    await waitFor(() => location(view.host) === '/programs/7', 'program route change');
    assert.match(text(view.host), /Program destination/);

    await act(async () => {
      view.root.render(challengeRouter(41, 'challenge-remount-for-support'));
      await settle();
    });
    await waitFor(() => view.host.querySelector('a[href="/support/my-tickets"]'), 'support action after explicit route remount');
    await click(view.host.querySelector('a[href="/support/my-tickets"]'));
    await waitFor(() => location(view.host) === '/support/my-tickets', 'support route change');
    assert.match(text(view.host), /Support destination/);
  } finally {
    api.defaults.adapter = previousAdapter;
    await view.close();
  }
});

test('Challenge details render null catalog values as unavailable and keep failed records on review/support only', { concurrency: false }, async () => {
  const view = installDom('http://challenge-guidance.invalid/challenges/44');
  const previousAdapter = api.defaults.adapter;
  const requests = [];
  api.defaults.adapter = async (config) => {
    requests.push(config.url);
    assert.equal(config.url, '/challenges/44/progress');
    return response(config, detailPayload(44, {
      legacyStatus: 'failed',
      profitTargetPercent: null,
      minTradingDays: null,
    }));
  };

  try {
    await act(async () => {
      view.root.render(challengeRouter(44));
      await settle();
    });
    const requirements = await waitFor(() => view.host.querySelector('[data-challenge-requirements]'), 'null requirement source');
    assert.equal(definitionValue(requirements, 'Recorded catalog profit target percent'), 'Unavailable');
    assert.equal(definitionValue(requirements, 'Recorded catalog minimum trading days'), 'Unavailable');

    const action = view.host.querySelector('[data-challenge-next-action="review-record"]');
    assert.ok(action, 'failed status receives only the conservative record-review action');
    assert.ok(action.querySelector('a[href="/support/my-tickets"]'));
    assert.equal(action.querySelector('a[href^="/programs/"]'), null, 'failed records do not invite a program retry or purchase path');
    assert.match(text(action), /does not offer a retry, purchase, trading, or provider action/i);
    assert.deepEqual(requests, ['/challenges/44/progress']);
  } finally {
    api.defaults.adapter = previousAdapter;
    await view.close();
  }
});

test('Challenge detail discards a late route response and rejects an owner-mismatched record before projection', { concurrency: false }, async () => {
  const view = installDom();
  const previousAdapter = api.defaults.adapter;
  let releaseRoute41;
  const requests = [];
  api.defaults.adapter = async (config) => {
    requests.push(config.url);
    if (config.url === '/challenges/41/progress') {
      return new Promise((resolve) => { releaseRoute41 = () => resolve(response(config, detailPayload(41))); });
    }
    if (config.url === '/challenges/42/progress') return response(config, detailPayload(42));
    if (config.url === '/challenges/43/progress') {
      return response(config, detailPayload(43, { ownerContext: { user_id: 10, tenant_id: 7 } }));
    }
    throw new Error(`unexpected request ${config.url}`);
  };

  const render = async (id) => {
    await act(async () => {
      view.root.render(challengeRouter(id, `route-${id}`));
      await settle();
    });
  };

  try {
    await render(41);
    await waitFor(() => typeof releaseRoute41 === 'function', 'first route request');
    await render(42);
    await waitFor(() => text(view.host).includes('Synthetic Evaluation 42'), 'second route projection');
    releaseRoute41();
    await act(async () => { await settle(); });
    assert.doesNotMatch(text(view.host), /Synthetic Evaluation 41/, 'an abort-resistant late route response cannot replace the current route');
    assert.match(text(view.host), /Synthetic Evaluation 42/);

    await render(43);
    await waitFor(() => view.host.querySelector('[role="alert"]'), 'owner mismatch error');
    assert.match(text(view.host.querySelector('[role="alert"]')), /could not be loaded/i);
    assert.doesNotMatch(text(view.host), /Synthetic Evaluation 42/, 'old owner data is cleared before a rejected response can project');
    assert.deepEqual(requests, ['/challenges/41/progress', '/challenges/42/progress', '/challenges/43/progress']);
  } finally {
    api.defaults.adapter = previousAdapter;
    await view.close();
  }
});

test.after(() => {
  fs.rmSync(temporaryDirectory, { recursive: true, force: true });
});
