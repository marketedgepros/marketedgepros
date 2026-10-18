import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const service = fs.readFileSync(new URL('../src/services/supportTicketViewService.js', import.meta.url), 'utf8');
const createPage = fs.readFileSync(new URL('../src/pages/support/CreateTicket.jsx', import.meta.url), 'utf8');
const listPage = fs.readFileSync(new URL('../src/pages/support/MyTickets.jsx', import.meta.url), 'utf8');
const detailPage = fs.readFileSync(new URL('../src/pages/support/TicketDetail.jsx', import.meta.url), 'utf8');

const { normalizeExpectedOwner, supportPrincipalFromAuth } = await import('../src/services/supportTicketViewService.js');

test('UI4 support principal is typed and keys auth/user/tenant/role before private requests', () => {
  const principal = supportPrincipalFromAuth({ id: 9, tenant_id: null, role: 'trader' }, true);
  assert.deepEqual(principal.owner, { user_id: 9, tenant_id: null });
  assert.equal(principal.key, JSON.stringify([true, 9, null, 'trader']));
  for (const invalid of [
    [null, true],
    [{ id: '9', tenant_id: null, role: 'trader' }, true],
    [{ id: 9, tenant_id: undefined, role: 'trader' }, true],
    [{ id: 9, tenant_id: null, role: '' }, true],
    [{ id: 9, tenant_id: null, role: 'trader' }, false],
  ]) assert.equal(supportPrincipalFromAuth(...invalid), null);
  assert.deepEqual(normalizeExpectedOwner({ user_id: 9, tenant_id: 4 }), { user_id: 9, tenant_id: 4 });
  assert.throws(() => normalizeExpectedOwner({ user_id: 9 }), /incomplete/i);
});

test('support page sources pass expectedOwner, block unavailable private calls, and retain accessible controls', () => {
  assert.match(createPage, /if \(!expectedOwner\) return/);
  assert.match(createPage, /if \(mutationInFlightRef\.current\) return/);
  assert.match(createPage, /expectedOwner,/);
  assert.match(listPage, /if \(!expectedOwner\) \{/);
  assert.match(listPage, /expectedOwner,/);
  assert.match(listPage, /aria-pressed=\{statusFilter === filter\.value\}/);
  assert.match(detailPage, /if \(!expectedOwner\) return <Unavailable/);
  assert.match(detailPage, /expectedTicketId: ticket\.id/);
  assert.match(detailPage, /htmlFor="ticket-reply"/);
  assert.match(detailPage, /id="ticket-reply"/);
  assert.doesNotMatch(detailPage, /Ticket #\$\{ticket\.ticketNumber\}/);
  assert.doesNotMatch(detailPage, /description=\{ticket\.description\}/);
  assert.match(service, /_skipAuthRefresh: true/);
  assert.match(service, /TICKET_NUMBER_PATTERN/);
});
