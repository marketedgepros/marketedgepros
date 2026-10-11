import assert from 'node:assert/strict';
import test from 'node:test';
import axios from 'axios';

const {
  CUSTOMER_TICKET_CATEGORIES,
  DEFAULT_MESSAGES_PER_PAGE,
  DEFAULT_TICKETS_PER_PAGE,
  MAX_SUPPORT_PAGE,
  MAX_TICKET_DESCRIPTION_LENGTH,
  MAX_TICKET_MESSAGE_LENGTH,
  MAX_TICKET_SUBJECT_LENGTH,
  MY_SUPPORT_TICKETS_ENDPOINT,
  SUPPORT_TICKETS_ENDPOINT,
  addMySupportTicketMessage,
  closeMySupportTicket,
  createMySupportTicket,
  loadMySupportTicketDetail,
  loadMySupportTickets,
  rateMySupportTicket,
} = await import('../src/services/supportTicketViewService.js');

const response = (config, data, status = 200) => ({
  config,
  data,
  headers: {},
  status,
  statusText: status >= 200 && status < 300 ? 'OK' : 'Error',
});

const clientWithAdapter = (adapter) => axios.create({ adapter });

const ticket = (overrides = {}) => ({
  id: 41,
  ticket_number: 'TICKET-000041',
  email: 'owner@example.test',
  name: 'Owner Name',
  subject: 'Unable to log in',
  description: 'The account login page rejects a valid code.',
  category: 'account',
  priority: 'high',
  status: 'open',
  created_at: '2026-10-11T10:00:00Z',
  updated_at: '2026-10-11T10:05:00Z',
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
  total_messages: 2,
  total_pages: 1,
  has_next: false,
  has_prev: false,
  ...overrides,
});

test('authenticated ticket creation posts only customer-safe fields to the same-origin /my endpoint', async () => {
  const calls = [];
  const client = clientWithAdapter(async (config) => {
    calls.push(config);
    return response(config, { ticket: ticket() }, 201);
  });

  const created = await createMySupportTicket({
    subject: ' Unable to log in ',
    description: ' The account login page rejects a valid code. ',
    category: 'account',
    priority: 'high',
    // A caller cannot smuggle ownership fields into the service payload.
    email: 'attacker@example.test',
    name: 'Attacker',
    attachments: ['https://example.test/file'],
  }, client);

  assert.equal(CUSTOMER_TICKET_CATEGORIES.includes('account'), true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, 'post');
  assert.equal(calls[0].url, MY_SUPPORT_TICKETS_ENDPOINT);
  assert.deepEqual(JSON.parse(calls[0].data), {
    subject: 'Unable to log in',
    description: 'The account login page rejects a valid code.',
    category: 'account',
    priority: 'high',
  });
  assert.equal(created.ticketNumber, 'TICKET-000041');
  assert.equal('email' in created, false);
  assert.equal('attachments' in created, false);
});

test('ticket list makes one bounded, cancelable request and hides last_message plus identity fields', async () => {
  const calls = [];
  const controller = new AbortController();
  const client = clientWithAdapter(async (config) => {
    calls.push(config);
    return response(config, {
      tickets: [ticket()],
      pagination: listPagination(),
    });
  });

  const view = await loadMySupportTickets({
    page: 1,
    perPage: DEFAULT_TICKETS_PER_PAGE,
    status: 'open',
    signal: controller.signal,
  }, client);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, 'get');
  assert.equal(calls[0].url, MY_SUPPORT_TICKETS_ENDPOINT);
  assert.deepEqual(calls[0].params, { page: 1, per_page: DEFAULT_TICKETS_PER_PAGE, status: 'open' });
  assert.equal(calls[0].signal, controller.signal);
  assert.deepEqual(view.pagination, {
    page: 1,
    perPage: DEFAULT_TICKETS_PER_PAGE,
    totalTickets: 1,
    totalPages: 1,
    hasNext: false,
    hasPrev: false,
  });
  assert.equal(view.tickets[0].lastMessage, null);
  assert.equal('email' in view.tickets[0], false);
  assert.equal('name' in view.tickets[0], false);
  assert.equal('attachments' in view.tickets[0], false);
});

test('ticket detail sends canonical page/per_page keys and fails closed for non-false internal flags', async () => {
  const calls = [];
  const client = clientWithAdapter(async (config) => {
    calls.push(config);
    return response(config, {
      ...ticket({
        messages: [
          {
            id: 12, message: 'Customer-safe staff reply', is_staff: true, is_internal: false,
            attachments: ['https://example.test/private-file'], created_at: '2026-10-11T10:10:00Z',
          },
          {
            id: 13, message: 'Internal staff note', is_staff: true, is_internal: true,
            created_at: '2026-10-11T10:12:00Z',
          },
          {
            id: 14, message: 'Legacy nullable note', is_staff: true, is_internal: null,
            created_at: '2026-10-11T10:13:00Z',
          },
          {
            id: 15, message: 'Missing visibility flag', is_staff: true,
            created_at: '2026-10-11T10:14:00Z',
          },
        ],
      }),
      // total_messages is server-side customer-visible count. A malformed raw
      // response may contain extra unsafe messages; the client filters it but
      // still only permits a raw page bounded by per_page.
      message_pagination: messagePagination({ total_messages: 1 }),
    });
  });

  const view = await loadMySupportTicketDetail('TICKET-000041', {
    page: 1,
    perPage: DEFAULT_MESSAGES_PER_PAGE,
  }, client);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `${SUPPORT_TICKETS_ENDPOINT}/TICKET-000041`);
  assert.deepEqual(calls[0].params, {
    page: 1,
    per_page: DEFAULT_MESSAGES_PER_PAGE,
  });
  assert.deepEqual(view.messagePagination, {
    page: 1,
    perPage: DEFAULT_MESSAGES_PER_PAGE,
    totalMessages: 1,
    totalPages: 1,
    hasNext: false,
    hasPrev: false,
  });
  assert.equal(view.ticket.messages.length, 1);
  assert.deepEqual(view.ticket.messages[0], {
    id: 12,
    message: 'Customer-safe staff reply',
    isStaff: true,
    createdAt: '2026-10-11T10:10:00Z',
  });
});

test('service rejects unbounded input and pages beyond the backend page cap before requests', async () => {
  const noRequestClient = clientWithAdapter(async () => {
    assert.fail('invalid client input must not issue a request');
  });

  await assert.rejects(
    () => loadMySupportTickets({ page: MAX_SUPPORT_PAGE + 1 }, noRequestClient),
    /page/,
  );
  await assert.rejects(
    () => loadMySupportTicketDetail('TICKET-000041', { page: MAX_SUPPORT_PAGE + 1 }, noRequestClient),
    /page/,
  );
  await assert.rejects(() => createMySupportTicket({
    subject: 's'.repeat(MAX_TICKET_SUBJECT_LENGTH + 1),
    description: 'valid description',
    category: 'general', priority: 'medium',
  }, noRequestClient), /subject/);
  await assert.rejects(() => createMySupportTicket({
    subject: 'valid subject',
    description: 'd'.repeat(MAX_TICKET_DESCRIPTION_LENGTH + 1),
    category: 'general', priority: 'medium',
  }, noRequestClient), /description/);
  await assert.rejects(
    () => addMySupportTicketMessage('TICKET-000041', 'm'.repeat(MAX_TICKET_MESSAGE_LENGTH + 1), noRequestClient),
    /message/,
  );
});

test('service rejects pagination echoes, excessive rows, and a detail for another ticket', async () => {
  const listEchoMismatch = clientWithAdapter(async (config) => response(config, {
    tickets: [], pagination: listPagination({ page: 2 }),
  }));
  await assert.rejects(
    () => loadMySupportTickets({ page: 1 }, listEchoMismatch),
    /pagination is invalid/,
  );

  const illogicalListPagination = clientWithAdapter(async (config) => response(config, {
    tickets: [], pagination: listPagination({ total_tickets: 11, total_pages: 1, has_next: false }),
  }));
  await assert.rejects(() => loadMySupportTickets({}, illogicalListPagination), /pagination is invalid/);

  const listTooManyRows = clientWithAdapter(async (config) => response(config, {
    tickets: Array.from({ length: DEFAULT_TICKETS_PER_PAGE + 1 }, () => ticket()),
    pagination: listPagination({ total_tickets: DEFAULT_TICKETS_PER_PAGE + 1, total_pages: 2, has_next: true }),
  }));
  await assert.rejects(() => loadMySupportTickets({}, listTooManyRows), /exceeds/);

  const wrongTicketDetail = clientWithAdapter(async (config) => response(config, {
    ...ticket({ ticket_number: 'TICKET-OTHER' }), messages: [], message_pagination: messagePagination({ total_messages: 0, total_pages: 0 }),
  }));
  await assert.rejects(
    () => loadMySupportTicketDetail('TICKET-000041', {}, wrongTicketDetail),
    /does not match/,
  );

  const tooManyRawMessages = clientWithAdapter(async (config) => response(config, {
    ...ticket({
      messages: Array.from({ length: DEFAULT_MESSAGES_PER_PAGE + 1 }, (_, index) => ({
        id: index + 1, message: `Message ${index}`, is_staff: false, is_internal: false,
        created_at: '2026-10-11T10:20:00Z',
      })),
    }),
    message_pagination: messagePagination({ total_messages: DEFAULT_MESSAGES_PER_PAGE + 1, total_pages: 2, has_next: true }),
  }));
  await assert.rejects(
    () => loadMySupportTicketDetail('TICKET-000041', {}, tooManyRawMessages),
    /exceeds/,
  );
});

test('message, close, and rating mutations use canonical routes and minimal bodies', async () => {
  const calls = [];
  const client = clientWithAdapter(async (config) => {
    calls.push(config);
    if (config.url.endsWith('/messages')) {
      return response(config, {
        ticket_message: {
          id: 52, message: 'A customer reply', is_staff: false, is_internal: false,
          created_at: '2026-10-11T10:20:00Z',
        },
      }, 201);
    }
    return response(config, { ticket: ticket({ status: 'closed', rating: config.url.endsWith('/rate') ? 5 : null }) });
  });

  const added = await addMySupportTicketMessage('TICKET-000041', ' A customer reply ', client);
  const closed = await closeMySupportTicket(41, client);
  const rated = await rateMySupportTicket(41, 5, client);

  assert.deepEqual(added, {
    id: 52, message: 'A customer reply', isStaff: false, createdAt: '2026-10-11T10:20:00Z',
  });
  assert.equal(closed.status, 'closed');
  assert.equal(rated.rating, 5);
  assert.deepEqual(calls.map((call) => call.url), [
    `${SUPPORT_TICKETS_ENDPOINT}/TICKET-000041/messages`,
    `${SUPPORT_TICKETS_ENDPOINT}/41/close`,
    `${SUPPORT_TICKETS_ENDPOINT}/41/rate`,
  ]);
  assert.deepEqual(JSON.parse(calls[0].data), { message: 'A customer reply' });
  assert.deepEqual(JSON.parse(calls[1].data), {});
  assert.deepEqual(JSON.parse(calls[2].data), { rating: 5 });
});

test('mutation responses must prove the expected ticket change or explicit customer visibility', async () => {
  const messageWithNullVisibility = clientWithAdapter(async (config) => response(config, {
    ticket_message: {
      id: 52, message: 'Unproven message', is_staff: false, is_internal: null,
      created_at: '2026-10-11T10:20:00Z',
    },
  }, 201));
  await assert.rejects(
    () => addMySupportTicketMessage('TICKET-000041', 'A customer reply', messageWithNullVisibility),
    /not customer-visible/,
  );

  const wrongClose = clientWithAdapter(async (config) => response(config, {
    ticket: ticket({ id: 99, status: 'open' }),
  }));
  await assert.rejects(() => closeMySupportTicket(41, wrongClose), /does not match/);

  const wrongRating = clientWithAdapter(async (config) => response(config, {
    ticket: ticket({ id: 41, status: 'closed', rating: 4 }),
  }));
  await assert.rejects(() => rateMySupportTicket(41, 5, wrongRating), /does not match/);
});

test('the service rejects logical error envelopes and preserves delayed Axios adapter request signals', async () => {
  const failureClient = clientWithAdapter(async (config) => response(config, { error: 'Ticket access denied' }));
  await assert.rejects(
    () => loadMySupportTickets({}, failureClient),
    /Ticket access denied/,
  );

  let delayedSignal = null;
  const delayedClient = clientWithAdapter(async (config) => {
    delayedSignal = config.signal;
    await new Promise((resolve) => setTimeout(resolve, 15));
    return response(config, { tickets: [], pagination: listPagination({ total_tickets: 0, total_pages: 0 }) });
  });
  const controller = new AbortController();
  const view = await loadMySupportTickets({ signal: controller.signal }, delayedClient);

  assert.equal(delayedSignal, controller.signal);
  assert.deepEqual(view.tickets, []);
  await assert.rejects(() => loadMySupportTickets({ perPage: 51 }, delayedClient), /per_page/);
  assert.throws(() => rateMySupportTicket(0, 5, delayedClient), /id/);
});
