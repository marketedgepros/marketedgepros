import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { JSDOM } from 'jsdom';
import React, { act } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';
import {
  AccountSetupContractError,
  createAccountSetupViewService,
  sanitiseDocumentSetupSummary,
} from '../src/services/accountSetupViewService.js';

const owner = Object.freeze({ userId: 41, tenantId: 7, role: 'user' });
const require = createRequire(import.meta.url);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'account-setup-'));
const guideSourceUrl = new URL('../src/components/account/AccountSetupGuide.jsx', import.meta.url);
const accountSetupServiceUrl = new URL('../src/services/accountSetupViewService.js', import.meta.url).href;
const external = Object.fromEntries(['react', 'react/jsx-runtime', 'lucide-react', 'react-router-dom']
  .map((name) => [name, pathToFileURL(require.resolve(name)).href]));
const resolveExternal = (text) => Object.entries(external).reduce(
  (current, [name, url]) => current
    .replaceAll(`from '${name}'`, `from ${JSON.stringify(url)}`)
    .replaceAll(`from "${name}"`, `from ${JSON.stringify(url)}`),
  text,
);
const guideSource = fs.readFileSync(guideSourceUrl, 'utf8')
  .replace("'../../services/accountSetupViewService.js'", JSON.stringify(accountSetupServiceUrl));
const guideCode = await transformWithEsbuild(resolveExternal(guideSource), guideSourceUrl.pathname, { loader: 'jsx', jsx: 'automatic' });
const guidePath = path.join(tmp, 'AccountSetupGuide.mjs');
fs.writeFileSync(guidePath, resolveExternal(guideCode.code));
const { default: AccountSetupGuide, AccountSetupGuideView, accountSetupNextAction } = await import(pathToFileURL(guidePath).href);

const fullProfile = (overrides = {}) => ({
  id: 41,
  tenant_id: 7,
  role: 'user',
  email: 'private-account@example.test',
  first_name: 'Ada',
  last_name: 'Lovelace',
  phone: '+12025550123',
  country_code: 'US',
  is_active: true,
  is_verified: true,
  two_factor_enabled: false,
  kyc_status: 'approved',
  avatar_url: null,
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: null,
  ...overrides,
});

const profileResponse = (user = fullProfile()) => ({ data: { user } });
const documentRow = (type, overrides = {}) => ({
  type,
  name: `private ${type} filename.pdf`,
  status: 'pending',
  uploaded_at: '2026-10-12T08:00:00Z',
  notes: 'private notes must not enter the guide state',
  url: `/api/v1/kyc/documents/41/${type}/download`,
  ...overrides,
});
const documentPayload = (documents) => ({
  overall_status: 'approved',
  statistics: { total: documents.length, uploaded: documents.length, approved: 0, pending: documents.length, rejected: 0 },
  documents,
});
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

function createService({ requestProfile, getDocuments }) {
  return createAccountSetupViewService({
    profileTransport: { request: requestProfile },
    documentsClient: { get: getDocuments },
  });
}

test('account setup service uses only the two owner-bound reads and keeps its ready summaries non-sensitive', async () => {
  const calls = [];
  const service = createService({
    requestProfile: async (request) => {
      calls.push(request);
      return profileResponse();
    },
    getDocuments: async (url, config) => {
      calls.push({ url, config });
      return { data: documentPayload([
        documentRow('id_proof'),
        documentRow('address_proof', { status: 'approved' }),
        documentRow('selfie'),
      ]) };
    },
  });

  const profile = await service.loadProfile(owner);
  const documents = await service.loadDocuments(owner);

  assert.deepEqual(calls.map((call) => call.path || call.url), ['/profile', '/kyc/documents']);
  assert.equal(calls[0].method, 'GET');
  assert.deepEqual(profile, {
    recordedFields: ['First name', 'Last name', 'Email address', 'Phone number'],
    missingFields: [],
  });
  assert.equal(documents.documentTypesShown, 3);
  assert.equal(documents.recordedCount, 3);
  assert.equal(documents.allRequestedRecordsPresent, true);
  assert.equal(documents.hasRejectedRecord, false);
  assert.deepEqual(documents.documents.map((row) => [row.type, row.state, row.status]), [
    ['id_proof', 'recorded', 'pending'],
    ['address_proof', 'recorded', 'approved'],
    ['selfie', 'recorded', 'pending'],
  ]);
  const serialized = JSON.stringify({ profile, documents });
  for (const privateValue of ['Ada', 'Lovelace', 'private-account@example.test', '+12025550123', 'filename', 'private notes', '/api/v1/kyc']) {
    assert.equal(serialized.includes(privateValue), false, `sanitized summary excludes ${privateValue}`);
  }
});

test('document summary distinguishes missing, rejected, unknown, and no-owner evidence without reading overall KYC state', () => {
  const summary = sanitiseDocumentSetupSummary(documentPayload([
    documentRow('id_proof', { url: null }),
    documentRow('address_proof', { status: 'rejected' }),
    documentRow('selfie', { status: 'mystery_review_state' }),
  ]), owner);
  assert.deepEqual(summary.documents.map((row) => [row.type, row.state, row.status]), [
    ['id_proof', 'unavailable', null],
    ['address_proof', 'needs-attention', 'rejected'],
    ['selfie', 'unavailable', null],
  ]);
  assert.equal(summary.recordedCount, 1);
  assert.equal(summary.hasRejectedRecord, true);
  assert.equal('overallStatus' in summary, false);

  const withoutOwnerEvidence = sanitiseDocumentSetupSummary(documentPayload([
    documentRow('id_proof', { url: null }),
    documentRow('address_proof', { url: null }),
    documentRow('selfie', { url: null }),
  ]), owner);
  assert.equal(withoutOwnerEvidence.recordedCount, 0);
  assert.ok(withoutOwnerEvidence.documents.every((row) => row.state === 'unavailable'));

  assert.throws(
    () => sanitiseDocumentSetupSummary(documentPayload([
      documentRow('id_proof', { url: '/api/v1/kyc/documents/99/id_proof/download' }),
    ]), owner),
    AccountSetupContractError,
  );
});

test('profile source requires strict id, tenant, and role equality rather than profile flags', async () => {
  const service = createService({
    requestProfile: async () => profileResponse(fullProfile({ role: 'trader', is_verified: true, kyc_status: 'approved' })),
    getDocuments: async () => ({ data: documentPayload([]) }),
  });
  await assert.rejects(() => service.loadProfile(owner), /authenticated account context/i);
});

test('cancelling either source rejects promptly and ignores an adapter response that arrives late', async () => {
  const profilePending = deferred();
  const documentsPending = deferred();
  const service = createService({
    requestProfile: () => profilePending.promise,
    getDocuments: () => documentsPending.promise,
  });
  const profileController = new AbortController();
  const documentsController = new AbortController();
  const profileRequest = service.loadProfile(owner, profileController.signal);
  const documentsRequest = service.loadDocuments(owner, documentsController.signal);
  profileController.abort();
  documentsController.abort();

  await assert.rejects(profileRequest, /cancelled/i);
  await assert.rejects(documentsRequest, /cancelled/i);
  profilePending.resolve(profileResponse());
  documentsPending.resolve({ data: documentPayload([documentRow('id_proof')]) });
  await Promise.resolve();
});

const bootstrap = new JSDOM('<!doctype html><body></body>');
Object.defineProperty(globalThis, 'window', { configurable: true, writable: true, value: bootstrap.window });
Object.defineProperty(globalThis, 'document', { configurable: true, writable: true, value: bootstrap.window.document });
const { createRoot } = await import('react-dom/client');
delete globalThis.window;
delete globalThis.document;
bootstrap.window.close();

function harness() {
  const dom = new JSDOM('<!doctype html><body><div id="root"></div></body>', { url: 'https://account-setup.test/' });
  const prior = new Map();
  for (const [key, value] of Object.entries({
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    Node: dom.window.Node,
    IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    prior.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  const root = createRoot(dom.window.document.getElementById('root'));
  return {
    host: dom.window.document.getElementById('root'),
    async render(component) {
      await act(async () => root.render(React.createElement(MemoryRouter, null, component)));
    },
    async settle() {
      await act(async () => {
        await Promise.resolve();
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    },
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

const click = async (element) => {
  assert.ok(element, 'expected an interactive element');
  await act(async () => element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true })));
};

function LocationProbe() {
  const location = useLocation();
  return React.createElement('output', { 'data-location': true }, location.pathname);
}

test('guide has bounded initial reads, toggle-only visibility, sanitized recorded text, and real Router destinations', async () => {
  const profileRead = deferred();
  const documentRead = deferred();
  const calls = [];
  const service = {
    loadProfile: (expectedOwner, signal) => {
      calls.push({ source: 'profile', expectedOwner, signal });
      return profileRead.promise;
    },
    loadDocuments: (expectedOwner, signal) => {
      calls.push({ source: 'documents', expectedOwner, signal });
      return documentRead.promise;
    },
  };
  const h = harness();
  try {
    await h.render(React.createElement(React.Fragment, null,
      React.createElement(AccountSetupGuide, { owner, dashboardCount: 1, service }),
      React.createElement(LocationProbe),
    ));
    assert.deepEqual(calls.map((call) => call.source), ['profile', 'documents']);
    const guide = h.host.querySelector('[aria-labelledby="getting-started-heading"]');
    const toggle = guide.querySelector('[aria-controls="account-starting-guide"]');
    await click(toggle);
    await click(toggle);
    assert.equal(calls.length, 2, 'showing or hiding the guide makes no read');

    await act(async () => {
      profileRead.resolve({ recordedFields: ['First name'], missingFields: ['Last name', 'Email address', 'Phone number'] });
      documentRead.resolve({
        documentTypesShown: 3,
        documents: [
          { type: 'id_proof', label: 'ID proof', state: 'recorded', status: 'pending' },
          { type: 'address_proof', label: 'Address proof', state: 'recorded', status: 'approved' },
          { type: 'selfie', label: 'Selfie with ID', state: 'recorded', status: 'pending' },
        ],
        recordedCount: 3,
        allRequestedRecordsPresent: true,
        hasRejectedRecord: false,
      });
    });
    await h.settle();
    assert.match(guide.textContent, /Fields recorded: First name/);
    assert.match(guide.textContent, /Upload records are present for all three document types shown in Documents/);
    assert.match(guide.textContent, /File-upload records are distinct from identity verification or a KYC provider decision/);
    assert.match(guide.textContent, /MT5 and KYC-provider capabilities are unavailable from this account workspace\. Payment availability is checked separately in an order checkout; a stored purchase does not activate trading or payouts\./);
    assert.doesNotMatch(guide.textContent, /KYC verified|identity verified|profile complete/i);
    assert.doesNotMatch(guide.textContent, /trading (?:account )?activated|payouts? enabled|payment enables trading/i);
    assert.equal([...guide.querySelectorAll('a')].find((node) => node.textContent.includes('Open Documents')).getAttribute('href'), '/documents');
    await click([...guide.querySelectorAll('a')].find((node) => node.textContent.includes('Open Documents')));
    assert.equal(h.host.querySelector('[data-location]').textContent, '/documents');
  } finally {
    await h.close();
  }
});

test('guide keeps source errors independent and retries only explicit source or refresh reads', async () => {
  const calls = { profile: 0, documents: 0 };
  const service = {
    loadProfile: async () => {
      calls.profile += 1;
      if (calls.profile === 1) throw new Error('private profile failure');
      return { recordedFields: ['First name'], missingFields: ['Last name', 'Email address', 'Phone number'] };
    },
    loadDocuments: async () => {
      calls.documents += 1;
      if (calls.documents === 1) throw new Error('private document failure');
      return { documentTypesShown: 3, documents: [], recordedCount: 0, allRequestedRecordsPresent: false, hasRejectedRecord: false };
    },
  };
  const h = harness();
  try {
    await h.render(React.createElement(AccountSetupGuide, { owner, dashboardCount: 0, service }));
    await h.settle();
    assert.equal(calls.profile, 1);
    assert.equal(calls.documents, 1);
    assert.match(h.host.textContent, /Profile record is unavailable/);
    assert.match(h.host.textContent, /Document records are unavailable/);
    assert.doesNotMatch(h.host.textContent, /private profile failure|private document failure/);

    await click([...h.host.querySelectorAll('button')].find((node) => node.textContent.includes('Retry profile check')));
    await h.settle();
    assert.deepEqual(calls, { profile: 2, documents: 1 }, 'profile retry does not retry documents');
    assert.match(h.host.textContent, /Fields recorded: First name/);
    assert.match(h.host.textContent, /Document records are unavailable/);

    await click([...h.host.querySelectorAll('button')].find((node) => node.textContent.includes('Refresh setup records')));
    await h.settle();
    assert.deepEqual(calls, { profile: 3, documents: 2 }, 'refresh issues at most one read for each source');
  } finally {
    await h.close();
  }
});

test('guide aborts old owner reads and never publishes late source state into a new identity', async () => {
  const reads = [];
  const service = {
    loadProfile: (expectedOwner, signal) => {
      const pending = deferred();
      reads.push({ source: 'profile', expectedOwner, signal, pending });
      return pending.promise;
    },
    loadDocuments: (expectedOwner, signal) => {
      const pending = deferred();
      reads.push({ source: 'documents', expectedOwner, signal, pending });
      return pending.promise;
    },
  };
  const h = harness();
  try {
    await h.render(React.createElement(AccountSetupGuide, { owner, dashboardCount: 0, service }));
    assert.equal(reads.length, 2);
    const nextOwner = { userId: 42, tenantId: 7, role: 'user' };
    await h.render(React.createElement(AccountSetupGuide, { owner: nextOwner, dashboardCount: 0, service }));
    assert.equal(reads.length, 4);
    assert.equal(reads[0].signal.aborted, true);
    assert.equal(reads[1].signal.aborted, true);

    await act(async () => {
      reads[0].pending.resolve({ recordedFields: ['OLD PROFILE MARKER'], missingFields: [] });
      reads[1].pending.resolve({ documentTypesShown: 3, documents: [], recordedCount: 0, allRequestedRecordsPresent: false, hasRejectedRecord: false });
    });
    await h.settle();
    assert.doesNotMatch(h.host.textContent, /OLD PROFILE MARKER/);

    await act(async () => {
      reads[2].pending.resolve({ recordedFields: ['New profile field'], missingFields: [] });
      reads[3].pending.resolve({ documentTypesShown: 3, documents: [], recordedCount: 0, allRequestedRecordsPresent: false, hasRejectedRecord: false });
    });
    await h.settle();
    assert.match(h.host.textContent, /New profile field/);
  } finally {
    await h.close();
  }
});

test('explicit not uploaded is distinct from absent rows, contradictory metadata and foreign optional document records', () => {
  const summary = sanitiseDocumentSetupSummary(documentPayload([
    documentRow('id_proof', { status: 'not_uploaded', uploaded_at: null, url: null }),
    documentRow('address_proof', { status: 'not_uploaded' }),
  ]), owner);
  assert.deepEqual(summary.documents.map((row) => [row.state, row.status]), [
    ['not-recorded', 'not_uploaded'], ['unavailable', null], ['unavailable', null],
  ]);
  assert.equal(summary.recordedCount, 0);
  assert.equal(summary.allRequestedRecordsPresent, false);
  assert.throws(() => sanitiseDocumentSetupSummary(documentPayload([
    documentRow('bank_statement', { url: '/api/v1/kyc/documents/99/bank_statement/download' }),
  ]), owner), AccountSetupContractError);
});

test('personal next action prioritizes actual missing/rejected/unavailable sources, not visits or verification flags', async () => {
  const readyProfile = { status: 'ready', summary: { recordedFields: ['First name', 'Last name', 'Email address', 'Phone number'], missingFields: [] } };
  const readyDocuments = { status: 'ready', summary: sanitiseDocumentSetupSummary(documentPayload([
    documentRow('id_proof'), documentRow('address_proof'), documentRow('selfie'),
  ]), owner) };
  const props = { profileSource: readyProfile, documentsSource: readyDocuments, dashboardCount: 0 };
  assert.equal(accountSetupNextAction(props).to, '/programs');
  assert.equal(accountSetupNextAction({ ...props, dashboardCount: 1 }).to, '/challenges');
  assert.match(accountSetupNextAction({ ...props, dashboardCount: null }).title, /availability/);
  assert.equal(accountSetupNextAction({ ...props, profileSource: { status: 'loading' } }).to, null);
  assert.match(accountSetupNextAction({ ...props, profileSource: { status: 'error' } }).title, /availability/);
  const missing = { status: 'ready', summary: { recordedFields: ['First name'], missingFields: ['Phone number'] } };
  assert.equal(accountSetupNextAction({ ...props, profileSource: missing }).to, '/profile');
  const needsUpload = { status: 'ready', summary: sanitiseDocumentSetupSummary(documentPayload([
    documentRow('id_proof', { status: 'not_uploaded', uploaded_at: null, url: null }),
    documentRow('address_proof'), documentRow('selfie'),
  ]), owner) };
  assert.match(accountSetupNextAction({ ...props, documentsSource: needsUpload }).title, /upload records/);
  const rejected = { status: 'ready', summary: sanitiseDocumentSetupSummary(documentPayload([
    documentRow('id_proof', { status: 'rejected' }), documentRow('address_proof'), documentRow('selfie'),
  ]), owner) };
  assert.equal(accountSetupNextAction({ ...props, documentsSource: rejected }).to, '/documents');
  const unavailable = { status: 'ready', summary: sanitiseDocumentSetupSummary(documentPayload([]), owner) };
  assert.match(accountSetupNextAction({ ...props, documentsSource: unavailable }).title, /status/);
  const h = harness();
  try {
    await h.render(React.createElement(React.Fragment, null,
      React.createElement(AccountSetupGuideView, { ...props, documentsSource: needsUpload, expanded: true, onToggle: () => {} }),
      React.createElement(LocationProbe),
    ));
    assert.match(h.host.textContent, /No upload recorded/);
    await click(h.host.querySelector('[aria-labelledby="setup-next-action-heading"] a'));
    assert.equal(h.host.querySelector('[data-location]').textContent, '/documents');
    await h.render(React.createElement(AccountSetupGuideView, { ...props, dashboardCount: null, expanded: true, onToggle: () => {} }));
    assert.match(h.host.textContent, /challenge count is unavailable/i);
    assert.doesNotMatch(h.host.textContent, /has no challenge records|0 challenge records/);
  } finally { await h.close(); }
});

test.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
