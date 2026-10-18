import assert from 'node:assert/strict';
import test from 'node:test';
import { createAdminClosureCrmService, parseAdminClosureCrmRouteLeadId } from '../src/services/adminClosureCrmService.js';

test('CRM route identifiers normalize canonical Router strings while API identifier validation remains strict', async () => {
  assert.equal(parseAdminClosureCrmRouteLeadId('100'), 100);
  assert.equal(parseAdminClosureCrmRouteLeadId('1'), 1);
  assert.equal(parseAdminClosureCrmRouteLeadId('2147483647'), 2147483647);
  for (const value of ['', '0', '01', '-1', '1.2', '1e2', ' 100', '100 ', '١٠٠',
    '2147483648', '999999999999999999999', '100/notes', undefined, null, 100]) {
    assert.equal(parseAdminClosureCrmRouteLeadId(value), null, String(value));
  }
  const calls = [];
  const service = createAdminClosureCrmService({ get: async (...args) => { calls.push(args); } });
  await assert.rejects(service.loadLead({ expectedOwner: { user_id: 1, tenant_id: 1 },
    role: 'supermaster', leadId: '100' }));
  assert.deepEqual(calls, [], 'raw string API ID must still be rejected before transport');
});
