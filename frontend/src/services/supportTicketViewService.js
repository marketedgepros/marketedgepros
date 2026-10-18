import api from './api.js';

export const SUPPORT_TICKETS_ENDPOINT = '/support/tickets';
export const MY_SUPPORT_TICKETS_ENDPOINT = `${SUPPORT_TICKETS_ENDPOINT}/my`;
export const DEFAULT_TICKETS_PER_PAGE = 10;
export const MAX_TICKETS_PER_PAGE = 50;
export const DEFAULT_MESSAGES_PER_PAGE = 50;
export const MAX_MESSAGES_PER_PAGE = 100;
export const MAX_SUPPORT_PAGE = 1000;
export const MAX_TICKET_SUBJECT_LENGTH = 500;
export const MAX_TICKET_DESCRIPTION_LENGTH = 20000;
export const MAX_TICKET_MESSAGE_LENGTH = 4000;

// Customers can create only these established categories. Historical/server-side
// records may additionally contain KYC or withdrawal categories, which remain
// readable rather than being rewritten into a client fallback value.
export const CUSTOMER_TICKET_CATEGORIES = Object.freeze(['general', 'technical', 'billing', 'account']);
export const SUPPORT_TICKET_CATEGORIES = Object.freeze([...CUSTOMER_TICKET_CATEGORIES, 'kyc', 'withdrawal']);
export const CUSTOMER_TICKET_PRIORITIES = Object.freeze(['low', 'medium', 'high', 'urgent']);
export const CUSTOMER_TICKET_STATUSES = Object.freeze(['open', 'in_progress', 'waiting_customer', 'resolved', 'closed']);

const MAX_SUPPORT_ID = 2147483647;
const TICKET_NUMBER_PATTERN = /^[A-Za-z0-9_-]{1,20}$/;

export class SupportTicketContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'SupportTicketContractError';
  }
}

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isNonEmptyString = (value) => typeof value === 'string' && value.trim().length > 0;
const isPositiveInteger = (value) => Number.isSafeInteger(value) && value > 0 && value <= MAX_SUPPORT_ID;
const isNonNegativeInteger = (value) => Number.isSafeInteger(value) && value >= 0;
const isNullableTenantId = (value) => value === null || isPositiveInteger(value);

const requiredText = (value, field) => {
  if (!isNonEmptyString(value)) {
    throw new SupportTicketContractError(`Support ticket ${field} is unavailable`);
  }
  return value.trim();
};

const nullableText = (value, field) => {
  if (value === null) return null;
  return requiredText(value, field);
};

const boundedText = (value, field, maximum) => {
  const text = requiredText(value, field);
  if (text.length > maximum) {
    throw new RangeError(`Support ticket ${field} must not exceed ${maximum} characters`);
  }
  return text;
};

const boundedInteger = (value, fallback, maximum, field) => {
  const selected = value === undefined ? fallback : value;
  if (!isPositiveInteger(selected) || selected > maximum) {
    throw new RangeError(`${field} must be an integer from 1 to ${maximum}`);
  }
  return selected;
};

const ticketId = (value) => {
  if (!isPositiveInteger(value)) {
    throw new SupportTicketContractError('Support ticket id is unavailable');
  }
  return value;
};

const ticketNumber = (value) => {
  const number = requiredText(value, 'ticket_number');
  if (!TICKET_NUMBER_PATTERN.test(number)) {
    throw new SupportTicketContractError('Support ticket ticket_number is invalid');
  }
  return number;
};

const canonicalValue = (value, allowed, field, { nullable = false } = {}) => {
  if (nullable && value === null) return null;
  if (typeof value !== 'string' || !allowed.includes(value)) {
    throw new SupportTicketContractError(`Support ticket ${field} is invalid`);
  }
  return value;
};

const nullableRating = (value) => {
  if (value === null) return null;
  if (!Number.isInteger(value) || value < 1 || value > 5) {
    throw new SupportTicketContractError('Support ticket rating is invalid');
  }
  return value;
};

const apiData = (response) => {
  const data = response?.data;
  if (!isRecord(data)) {
    throw new SupportTicketContractError('Support ticket response is unavailable');
  }

  const apiError = isNonEmptyString(data.error)
    ? data.error.trim()
    : (data.success === false && isNonEmptyString(data.message) ? data.message.trim() : null);
  if (apiError) throw new Error(apiError);
  return data;
};

const ticketPayload = (payload) => (isRecord(payload.ticket) ? payload.ticket : payload);

const normalizeOwner = (value, label) => {
  if (!isRecord(value) || !hasOwn(value, 'user_id') || !hasOwn(value, 'tenant_id')) {
    throw new SupportTicketContractError(`${label} is incomplete`);
  }
  if (!isPositiveInteger(value.user_id) || !isNullableTenantId(value.tenant_id)) {
    throw new SupportTicketContractError(`${label} is invalid`);
  }
  return { user_id: value.user_id, tenant_id: value.tenant_id };
};

/** Strictly type an account hint before it can be used to validate a response. */
export const normalizeExpectedOwner = (expectedOwner) => normalizeOwner(expectedOwner, 'Expected owner');

/** British-spelling alias kept consistent with other UI-4 view adapters. */
export const normaliseExpectedOwner = normalizeExpectedOwner;

const assertResponseOwner = (payload, expectedOwner, label) => {
  if (expectedOwner === undefined) return null;
  const owner = normalizeOwner(payload?.owner_context, `${label} owner context`);
  if (owner.user_id !== expectedOwner.user_id || owner.tenant_id !== expectedOwner.tenant_id) {
    throw new SupportTicketContractError(`${label} owner context does not match the active account`);
  }
  return owner;
};

const normalizeOptionalExpectedOwner = (expectedOwner) => (
  expectedOwner === undefined ? undefined : normalizeExpectedOwner(expectedOwner)
);

/**
 * Builds the only UI principal accepted by customer-support pages. Authentication
 * may be true while its user record is still incomplete; that state is unavailable
 * and must not issue a private request.
 */
export const supportPrincipalFromAuth = (user, isAuthenticated) => {
  if (!isAuthenticated || !isRecord(user) || !hasOwn(user, 'tenant_id')
    || !isPositiveInteger(user.id) || !isNullableTenantId(user.tenant_id)
    || !isNonEmptyString(user.role)) {
    return null;
  }

  const owner = { user_id: user.id, tenant_id: user.tenant_id };
  const role = user.role.trim();
  return {
    owner,
    role,
    key: JSON.stringify([true, owner.user_id, owner.tenant_id, role]),
  };
};

const assertTicketOwner = (value, expectedOwner, label) => {
  if (expectedOwner === undefined) return;
  if (!isPositiveInteger(value.user_id) || value.user_id !== expectedOwner.user_id) {
    throw new SupportTicketContractError(`${label} belongs to a different account`);
  }
};

const normalizeMessage = (value, {
  expectedOwner,
  expectedTicketId,
  requireCustomerAuthor = false,
} = {}) => {
  if (!isRecord(value)) {
    throw new SupportTicketContractError('Support ticket message is unavailable');
  }
  if (value.is_internal !== false) {
    throw new SupportTicketContractError('Support ticket message is not customer-visible');
  }
  if (typeof value.is_staff !== 'boolean') {
    throw new SupportTicketContractError('Support ticket message staff flag is invalid');
  }

  const rawTicketId = ticketId(value.ticket_id);
  if (expectedTicketId !== undefined && rawTicketId !== ticketId(expectedTicketId)) {
    throw new SupportTicketContractError('Support ticket message does not match the requested ticket');
  }
  if (requireCustomerAuthor) {
    if (value.is_staff !== false || expectedOwner === undefined
      || !isPositiveInteger(value.user_id) || value.user_id !== expectedOwner.user_id) {
      throw new SupportTicketContractError('Support ticket message does not match the active account');
    }
  }

  return {
    id: ticketId(value.id),
    message: requiredText(value.message, 'message'),
    isStaff: value.is_staff,
    createdAt: requiredText(value.created_at, 'message created_at'),
  };
};

/**
 * Converts only customer-safe ticket fields. The raw user_id is checked when an
 * expected owner is supplied, but is intentionally never exposed to the view.
 */
export const normalizeSupportTicket = (value, {
  includeMessages = false,
  expectedOwner,
  ownerContext,
} = {}) => {
  if (!isRecord(value)) {
    throw new SupportTicketContractError('Support ticket is unavailable');
  }

  const owner = normalizeOptionalExpectedOwner(expectedOwner);
  if (owner !== undefined) {
    const responseOwner = normalizeOwner(
      ownerContext === undefined ? value.owner_context : ownerContext,
      'Support ticket owner context',
    );
    if (responseOwner.user_id !== owner.user_id || responseOwner.tenant_id !== owner.tenant_id) {
      throw new SupportTicketContractError('Support ticket owner context does not match the active account');
    }
  }
  assertTicketOwner(value, owner, 'Support ticket');

  const ticket = {
    id: ticketId(value.id),
    ticketNumber: ticketNumber(value.ticket_number),
    subject: requiredText(value.subject, 'subject'),
    description: requiredText(value.description, 'description'),
    category: canonicalValue(value.category, SUPPORT_TICKET_CATEGORIES, 'category'),
    // Legacy data may have no priority/rating; preserve null rather than inventing
    // medium or zero, and reject any unfamiliar non-null value.
    priority: canonicalValue(value.priority, CUSTOMER_TICKET_PRIORITIES, 'priority', { nullable: true }),
    status: canonicalValue(value.status, CUSTOMER_TICKET_STATUSES, 'status'),
    createdAt: requiredText(value.created_at, 'created_at'),
    updatedAt: nullableText(value.updated_at, 'updated_at'),
    firstResponseAt: nullableText(value.first_response_at, 'first_response_at'),
    resolvedAt: nullableText(value.resolved_at, 'resolved_at'),
    closedAt: nullableText(value.closed_at, 'closed_at'),
    rating: nullableRating(value.rating),
    feedback: nullableText(value.feedback, 'feedback'),
    // A list endpoint's preview can contain content that this UI is not allowed to show.
    lastMessage: null,
  };

  if (!includeMessages) return ticket;
  if (!Array.isArray(value.messages)) {
    throw new SupportTicketContractError('Support ticket messages are unavailable');
  }

  return {
    ...ticket,
    messages: value.messages
      .filter((message) => isRecord(message) && message.is_internal === false)
      .map((message) => normalizeMessage(message, { expectedTicketId: ticket.id })),
  };
};

const normalizePagination = (value, {
  totalField,
  totalLabel,
  maximumPerPage,
  requestedPage,
  requestedPerPage,
}) => {
  if (!isRecord(value)) {
    throw new SupportTicketContractError(`Support ticket ${totalLabel} pagination is unavailable`);
  }

  const page = value.page;
  const perPage = value.per_page;
  const total = value[totalField];
  const totalPages = value.total_pages;
  const expectedTotalPages = isPositiveInteger(perPage) && isNonNegativeInteger(total)
    ? Math.ceil(total / perPage)
    : null;
  const expectedHasNext = expectedTotalPages === null ? null : page < expectedTotalPages;
  const expectedHasPrev = page > 1;

  if (
    !isPositiveInteger(page)
    || !isPositiveInteger(perPage)
    || perPage > maximumPerPage
    || !isNonNegativeInteger(total)
    || !isNonNegativeInteger(totalPages)
    || typeof value.has_next !== 'boolean'
    || typeof value.has_prev !== 'boolean'
    || (requestedPage !== undefined && page !== requestedPage)
    || (requestedPerPage !== undefined && perPage !== requestedPerPage)
    || totalPages !== expectedTotalPages
    || value.has_next !== expectedHasNext
    || value.has_prev !== expectedHasPrev
  ) {
    throw new SupportTicketContractError(`Support ticket ${totalLabel} pagination is invalid`);
  }

  return { page, perPage, total, totalPages, hasNext: value.has_next, hasPrev: value.has_prev };
};

export const normalizeTicketPagination = (value, requested = {}) => {
  const pagination = normalizePagination(value, {
    totalField: 'total_tickets',
    totalLabel: 'ticket',
    maximumPerPage: MAX_TICKETS_PER_PAGE,
    requestedPage: requested.page,
    requestedPerPage: requested.perPage,
  });
  return {
    page: pagination.page,
    perPage: pagination.perPage,
    totalTickets: pagination.total,
    totalPages: pagination.totalPages,
    hasNext: pagination.hasNext,
    hasPrev: pagination.hasPrev,
  };
};

export const normalizeMessagePagination = (value, requested = {}) => {
  const pagination = normalizePagination(value, {
    totalField: 'total_messages',
    totalLabel: 'message',
    maximumPerPage: MAX_MESSAGES_PER_PAGE,
    requestedPage: requested.page,
    requestedPerPage: requested.perPage,
  });
  return {
    page: pagination.page,
    perPage: pagination.perPage,
    totalMessages: pagination.total,
    totalPages: pagination.totalPages,
    hasNext: pagination.hasNext,
    hasPrev: pagination.hasPrev,
  };
};

export const normalizeMySupportTickets = (payload, {
  page,
  perPage,
  expectedOwner,
} = {}) => {
  if (!isRecord(payload) || !Array.isArray(payload.tickets)) {
    throw new SupportTicketContractError('Support ticket list is unavailable');
  }
  const owner = normalizeOptionalExpectedOwner(expectedOwner);
  const ownerContext = assertResponseOwner(payload, owner, 'Support ticket list');
  const pagination = normalizeTicketPagination(payload.pagination, { page, perPage });
  if (payload.tickets.length > pagination.perPage) {
    throw new SupportTicketContractError('Support ticket list exceeds its requested page size');
  }

  return {
    tickets: payload.tickets.map((ticket) => normalizeSupportTicket(ticket, { expectedOwner: owner, ownerContext })),
    pagination,
    ...(ownerContext ? { ownerContext } : {}),
  };
};

export const normalizeSupportTicketDetail = (payload, {
  ticketNumber: expectedTicketNumber,
  page,
  perPage,
  expectedOwner,
} = {}) => {
  if (!isRecord(payload)) {
    throw new SupportTicketContractError('Support ticket detail is unavailable');
  }

  const owner = normalizeOptionalExpectedOwner(expectedOwner);
  const ownerContext = assertResponseOwner(payload, owner, 'Support ticket detail');
  const rawTicket = ticketPayload(payload);
  const messagePagination = payload.message_pagination ?? rawTicket.message_pagination;
  if (!isRecord(rawTicket) || (expectedTicketNumber !== undefined && rawTicket.ticket_number !== expectedTicketNumber)) {
    throw new SupportTicketContractError('Support ticket detail does not match the requested ticket');
  }
  if (!Array.isArray(rawTicket.messages)) {
    throw new SupportTicketContractError('Support ticket messages are unavailable');
  }
  const normalizedPagination = normalizeMessagePagination(messagePagination, { page, perPage });
  if (rawTicket.messages.length > normalizedPagination.perPage) {
    throw new SupportTicketContractError('Support ticket message list exceeds its requested page size');
  }

  return {
    ticket: normalizeSupportTicket(rawTicket, { includeMessages: true, expectedOwner: owner, ownerContext }),
    messagePagination: normalizedPagination,
    ...(ownerContext ? { ownerContext } : {}),
  };
};

const validateTicketDraft = (draft) => {
  if (!isRecord(draft)) {
    throw new SupportTicketContractError('Support ticket details are unavailable');
  }

  const category = canonicalValue(draft.category, CUSTOMER_TICKET_CATEGORIES, 'category');
  const priority = canonicalValue(draft.priority, CUSTOMER_TICKET_PRIORITIES, 'priority');
  return {
    subject: boundedText(draft.subject, 'subject', MAX_TICKET_SUBJECT_LENGTH),
    description: boundedText(draft.description, 'description', MAX_TICKET_DESCRIPTION_LENGTH),
    category,
    priority,
  };
};

const abortError = () => {
  const error = new Error('Support ticket request was cancelled.');
  error.name = 'AbortError';
  return error;
};

const observeAbort = (promise, signal) => {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort));
  });
};

const callApi = (apiClient, method, args, signal) => {
  if (!apiClient || typeof apiClient[method] !== 'function') {
    return Promise.reject(new SupportTicketContractError('Support ticket API client is unavailable'));
  }
  try {
    return observeAbort(Promise.resolve(apiClient[method](...args)), signal);
  } catch (error) {
    return Promise.reject(error);
  }
};

const requestConfig = (signal, { mutation = false, params } = {}) => ({
  ...(params ? { params } : {}),
  ...(signal ? { signal } : {}),
  // api.js supports this concrete opt-out. Never replay a support mutation after
  // a 401/refresh cycle because a server-side write outcome may be unknown.
  ...(mutation ? { _skipAuthRefresh: true } : {}),
});

const assertCreatedTicket = (ticket, draft) => {
  if (ticket.status !== 'open'
    || ticket.subject !== draft.subject
    || ticket.description !== draft.description
    || ticket.category !== draft.category
    || ticket.priority !== draft.priority) {
    throw new SupportTicketContractError('Created support ticket does not match the submitted details');
  }
  return ticket;
};

/** Create a customer-owned ticket. Account identity is always derived server-side. */
export const createMySupportTicket = async (draft, apiClient = api, { signal, expectedOwner } = {}) => {
  const payload = validateTicketDraft(draft);
  const owner = normalizeOptionalExpectedOwner(expectedOwner);
  const response = await callApi(
    apiClient,
    'post',
    [MY_SUPPORT_TICKETS_ENDPOINT, payload, requestConfig(signal, { mutation: true })],
    signal,
  );
  if (response?.status !== 201) {
    throw new SupportTicketContractError('Support ticket creation was not confirmed');
  }
  const data = apiData(response);
  const ownerContext = assertResponseOwner(data, owner, 'Support ticket creation');
  if (!isRecord(data.ticket)) {
    throw new SupportTicketContractError('Created support ticket is unavailable');
  }
  return assertCreatedTicket(
    normalizeSupportTicket(data.ticket, { expectedOwner: owner, ownerContext }),
    payload,
    ownerContext,
  );
};

/** Load one bounded current page of authenticated customer tickets. */
export const loadMySupportTickets = async (
  { page = 1, perPage = DEFAULT_TICKETS_PER_PAGE, status = null, signal, expectedOwner } = {},
  apiClient = api,
) => {
  const safePage = boundedInteger(page, 1, MAX_SUPPORT_PAGE, 'page');
  const safePerPage = boundedInteger(perPage, DEFAULT_TICKETS_PER_PAGE, MAX_TICKETS_PER_PAGE, 'per_page');
  const owner = normalizeOptionalExpectedOwner(expectedOwner);
  if (status !== null && status !== undefined && !CUSTOMER_TICKET_STATUSES.includes(status)) {
    throw new RangeError('Support ticket status is invalid');
  }

  const params = { page: safePage, per_page: safePerPage };
  if (status) params.status = status;
  const response = await callApi(apiClient, 'get', [MY_SUPPORT_TICKETS_ENDPOINT, requestConfig(signal, { params })], signal);
  return normalizeMySupportTickets(apiData(response), {
    page: safePage,
    perPage: safePerPage,
    expectedOwner: owner,
  });
};

/** Load exactly one bounded page of customer-visible messages for an owned ticket. */
export const loadMySupportTicketDetail = async (
  requestedTicketNumber,
  { page = 1, perPage = DEFAULT_MESSAGES_PER_PAGE, signal, expectedOwner } = {},
  apiClient = api,
) => {
  const safeTicketNumber = ticketNumber(requestedTicketNumber);
  const safePage = boundedInteger(page, 1, MAX_SUPPORT_PAGE, 'page');
  const safePerPage = boundedInteger(perPage, DEFAULT_MESSAGES_PER_PAGE, MAX_MESSAGES_PER_PAGE, 'per_page');
  const owner = normalizeOptionalExpectedOwner(expectedOwner);
  const response = await callApi(
    apiClient,
    'get',
    [`${SUPPORT_TICKETS_ENDPOINT}/${encodeURIComponent(safeTicketNumber)}`,
      requestConfig(signal, { params: { page: safePage, per_page: safePerPage } })],
    signal,
  );
  return normalizeSupportTicketDetail(apiData(response), {
    ticketNumber: safeTicketNumber,
    page: safePage,
    perPage: safePerPage,
    expectedOwner: owner,
  });
};

export const addMySupportTicketMessage = async (
  requestedTicketNumber,
  message,
  apiClient = api,
  { signal, expectedOwner, expectedTicketId } = {},
) => {
  const safeTicketNumber = ticketNumber(requestedTicketNumber);
  const owner = normalizeOptionalExpectedOwner(expectedOwner);
  const safeExpectedTicketId = expectedTicketId === undefined ? undefined : ticketId(expectedTicketId);
  const body = { message: boundedText(message, 'message', MAX_TICKET_MESSAGE_LENGTH) };
  const response = await callApi(
    apiClient,
    'post',
    [`${SUPPORT_TICKETS_ENDPOINT}/${encodeURIComponent(safeTicketNumber)}/messages`, body,
      requestConfig(signal, { mutation: true })],
    signal,
  );
  if (response?.status !== 201) {
    throw new SupportTicketContractError('Support ticket reply was not confirmed');
  }
  const data = apiData(response);
  assertResponseOwner(data, owner, 'Support ticket reply');
  if (!isRecord(data.ticket_message)) {
    throw new SupportTicketContractError('Created support ticket message is unavailable');
  }
  const created = normalizeMessage(data.ticket_message, {
    expectedOwner: owner,
    expectedTicketId: safeExpectedTicketId,
    requireCustomerAuthor: true,
  });
  if (created.message !== body.message) {
    throw new SupportTicketContractError('Created support ticket message does not match the submitted reply');
  }
  return created;
};

const updateTicketResponse = async (request, {
  expectedOwner,
  expectedId,
  expectedStatus,
  expectedRating,
  label,
} = {}) => {
  const response = await request;
  const data = apiData(response);
  const owner = normalizeOptionalExpectedOwner(expectedOwner);
  const ownerContext = assertResponseOwner(data, owner, label || 'Updated support ticket');
  if (!isRecord(data.ticket)) {
    throw new SupportTicketContractError('Updated support ticket is unavailable');
  }
  const updated = normalizeSupportTicket(data.ticket, { expectedOwner: owner, ownerContext });
  if (
    (expectedId !== undefined && updated.id !== ticketId(expectedId))
    || (expectedStatus !== undefined && updated.status !== expectedStatus)
    || (expectedRating !== undefined && updated.rating !== expectedRating)
  ) {
    throw new SupportTicketContractError('Updated support ticket does not match the requested mutation');
  }
  return updated;
};

export const closeMySupportTicket = (id, apiClient = api, { signal, expectedOwner } = {}) => {
  const safeId = ticketId(id);
  const owner = normalizeOptionalExpectedOwner(expectedOwner);
  return updateTicketResponse(
    callApi(
      apiClient,
      'post',
      [`${SUPPORT_TICKETS_ENDPOINT}/${safeId}/close`, {}, requestConfig(signal, { mutation: true })],
      signal,
    ),
    { expectedOwner: owner, expectedId: safeId, expectedStatus: 'closed', label: 'Support ticket close' },
  );
};

export const rateMySupportTicket = (id, rating, apiClient = api, { signal, expectedOwner } = {}) => {
  const safeId = ticketId(id);
  const owner = normalizeOptionalExpectedOwner(expectedOwner);
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
    throw new RangeError('Support ticket rating must be an integer from 1 to 5');
  }

  return updateTicketResponse(
    callApi(
      apiClient,
      'post',
      [`${SUPPORT_TICKETS_ENDPOINT}/${safeId}/rate`, { rating }, requestConfig(signal, { mutation: true })],
      signal,
    ),
    {
      expectedOwner: owner,
      expectedId: safeId,
      expectedStatus: 'closed',
      expectedRating: rating,
      label: 'Support ticket rating',
    },
  );
};

export const isSupportTicketRequestCanceled = (error) => (
  error?.code === 'ERR_CANCELED' || error?.name === 'AbortError' || error?.__CANCEL__ === true
);
