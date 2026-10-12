import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom';
import { transformWithEsbuild } from 'vite';

const listFile = new URL('../src/pages/user/MyChallenges.jsx', import.meta.url);
const detailFile = new URL('../src/pages/ChallengeDetails.jsx', import.meta.url);
const listTarget = new URL(`../src/pages/user/.ui4-challenge-list-${process.pid}.mjs`, import.meta.url);
const detailTarget = new URL(`../src/pages/.ui4-challenge-detail-${process.pid}.mjs`, import.meta.url);

const listSource = fs.readFileSync(listFile, 'utf8')
  .replace("from '../../services/api';", "from '../../services/api.js';")
  .replace("from '../../services/challengeViewService';", "from '../../services/challengeViewService.js';")
  .replace("from '../../store/authStore';", "from '../../store/authStore.js';");
const detailSource = fs.readFileSync(detailFile, 'utf8')
  .replace("from '../services/api';", "from '../services/api.js';")
  .replace("from '../services/challengeViewService';", "from '../services/challengeViewService.js';")
  .replace("from '../store/authStore';", "from '../store/authStore.js';");

const [compiledList, compiledDetail] = await Promise.all([
  transformWithEsbuild(listSource, listFile.pathname, { loader: 'jsx', jsx: 'automatic' }),
  transformWithEsbuild(detailSource, detailFile.pathname, { loader: 'jsx', jsx: 'automatic' }),
]);

let listModule;
let detailModule;
try {
  fs.writeFileSync(listTarget, compiledList.code);
  fs.writeFileSync(detailTarget, compiledDetail.code);
  [listModule, detailModule] = await Promise.all([
    import(`${listTarget.href}?ui4=${process.pid}`),
    import(`${detailTarget.href}?ui4=${process.pid}`),
  ]);
} finally {
  fs.rmSync(listTarget, { force: true });
  fs.rmSync(detailTarget, { force: true });
}

const withRouter = (element) => React.createElement(StaticRouter, { location: '/challenges' }, element);

test('UI4 challenge screens render role-appropriate unavailable status with real React markup and no network effect', () => {
  const unavailablePrincipal = {
    key: '[true,"number:9","null:null","string:master"]',
    ready: false,
    unavailableMessage: 'Recorded challenges are unavailable for this account role.',
  };
  const listHtml = renderToStaticMarkup(withRouter(
    React.createElement(listModule.MyChallengesContent, { principal: unavailablePrincipal }),
  ));
  const detailHtml = renderToStaticMarkup(withRouter(
    React.createElement(detailModule.ChallengeDetailsContent, { id: '41', principal: unavailablePrincipal }),
  ));

  assert.match(listHtml, /role="status"/);
  assert.match(listHtml, /Recorded challenges unavailable/);
  assert.match(detailHtml, /role="status"/);
  assert.match(detailHtml, /Recorded challenge details unavailable/);
  assert.doesNotMatch(`${listHtml}${detailHtml}`, /Unable to load/);
});

test('UI4 challenge principals are identity keyed by id, tenant, and role, never by a guessed tenant fallback', () => {
  const listPrincipal = listModule.challengePrincipalFromUser({ id: 9, tenant_id: null, role: 'trader' }, true);
  const changedTenant = listModule.challengePrincipalFromUser({ id: 9, tenant_id: 4, role: 'trader' }, true);
  const changedRole = listModule.challengePrincipalFromUser({ id: 9, tenant_id: null, role: 'master' }, true);
  const fallbackOnly = listModule.challengePrincipalFromUser({ id: 9, tenantId: 4, role: 'trader' }, true);
  const detailPrincipal = detailModule.challengeDetailPrincipalFromUser({ id: 9, tenant_id: null, role: 'trader' }, true);

  assert.equal(listPrincipal.ready, true);
  assert.deepEqual(listPrincipal.expectedOwner, { user_id: 9, tenant_id: null });
  assert.equal(fallbackOnly.ready, true);
  assert.deepEqual(fallbackOnly.expectedOwner, { user_id: 9, tenant_id: null });
  assert.notEqual(listPrincipal.key, changedTenant.key);
  assert.notEqual(listPrincipal.key, changedRole.key);
  assert.equal(changedRole.ready, false);
  assert.equal(detailPrincipal.key, listPrincipal.key);
  assert.equal(listModule.challengePrincipalFromUser({ id: '9', tenant_id: null, role: 'trader' }, true).ready, false);
});

test('UI4 challenge role gate matches protected non-admin account routes', () => {
  for (const role of ['trader', 'affiliate', 'guest']) {
    assert.equal(listModule.challengePrincipalFromUser({ id: 9, tenant_id: 7, role }, true).ready, true);
    assert.equal(detailModule.challengeDetailPrincipalFromUser({ id: 9, tenant_id: 7, role }, true).ready, true);
  }
  for (const role of ['master', 'supermaster', 'user', null]) {
    assert.equal(listModule.challengePrincipalFromUser({ id: 9, tenant_id: 7, role }, true).ready, false);
    assert.equal(detailModule.challengeDetailPrincipalFromUser({ id: 9, tenant_id: 7, role }, true).ready, false);
  }
  assert.equal(listModule.challengePrincipalFromUser({ id: 9, tenant_id: 7, role: 'trader' }, false).ready, false);
});
