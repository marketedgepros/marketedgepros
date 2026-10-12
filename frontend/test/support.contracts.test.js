import assert from 'node:assert/strict';
import test from 'node:test';

const {
  CUSTOMER_TICKET_CATEGORIES,
  DEFAULT_MESSAGES_PER_PAGE,
  DEFAULT_TICKETS_PER_PAGE,
  MY_SUPPORT_TICKETS_ENDPOINT,
  SUPPORT_TICKETS_ENDPOINT,
  addMySupportTicketMessage,
  closeMySupportTicket,
  createMySupportTicket,
  loadMySupportTicketDetail,
  loadMySupportTickets,
  normalizeMySupportTickets,
  normalizeSupportTicket,
  rateMySupportTicket,
} = await import('../src/services/supportTicketViewService.js');

const owner = { user_id: 9, tenant_id: 4 };
const response = (data, status = 200) => ({ data, status, statusText: 'OK', headers: {} });

const ticket = (overrides = {}) => ({
  id: 41,
  ticket_number: 'TICKET-000041',
  user_id: owner.user_id,
  subject: 'Unable to log in',
  description: 'The account login page rejects a valid code.',
  category: 'account',
  priority: 'high',
  status: 'open',
  created_at: '2026-10-11T10:00:00Z',
  updated_at: '2026-10-11T10:05:00Z',
  first_response_at: null,
  resolved_at: null,
  closed_at: null,
  rating: null,
  feedback: null,
  last_message: { id: 999, message: 'This preview must not reach the list view.' },
  ...overrides,
});

const listPagination = (overrides = {}) => ({
  page: 1,
  per_page: DEFAULT_TICKETS_PER_PAGE,
  total_tickets: 1,
  total_pages: 1,
  has_next: false,
  has_prev: false,
  ...overrides,
});

const messagePagination = (overrides = {}) => ({
  page: 1,
  per_page: DEFAULT_MESSAGES_PER_PAGE,
  total_messages: 1,
  total_pages: 1,
  has_next: false,
  has_prev: false,
  ...overrides,
});

const message = (overrides = {}) => ({
  id: 52,
  ticket_id: 41,
  user_id: owner.user_id,
  message: 'A customer reply',
  is_staff: false,
  is_internal: false,
  created_at: '2026-10-11T10:20:00Z',
  ...overrides,
});

const listPayload = (overrides = {}) => ({
  tickets: [ticket()],
  pagination: listPagination(),
  owner_context: owner,
  ...overrides,
});

test('ticket creation sends only a canonical draft and proves 201/open/exact response fields', async () => {
  const calls = [];
  const client = {
    post: async (url, body, config) => {
      calls.push({ url, body, config });
      return response({ owner_context: owner, ticket: ticket() }, 201);
    },
  };

  const created = await createMySupportTicket({
    subject: ' Unable to log in ',
    description: ' The account login page rejects a valid code. ',
    category: 'account',
    priority: 'high',
    user_id: 123,
    tenant_id: 567,
    attachments: ['private'],
  }, client, { expectedOwner: owner });

  assert.equal(CUSTOMER_TICKET_CATEGORIES.includes('account'), true);
  assert.deepEqual(calls, [{
    url: MY_SUPPORT_TICKETS_ENDPOINT,
    body: {
      subject: 'Unable to log in',
      description: 'The account login page rejects a valid code.',
      category: 'account',
      priority: 'high',
    },
    config: { _skipAuthRefresh: true },
  }]);
  assert.equal(created.ticketNumber, 'TICKET-000041');
  assert.equal('userId' in created, false);
  assert.equal('lastMessage' in created, true);

  const wrongReceipt = {
    post: async () => response({ owner_context: owner, ticket: ticket({ status: 'resolved' }) }, 201),
  };
  await assert.rejects(
    () => createMySupportTicket({ subject: 'a', description: 'b', category: 'general', priority: 'medium' }, wrongReceipt, { expectedOwner: owner }),
    /does not match/i,
  );

  const notCreated = { post: async () => response({ owner_context: owner, ticket: ticket() }, 200) };
  await assert.rejects(
    () => createMySupportTicket({ subject: 'a', description: 'b', category: 'account', priority: 'high' }, notCreated, { expectedOwner: owner }),
    /not confirmed/i,
  );
});

test('list normalizer rejects missing/spoofed owner context and foreign raw ticket rows before projection', () => {
  const accepted = normalizeMySupportTickets(listPayload(), { page: 1, perPage: DEFAULT_TICKETS_PER_PAGE, expectedOwner: owner });
  assert.deepEqual(accepted.ownerContext, owner);
  assert.equal(accepted.tickets[0].lastMessage, null);

  assert.throws(
    () => normalizeMySupportTickets(listPayload({ owner_context: { user_id: 8, tenant_id: 4 } }), { expectedOwner: owner }),
    /owner context does not match/i,
  );
  assert.throws(
    () => normalizeMySupportTickets(listPayload({ owner_context: { user_id: 9 } }), { expectedOwner: owner }),
    /owner context is incomplete/i,
  );
  assert.throws(
    () => normalizeMySupportTickets(listPayload({ tickets: [ticket({ user_id: 8 })] }), { expectedOwner: owner }),
    /different account/i,
  );
});

test('list request is bounded and validates owner-backed canonical server values', async () => {
  const calls = [];
  const client = {
    get: async (url, config) => {
      calls.push({ url, config });
      return response(listPayload());
    },
  };
  const view = await loadMySupportTickets({
    page: 1,
    perPage: DEFAULT_TICKETS_PER_PAGE,
    status: 'open',
    expectedOwner: owner,
  }, client);

  assert.deepEqual(calls, [{
    url: MY_SUPPORT_TICKETS_ENDPOINT,
    config: { params: { page: 1, per_page: DEFAULT_TICKETS_PER_PAGE, status: 'open' } },
  }]);
  assert.equal(view.tickets[0].category, 'account');

  const nullableHistorical = normalizeSupportTicket(ticket({ category: 'kyc', priority: null, rating: null }), { expectedOwner: owner, ownerContext: owner });
  assert.equal(nullableHistorical.category, 'kyc');
  assert.equal(nullableHistorical.priority, null);
  assert.equal(nullableHistorical.rating, null);
  assert.throws(() => normalizeSupportTicket(ticket({ ticket_number: 'ticket 41' })), /ticket_number is invalid/i);
  assert.throws(() => normalizeSupportTicket(ticket({ status: 'new' })), /status is invalid/i);
});

test('detail validates owner, route ticket number, visible messages, and raw message ticket IDs', async () => {
  const calls = [];
  const client = {
    get: async (url, config) => {
      calls.push({ url, config });
      return response({
        ...ticket({ messages: [message({ is_staff: true, user_id: 77 }), message({ id: 53, is_internal: true })] }),
        owner_context: owner,
        message_pagination: messagePagination(),
      });
    },
  };
  const view = await loadMySupportTicketDetail('TICKET-000041', { expectedOwner: owner }, client);
  assert.equal(view.ticket.messages.length, 1);
  assert.equal(view.ticket.messages[0].isStaff, true);
  assert.deepEqual(calls[0], {
    url: `${SUPPORT_TICKETS_ENDPOINT}/TICKET-000041`,
    config: { params: { page: 1, per_page: DEFAULT_MESSAGES_PER_PAGE } },
  });

  const malformedMessage = {
    get: async () => response({
      ...ticket({ messages: [message({ ticket_id: 99 })] }),
      owner_context: owner,
      message_pagination: messagePagination(),
    }),
  };
  await assert.rejects(() => loadMySupportTicketDetail('TICKET-000041', { expectedOwner: owner }, malformedMessage), /does not match the requested ticket/i);

  let requestCount = 0;
  await assert.rejects(
    () => loadMySupportTicketDetail('not a valid ticket!', {}, { get: async () => { requestCount += 1; return response({}); } }),
    /ticket_number is invalid/i,
  );
  assert.equal(requestCount, 0);
});

test('reply requires owner_context, 201, exact customer text, ticket ID, user ID, and visibility flags', async () => {
  const calls = [];
  const client = {
    post: async (url, body, config) => {
      calls.push({ url, body, config });
      return response({ owner_context: owner, ticket_message: message() }, 201);
    },
  };
  const added = await addMySupportTicketMessage('TICKET-000041', ' A customer reply ', client, {
    expectedOwner: owner,
    expectedTicketId: 41,
  });
  assert.equal(added.message, 'A customer reply');
  assert.deepEqual(calls, [{
    url: `${SUPPORT_TICKETS_ENDPOINT}/TICKET-000041/messages`,
    body: { message: 'A customer reply' },
    config: { _skipAuthRefresh: true },
  }]);

  for (const bad of [
    { ticket_message: message({ user_id: 8 }) },
    { ticket_message: message({ ticket_id: 99 }) },
    { ticket_message: message({ is_staff: true }) },
    { ticket_message: message({ is_internal: null }) },
  ]) {
    await assert.rejects(
      () => addMySupportTicketMessage('TICKET-000041', 'A customer reply', { post: async () => response({ owner_context: owner, ...bad }, 201) }, { expectedOwner: owner, expectedTicketId: 41 }),
      /active account|requested ticket|customer-visible/i,
    );
  }
  await assert.rejects(
    () => addMySupportTicketMessage('TICKET-000041', 'A customer reply', { post: async () => response({ owner_context: owner, ticket_message: message() }, 200) }, { expectedOwner: owner, expectedTicketId: 41 }),
    /not confirmed/i,
  );
});

test('close and rating verify raw owner, exact ID/status/rating and suppress automatic auth refresh', async () => {
  const calls = [];
  const client = {
    post: async (url, body, config) => {
      calls.push({ url, body, config });
      return response({
        owner_context: owner,
        ticket: ticket({ status: 'closed', rating: url.endsWith('/rate') ? 5 : null }),
      });
    },
  };
  const closed = await closeMySupportTicket(41, client, { expectedOwner: owner });
  const rated = await rateMySupportTicket(41, 5, client, { expectedOwner: owner });
  assert.equal(closed.status, 'closed');
  assert.equal(rated.rating, 5);
  assert.deepEqual(calls.map((call) => [call.url, call.body, call.config]), [
    [`${SUPPORT_TICKETS_ENDPOINT}/41/close`, {}, { _skipAuthRefresh: true }],
    [`${SUPPORT_TICKETS_ENDPOINT}/41/rate`, { rating: 5 }, { _skipAuthRefresh: true }],
  ]);

  await assert.rejects(
    () => closeMySupportTicket(41, { post: async () => response({ owner_context: owner, ticket: ticket({ id: 99, status: 'closed' }) }) }, { expectedOwner: owner }),
    /does not match/i,
  );
  await assert.rejects(
    () => rateMySupportTicket(41, 5, { post: async () => response({ owner_context: owner, ticket: ticket({ status: 'closed', rating: 4 }) }) }, { expectedOwner: owner }),
    /does not match/i,
  );
});

test('compatibility callers may omit expectedOwner, while malformed nullable fields still fail closed', async () => {
  const client = { get: async () => response({ tickets: [ticket()], pagination: listPagination() }) };
  const view = await loadMySupportTickets({}, client);
  assert.equal(view.tickets.length, 1);
  assert.throws(() => normalizeSupportTicket(ticket({ priority: 'normal' })), /priority is invalid/i);
  assert.throws(() => normalizeSupportTicket(ticket({ rating: 0 })), /rating is invalid/i);
});
