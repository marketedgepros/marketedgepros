import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import React, { act } from 'react';
import { Simulate } from 'react-dom/test-utils';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';
import api from '../src/services/api.js';
import useAuthStore from '../src/store/authStore.js';

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = (...parts) => path.join(frontend, 'src', ...parts);
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'remediation-admin-programs-'));
const dependencyUrl = (specifier) => pathToFileURL(require.resolve(specifier)).href;
const dependencies = new Map([
  ['react', dependencyUrl('react')],
  ['react/jsx-runtime', dependencyUrl('react/jsx-runtime')],
  ['lucide-react', dependencyUrl('lucide-react')],
]);

function absolutize(source) {
  for (const [specifier, url] of dependencies) {
    source = source.replaceAll(`from '${specifier}'`, `from ${JSON.stringify(url)}`);
    source = source.replaceAll(`from "${specifier}"`, `from ${JSON.stringify(url)}`);
  }
  return source;
}

async function compileProgramsPage() {
  const pageSource = fs.readFileSync(sourcePath('pages', 'admin', 'ProgramsManagement.jsx'), 'utf8')
    .replace("'../../store/authStore.js'", JSON.stringify(pathToFileURL(sourcePath('store', 'authStore.js')).href))
    .replace("'../../hooks/useDialogFocus.js'", JSON.stringify(pathToFileURL(sourcePath('hooks', 'useDialogFocus.js')).href))
    .replace("'../../services/adminClosureProgramsService.js'", JSON.stringify(pathToFileURL(sourcePath('services', 'adminClosureProgramsService.js')).href));
  const target = path.join(temporary, 'ProgramsManagement.mjs');
  const transformed = await transformWithEsbuild(absolutize(pageSource), target, { loader: 'jsx', jsx: 'automatic', format: 'esm' });
  fs.writeFileSync(target, absolutize(transformed.code));
  return (await import(`${pathToFileURL(target).href}?remediation=${process.pid}`)).default;
}

const bootstrap = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://admin-programs.bootstrap.test/' });
const bootstrapKeys = ['window', 'document', 'navigator'];
const bootstrapPrior = new Map(bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
for (const [key, value] of Object.entries({ window: bootstrap.window, document: bootstrap.window.document, navigator: bootstrap.window.navigator })) {
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
}
const { createRoot } = await import('react-dom/client');
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrap.window.close();

const ProgramsManagement = await compileProgramsPage();

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
    url: 'http://admin-programs.remediation.test/admin/programs',
    pretendToBeVisual: true,
  });
  const keys = [
    'window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'HTMLTextAreaElement',
    'Node', 'Element', 'Event', 'MouseEvent', 'KeyboardEvent', 'MutationObserver', 'getComputedStyle',
    'requestAnimationFrame', 'cancelAnimationFrame', 'IS_REACT_ACT_ENVIRONMENT',
  ];
  const prior = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const bindings = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
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
  for (const [key, value] of Object.entries(bindings)) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  const root = createRoot(dom.window.document.getElementById('root'));
  return {
    dom,
    root,
    host: dom.window.document.getElementById('root'),
    async close() {
      await act(async () => { root.unmount(); });
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
  for (let step = 0; step < 6; step += 1) await Promise.resolve();
  await delay();
  for (let step = 0; step < 6; step += 1) await Promise.resolve();
}
async function waitFor(predicate, label) {
  let lastError;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const result = predicate();
      if (result) return result;
    } catch (error) {
      lastError = error;
    }
    await act(async () => { await settle(); });
  }
  throw lastError || new Error(`Timed out waiting for ${label}`);
}
async function click(element) {
  assert.ok(element, 'expected actionable element');
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }));
    await settle();
  });
}
async function pressEscape(element) {
  await act(async () => {
    element.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    await settle();
  });
}
async function submit(form) {
  await act(async () => {
    form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
    await settle();
  });
}
async function inputValue(element, value) {
  assert.ok(element, 'expected editable control');
  const prototype = element.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
  descriptor.set.call(element, value);
  await act(async () => {
    Simulate.change(element, { target: { name: element.name, value, type: element.type, checked: element.checked } });
    await settle();
  });
}
function exactButton(host, label) {
  return [...host.querySelectorAll('button')].find((button) => button.textContent.replace(/\s+/g, ' ').trim() === label);
}
function dialog(host) {
  return host.querySelector('[role="dialog"], [role="alertdialog"]');
}
function axiosResponse(config, data) {
  return { data, status: 200, statusText: 'OK', headers: {}, config, request: {} };
}

const owner = { user_id: 41, tenant_id: 7, role: 'master' };
const principal = { id: 41, tenant_id: 7, role: 'master' };
function rawProgram(overrides = {}) {
  return {
    id: 1,
    tenant_id: 7,
    name: 'First page program',
    type: 'stored_type',
    description: null,
    account_size: '10000.00',
    profit_target: null,
    max_daily_loss: null,
    max_total_loss: null,
    price: '199.99',
    profit_split: null,
    profit_split_percentage: null,
    minimum_payout_amount: null,
    payout_mode: null,
    rules: {},
    is_active: true,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}
function listPayload(page, programs, total) {
  return {
    owner_context: owner,
    programs,
    pagination: { page, per_page: 20, total, pages: total === 0 ? 0 : Math.ceil(total / 20) },
  };
}

test('remediation ProgramsManagement refetches the current source range after create, clamps a deleted final page, and focuses both actual dialogs', { concurrency: false }, async () => {
  const harness = installDom();
  const originalAuth = useAuthStore.getState();
  const originalAdapter = api.defaults.adapter;
  const reads = [];
  let pageOneReads = 0;
  let pageTwoReads = 0;
  const first = rawProgram();
  const last = rawProgram({ id: 20, name: 'Last page program' });
  const created = rawProgram({ id: 21, name: 'Created program', account_size: '25000.00' });

  api.defaults.adapter = async (config) => {
    const method = String(config.method || 'get').toLowerCase();
    const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data;
    assert.equal(config._skipAuthRefresh, true, 'all synthetic program calls retain the no-replay transport guard');
    assert.ok(config.signal instanceof AbortSignal, 'all synthetic program calls remain cancelable');

    if (method === 'get' && config.url === '/admin/programs') {
      const page = config.params.page;
      reads.push(page);
      if (page === '1') {
        pageOneReads += 1;
        return axiosResponse(config, listPayload(1, [first], pageOneReads === 1 ? 21 : 20));
      }
      assert.equal(page, '2', 'the mutation reload must request only a bounded catalog page');
      pageTwoReads += 1;
      if (pageTwoReads === 1) return axiosResponse(config, listPayload(2, [last], 21));
      if (pageTwoReads === 2) return axiosResponse(config, listPayload(2, [last, created], 22));
      if (pageTwoReads === 3) return axiosResponse(config, listPayload(2, [last], 21));
      throw new Error(`Unexpected page-two read ${pageTwoReads}`);
    }
    if (method === 'post' && config.url === '/admin/programs') {
      assert.deepEqual(body, {
        name: 'Created program', type: 'stored_type', description: null,
        account_size: '25000.00', profit_target: null, max_daily_loss: null, max_total_loss: null,
        price: '199.99', profit_split: null, profit_split_percentage: null,
        minimum_payout_amount: null, payout_mode: null, rules: {}, is_active: true,
      });
      return axiosResponse(config, { owner_context: owner, program: created });
    }
    if (method === 'delete' && config.url === '/admin/programs/21') {
      assert.equal(body, undefined);
      return axiosResponse(config, { owner_context: owner, deleted_program_id: 21 });
    }
    if (method === 'delete' && config.url === '/admin/programs/20') {
      assert.equal(body, undefined);
      return axiosResponse(config, { owner_context: owner, deleted_program_id: 20 });
    }
    throw new Error(`Unexpected synthetic request ${method} ${config.url}`);
  };
  useAuthStore.setState({ user: principal, isAuthenticated: true, isLoading: false, error: null, init: async () => {} });

  try {
    await act(async () => { harness.root.render(React.createElement(ProgramsManagement)); await settle(); });
    await waitFor(() => harness.host.textContent.includes('First page program'), 'initial source page');

    await click(exactButton(harness.host, 'Next'));
    await waitFor(() => harness.host.textContent.includes('Last page program'), 'last source page');
    assert.ok(harness.host.textContent.includes('Page 2 of 2'));

    const createTrigger = exactButton(harness.host, 'Create program');
    createTrigger.focus();
    await click(createTrigger);
    const focusEditor = await waitFor(() => dialog(harness.host), 'create dialog focus');
    assert.equal(document.activeElement, exactButton(focusEditor, 'Cancel'), 'editor uses the foundation dialog hook with a safe initial focus target');
    await pressEscape(document.activeElement);
    await waitFor(() => !dialog(harness.host), 'editor escape close');
    assert.equal(document.activeElement, createTrigger, 'editor close restores focus to its trigger');

    await click(createTrigger);
    const form = (await waitFor(() => dialog(harness.host), 'create dialog')).querySelector('form');
    await inputValue(form.querySelector('#program-name'), 'Created program');
    await inputValue(form.querySelector('#program-type'), 'stored_type');
    await inputValue(form.querySelector('#program-accountSize'), '25000.00');
    await inputValue(form.querySelector('#program-price'), '199.99');
    await submit(form);
    await waitFor(() => !dialog(harness.host) && harness.host.textContent.includes('Created program'), 'server-confirmed create and range reload');
    assert.deepEqual(reads, ['1', '2', '2'], 'create performs one bounded reload of the current page rather than locally mixing page ranges');
    assert.equal(harness.host.querySelectorAll('tbody tr').length, 2, 'the rendered rows are the server-returned page-two range');

    const createdDelete = harness.host.querySelector('[aria-label="Delete Created program"]');
    createdDelete.focus();
    await click(createdDelete);
    const focusDelete = await waitFor(() => dialog(harness.host), 'delete dialog focus');
    assert.equal(document.activeElement, exactButton(focusDelete, 'Cancel'), 'delete confirmation uses the foundation dialog hook with safe initial focus');
    await pressEscape(document.activeElement);
    await waitFor(() => !dialog(harness.host), 'delete escape close');
    assert.equal(document.activeElement, createdDelete, 'delete close restores focus to its trigger');

    await click(createdDelete);
    await click(exactButton(await waitFor(() => dialog(harness.host), 'created delete confirmation'), 'Confirm server deletion'));
    await waitFor(() => !dialog(harness.host) && harness.host.textContent.includes('Last page program') && !harness.host.textContent.includes('Created program'), 'created program reload');
    assert.deepEqual(reads, ['1', '2', '2', '2'], 'ordinary deletion also performs exactly one bounded source reload');

    await click(harness.host.querySelector('[aria-label="Delete Last page program"]'));
    await click(exactButton(await waitFor(() => dialog(harness.host), 'final-row delete confirmation'), 'Confirm server deletion'));
    await waitFor(() => harness.host.textContent.includes('First page program') && harness.host.textContent.includes('Page 1 of 1'), 'clamped source page after deleting the only final-page record');
    assert.deepEqual(reads, ['1', '2', '2', '2', '1'], 'deleting the final page record clamps to page one and performs one correct reload');
    assert.equal(harness.host.querySelectorAll('tbody tr').length, 1, 'no stale final-page row is retained after the clamp');
  } finally {
    api.defaults.adapter = originalAdapter;
    useAuthStore.setState(originalAuth, true);
    await harness.close();
  }
});

test.after(() => {
  fs.rmSync(temporary, { recursive: true, force: true });
});
