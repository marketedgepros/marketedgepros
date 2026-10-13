import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';
import useAdminClosureKyc from '../src/hooks/useAdminClosureKyc.js';

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sourcePath = (...parts) => path.join(frontend, 'src', ...parts);
const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'remediation-admin-kyc-'));
const moduleImports = new Map([
  ['react', pathToFileURL(require.resolve('react')).href],
  ['react/jsx-runtime', pathToFileURL(require.resolve('react/jsx-runtime')).href],
  ['react/jsx-dev-runtime', pathToFileURL(require.resolve('react/jsx-dev-runtime')).href],
  ['lucide-react', pathToFileURL(require.resolve('lucide-react')).href],
]);

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function portable(code) {
  for (const [name, target] of moduleImports) {
    code = code.replaceAll(`from '${name}'`, `from ${JSON.stringify(target)}`);
    code = code.replaceAll(`from ${JSON.stringify(name)}`, `from ${JSON.stringify(target)}`);
  }
  return code;
}

function replaceSpec(code, from, to) {
  return code.replaceAll(`'${from}'`, JSON.stringify(to));
}

function writeModule(name, code) {
  const target = path.join(tempDir, name);
  fs.writeFileSync(target, code);
  return pathToFileURL(target).href;
}

async function compile(name, code) {
  const target = path.join(tempDir, name);
  const result = await transformWithEsbuild(portable(code), name, { loader: 'jsx', jsx: 'automatic', format: 'esm' });
  fs.writeFileSync(target, portable(result.code));
  return import(`${pathToFileURL(target).href}?remediation-admin-kyc=${process.pid}`);
}

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body><button id="trigger">Open</button><div id="root"></div></body></html>', {
    url: 'https://admin-kyc.test/',
    pretendToBeVisual: true,
  });
  const keys = ['window', 'document', 'navigator', 'HTMLElement', 'Node', 'KeyboardEvent', 'Event', 'MouseEvent'];
  const previous = new Map(keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const bindings = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    Node: dom.window.Node,
    KeyboardEvent: dom.window.KeyboardEvent,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
  };
  for (const [key, value] of Object.entries(bindings)) {
    Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  }
  return {
    dom,
    document: dom.window.document,
    root: createRoot(dom.window.document.getElementById('root')),
    async close() {
      await act(async () => { this.root.unmount(); });
      for (const [key, descriptor] of previous) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
      dom.window.close();
    },
  };
}

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function waitFor(predicate, description) {
  let error;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const result = predicate();
      if (result) return result;
    } catch (caught) {
      error = caught;
    }
    await act(async () => { await settle(); });
  }
  throw error || new Error(`Timed out waiting for ${description}`);
}

function response(page, pages, userId, total = pages * 20) {
  return {
    submissions: [{ userId, kycStatus: 'pending', submittedAt: null, documents: {} }],
    pagination: { page, per_page: 20, pages, total },
    filters: { status: 'pending' },
  };
}

function Probe({ user, service, onRead }) {
  const read = useAdminClosureKyc({ user, isAuthenticated: true, service });
  onRead(read);
  return React.createElement('output', { id: 'kyc-state' }, JSON.stringify({
    loading: read.list.loading,
    page: read.list.value?.pagination.page ?? null,
    subject: read.list.value?.submissions[0]?.userId ?? null,
    canPreviousPage: read.canPreviousPage,
    canNextPage: read.canNextPage,
  }));
}

test('admin KYC uses response pagination, resets on identity, rejects stale responses, bounds navigation, and returns from an emptied final page', { concurrency: false }, async () => {
  const view = installDom();
  const calls = [];
  let latest;
  const service = {
    loadSubmissions(request) {
      return new Promise((resolve, reject) => {
        calls.push({ request, resolve, reject });
      });
    },
    loadSubmission: async () => { throw new Error('selection is outside this pagination harness'); },
  };
  const masterA = { id: 2, tenant_id: 10, role: 'master' };
  const masterB = { id: 9, tenant_id: 10, role: 'master' };
  const render = async (user) => {
    await act(async () => {
      view.root.render(React.createElement(Probe, { user, service, onRead: (read) => { latest = read; } }));
      await settle();
    });
  };

  try {
    await render(masterA);
    await waitFor(() => calls.length === 1, 'the first owner-bound list request');
    assert.deepEqual(calls[0].request, {
      expectedOwner: { user_id: 2, tenant_id: 10 }, status: 'pending', page: 1, perPage: 20, signal: calls[0].request.signal,
    });

    await render(masterB);
    await waitFor(() => calls.length === 2, 'the identity-reset page-one request');
    assert.equal(calls[1].request.page, 1, 'a new identity always starts at page one');
    assert.deepEqual(calls[1].request.expectedOwner, { user_id: 9, tenant_id: 10 });

    await act(async () => { calls[0].resolve(response(1, 3, 31)); await settle(); });
    assert.equal(JSON.parse(view.document.getElementById('kyc-state').textContent).subject, null, 'an aborted prior identity response cannot populate the current list');

    await act(async () => { calls[1].resolve(response(1, 3, 42, 41)); await settle(); });
    await waitFor(() => JSON.parse(view.document.getElementById('kyc-state').textContent).subject === 42, 'the current identity response');
    assert.equal(latest.canPreviousPage, false);
    assert.equal(latest.canNextPage, true);

    await act(async () => { latest.nextPage(); await settle(); });
    await waitFor(() => calls.length === 3, 'page two request');
    assert.equal(calls[2].request.page, 2);
    await act(async () => { calls[2].resolve(response(2, 3, 43, 41)); await settle(); });
    await waitFor(() => latest.list.value?.pagination.page === 2, 'page two response');
    assert.equal(latest.canPreviousPage, true);
    assert.equal(latest.canNextPage, true);

    await act(async () => { latest.nextPage(); await settle(); });
    await waitFor(() => calls.length === 4, 'page three request');
    assert.equal(calls[3].request.page, 3);
    await act(async () => { calls[3].resolve(response(3, 3, 44, 41)); await settle(); });
    await waitFor(() => latest.list.value?.pagination.page === 3, 'page three response');
    assert.equal(latest.canNextPage, false, 'Next is bounded by the server response pages value');
    const callCountAtLastPage = calls.length;
    await act(async () => { latest.nextPage(); await settle(); });
    assert.equal(calls.length, callCountAtLastPage, 'requesting Next on the final page does not fetch beyond the bound');

    await act(async () => { latest.previousPage(); await settle(); });
    await waitFor(() => calls.length === 5, 'return to page two');
    assert.equal(calls[4].request.page, 2);
    await act(async () => { calls[4].resolve(response(2, 3, 43, 41)); await settle(); });
    await waitFor(() => latest.list.value?.pagination.page === 2, 'returned page two response');

    await act(async () => { latest.refresh(); await settle(); });
    await waitFor(() => calls.length === 6, 'post-decision refresh on the now-final page');
    assert.equal(calls[5].request.page, 2);
    await act(async () => { calls[5].resolve(response(2, 1, 99, 1)); await settle(); });
    await waitFor(() => calls.length === 7, 'automatic correction to the server final page');
    assert.equal(calls[6].request.page, 1, 'an out-of-range refreshed response is corrected to page one');
    await act(async () => { calls[6].resolve(response(1, 1, 98, 1)); await settle(); });
    await waitFor(() => latest.list.value?.pagination.page === 1 && latest.list.value?.submissions[0]?.userId === 98, 'corrected final-page response');
  } finally {
    await view.close();
  }
});

test('admin KYC recorded-review dialog receives focus, traps Escape through the shared hook, and restores its trigger', { concurrency: false }, async () => {
  const toastStub = writeModule('toast.mjs', 'export const useToast = () => ({ success() {}, error() {} });\n');
  const authStub = writeModule('auth.mjs', 'export default function useAuthStore() { return null; }\n');
  let pageCode = fs.readFileSync(sourcePath('pages', 'admin', 'KYCApprovalConnected.jsx'), 'utf8');
  pageCode = replaceSpec(pageCode, '../../contexts/ToastContext', toastStub);
  pageCode = replaceSpec(pageCode, '../../store/authStore', authStub);
  pageCode = replaceSpec(pageCode, '../../hooks/useAdminClosureKyc.js', pathToFileURL(sourcePath('hooks', 'useAdminClosureKyc.js')).href);
  pageCode = replaceSpec(pageCode, '../../hooks/useDialogFocus.js', pathToFileURL(sourcePath('hooks', 'useDialogFocus.js')).href);
  pageCode = replaceSpec(pageCode, '../../services/adminClosureKycService.js', pathToFileURL(sourcePath('services', 'adminClosureKycService.js')).href);
  const page = await compile('KYCApprovalConnected.mjs', pageCode);
  const view = installDom();
  let closes = 0;
  const review = {
    userId: 3,
    document: { type: 'id_proof', name: 'ID proof', uploadedAt: '2026-10-12T12:00:00Z' },
    status: 'approved',
    notes: '',
    acknowledgement: '',
  };

  try {
    const trigger = view.document.getElementById('trigger');
    trigger.focus();
    await act(async () => {
      view.root.render(React.createElement(page.KycDocumentReviewDialog, {
        review,
        isSaving: false,
        onClose: () => { closes += 1; },
        onChange: () => {},
        onSubmit: () => {},
      }));
      await settle();
    });
    const dialog = view.document.querySelector('[role="dialog"]');
    const note = view.document.getElementById('kyc-review-note');
    assert.equal(view.document.activeElement, note, 'the recorded note control receives initial dialog focus');
    assert.equal(view.document.body.style.overflow, 'hidden', 'the shared dialog hook locks background scrolling');
    const escape = new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    note.dispatchEvent(escape);
    assert.equal(escape.defaultPrevented, true);
    assert.equal(closes, 1, 'Escape invokes the supplied recorded-review close action');

    await act(async () => {
      view.root.render(React.createElement(page.KycDocumentReviewDialog, {
        review: null,
        isSaving: false,
        onClose: () => {},
        onChange: () => {},
        onSubmit: () => {},
      }));
      await settle();
    });
    assert.equal(view.document.activeElement, trigger, 'closing restores focus to the opener');
    assert.equal(view.document.body.style.overflow, '', 'closing restores the prior scroll style');
    assert.ok(dialog, 'the test exercised the real dialog root before unmount');
  } finally {
    await view.close();
  }
});

test.after(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
});
