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

export const CUSTOMER_TICKET_CATEGORIES = ['general', 'technical', 'billing', 'account'];
export const CUSTOMER_TICKET_PRIORITIES = ['low', 'medium', 'high', 'urgent'];
export const CUSTOMER_TICKET_STATUSES = ['open', 'in_progress', 'waiting_customer', 'resolved', 'closed'];

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isNonEmptyString = (value) => typeof value === 'string' && value.trim().length > 0;
const isPositiveInteger = (value) => Number.isSafeInteger(value) && value > 0;
const isNonNegativeInteger = (value) => Number.isSafeInteger(value) && value >= 0;

const requiredText = (value, field) => {
  if (!isNonEmptyString(value)) {
    throw new TypeError(`Support ticket ${field} is unavailable`);
  }
  return value.trim();
};

const optionalText = (value) => (isNonEmptyString(value) ? value.trim() : null);

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
    throw new TypeError('Support ticket id is unavailable');
  }
  return value;
};

const apiData = (response) => {
  const data = response?.data;
  if (!isRecord(data)) {
    throw new TypeError('Support ticket response is unavailable');
  }

  const apiError = optionalText(data.error) || (data.success === false ? optionalText(data.message) : null);
  if (apiError) {
    throw new Error(apiError);
  }
  return data;
};

const ticketPayload = (payload) => (isRecord(payload.ticket) ? payload.ticket : payload);

const normalizeMessage = (value) => {
  if (!isRecord(value)) {
    throw new TypeError('Support ticket message is unavailable');
  }
  // Customer endpoints only expose explicitly non-internal messages. A missing
  // or nullable flag must never be interpreted as a safe message.
  if (value.is_internal !== false) {
    throw new TypeError('Support ticket message is not customer-visible');
  }

  return {
    id: ticketId(value.id),
    message: requiredText(value.message, 'message'),
    isStaff: value.is_staff === true,
    createdAt: requiredText(value.created_at, 'message created_at'),
  };
};

/**
 * Convert only customer-safe public ticket fields into a view model. Deliberately
 * omit account email, assignee, attachments, and server-provided last_message.
 */
export const normalizeSupportTicket = (value, { includeMessages = false } = {}) => {
  if (!isRecord(value)) {
    throw new TypeError('Support ticket is unavailable');
  }

  const ticket = {
    id: ticketId(value.id),
    ticketNumber: requiredText(value.ticket_number, 'ticket_number'),
    subject: requiredText(value.subject, 'subject'),
    description: requiredText(value.description, 'description'),
    category: requiredText(value.category, 'category'),
    priority: requiredText(value.priority, 'priority'),
    status: requiredText(value.status, 'status'),
    createdAt: requiredText(value.created_at, 'created_at'),
    updatedAt: optionalText(value.updated_at),
    firstResponseAt: optionalText(value.first_response_at),
    resolvedAt: optionalText(value.resolved_at),
    closedAt: optionalText(value.closed_at),
    rating: Number.isInteger(value.rating) && value.rating >= 1 && value.rating <= 5 ? value.rating : null,
    feedback: optionalText(value.feedback),
    // Never use a list endpoint's possibly sensitive last_message preview.
    lastMessage: null,
  };

  if (!includeMessages) {
    return ticket;
  }

  if (!Array.isArray(value.messages)) {
    throw new TypeError('Support ticket messages are unavailable');
  }

  return {
    ...ticket,
    messages: value.messages
      .filter((message) => isRecord(message) && message.is_internal === false)
      .map(normalizeMessage),
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
    throw new TypeError(`Support ticket ${totalLabel} pagination is unavailable`);
  }

  const page = value.page;
  const perPage = value.per_page;
  const total = value[totalField];
  const totalPages = value.total_pages;
  const expectedTotalPages = isPositiveInteger(perPage) && isNonNegativeInteger(total)
    ? Math.ceil(total / perPage)
    : null;
  const expectedHasNext = expectedTotalPages === null ? null : page < expectedTotalPages;
  // Flask-SQLAlchemy exposes a previous page whenever the requested page is
  // greater than one, including an empty page beyond the final result page.
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
    throw new TypeError(`Support ticket ${totalLabel} pagination is invalid`);
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

export const normalizeMySupportTickets = (payload, requested = {}) => {
  if (!isRecord(payload) || !Array.isArray(payload.tickets)) {
    throw new TypeError('Support ticket list is unavailable');
  }
  const pagination = normalizeTicketPagination(payload.pagination, requested);
  if (payload.tickets.length > pagination.perPage) {
    throw new TypeError('Support ticket list exceeds its requested page size');
  }

  return {
    tickets: payload.tickets.map((ticket) => normalizeSupportTicket(ticket)),
    pagination,
  };
};

export const normalizeSupportTicketDetail = (payload, { ticketNumber, page, perPage } = {}) => {
  if (!isRecord(payload)) {
    throw new TypeError('Support ticket detail is unavailable');
  }

  const rawTicket = ticketPayload(payload);
  const messagePagination = payload.message_pagination ?? rawTicket.message_pagination;
  if (!isRecord(rawTicket) || (ticketNumber !== undefined && rawTicket.ticket_number !== ticketNumber)) {
    throw new TypeError('Support ticket detail does not match the requested ticket');
  }
  if (!Array.isArray(rawTicket.messages)) {
    throw new TypeError('Support ticket messages are unavailable');
  }
  const normalizedPagination = normalizeMessagePagination(messagePagination, { page, perPage });
  // The server's total_messages counts customer-visible messages. The raw page
  // may contain unsafe data from a faulty intermediary, so bound raw rows but
  // do not equate that count to the fail-closed filtered client view.
  if (rawTicket.messages.length > normalizedPagination.perPage) {
    throw new TypeError('Support ticket message list exceeds its requested page size');
  }

  return {
    ticket: normalizeSupportTicket(rawTicket, { includeMessages: true }),
    messagePagination: normalizedPagination,
  };
};

const validateTicketDraft = (draft) => {
  if (!isRecord(draft)) {
    throw new TypeError('Support ticket details are unavailable');
  }

  const category = requiredText(draft.category, 'category');
  const priority = requiredText(draft.priority, 'priority');
  if (!CUSTOMER_TICKET_CATEGORIES.includes(category)) {
    throw new RangeError('Support ticket category is invalid');
  }
  if (!CUSTOMER_TICKET_PRIORITIES.includes(priority)) {
    throw new RangeError('Support ticket priority is invalid');
  }

  return {
    subject: boundedText(draft.subject, 'subject', MAX_TICKET_SUBJECT_LENGTH),
    description: boundedText(draft.description, 'description', MAX_TICKET_DESCRIPTION_LENGTH),
    category,
    priority,
  };
};

const nonEmptyTicketNumber = (value) => requiredText(value, 'ticket_number');

/** Create a customer-owned ticket. Account identity is always derived server-side. */
export const createMySupportTicket = async (draft, apiClient = api, { signal } = {}) => {
  const response = await apiClient.post(
    MY_SUPPORT_TICKETS_ENDPOINT,
    validateTicketDraft(draft),
    signal ? { signal } : undefined,
  );
  const data = apiData(response);
  if (!isRecord(data.ticket)) {
    throw new TypeError('Created support ticket is unavailable');
  }
  return normalizeSupportTicket(data.ticket);
};

/** Load one bounded current page of authenticated customer tickets. */
export const loadMySupportTickets = async (
  { page = 1, perPage = DEFAULT_TICKETS_PER_PAGE, status = null, signal } = {},
  apiClient = api,
) => {
  const safePage = boundedInteger(page, 1, MAX_SUPPORT_PAGE, 'page');
  const safePerPage = boundedInteger(perPage, DEFAULT_TICKETS_PER_PAGE, MAX_TICKETS_PER_PAGE, 'per_page');
  if (status !== null && status !== undefined && !CUSTOMER_TICKET_STATUSES.includes(status)) {
    throw new RangeError('Support ticket status is invalid');
  }

  const params = { page: safePage, per_page: safePerPage };
  if (status) params.status = status;

  const response = await apiClient.get(MY_SUPPORT_TICKETS_ENDPOINT, signal ? { params, signal } : { params });
  return normalizeMySupportTickets(apiData(response), { page: safePage, perPage: safePerPage });
};

/** Load exactly one bounded page of customer-visible messages for an owned ticket. */
export const loadMySupportTicketDetail = async (
  ticketNumber,
  { page = 1, perPage = DEFAULT_MESSAGES_PER_PAGE, signal } = {},
  apiClient = api,
) => {
  const safeTicketNumber = nonEmptyTicketNumber(ticketNumber);
  const safePage = boundedInteger(page, 1, MAX_SUPPORT_PAGE, 'page');
  const safePerPage = boundedInteger(
    perPage,
    DEFAULT_MESSAGES_PER_PAGE,
    MAX_MESSAGES_PER_PAGE,
    'per_page',
  );
  const response = await apiClient.get(
    `${SUPPORT_TICKETS_ENDPOINT}/${encodeURIComponent(safeTicketNumber)}`,
    {
      params: { page: safePage, per_page: safePerPage },
      ...(signal ? { signal } : {}),
    },
  );
  return normalizeSupportTicketDetail(apiData(response), {
    ticketNumber: safeTicketNumber,
    page: safePage,
    perPage: safePerPage,
  });
};

export const addMySupportTicketMessage = async (ticketNumber, message, apiClient = api, { signal } = {}) => {
  const safeTicketNumber = nonEmptyTicketNumber(ticketNumber);
  const body = { message: boundedText(message, 'message', MAX_TICKET_MESSAGE_LENGTH) };
  const response = await apiClient.post(
    `${SUPPORT_TICKETS_ENDPOINT}/${encodeURIComponent(safeTicketNumber)}/messages`,
    body,
    signal ? { signal } : undefined,
  );
  const data = apiData(response);
  if (!isRecord(data.ticket_message)) {
    throw new TypeError('Created support ticket message is unavailable');
  }
  return normalizeMessage(data.ticket_message);
};

const updateTicketResponse = async (request, { expectedId, expectedStatus, expectedRating } = {}) => {
  const data = apiData(await request);
  if (!isRecord(data.ticket)) {
    throw new TypeError('Updated support ticket is unavailable');
  }
  const updated = normalizeSupportTicket(data.ticket);
  if (
    (expectedId !== undefined && updated.id !== expectedId)
    || (expectedStatus !== undefined && updated.status !== expectedStatus)
    || (expectedRating !== undefined && updated.rating !== expectedRating)
  ) {
    throw new TypeError('Updated support ticket does not match the requested mutation');
  }
  return updated;
};

export const closeMySupportTicket = (id, apiClient = api, { signal } = {}) => updateTicketResponse(
  apiClient.post(
    `${SUPPORT_TICKETS_ENDPOINT}/${ticketId(id)}/close`,
    {},
    signal ? { signal } : undefined,
  ),
  { expectedId: ticketId(id), expectedStatus: 'closed' },
);

export const rateMySupportTicket = (id, rating, apiClient = api, { signal } = {}) => {
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
    throw new RangeError('Support ticket rating must be an integer from 1 to 5');
  }

  return updateTicketResponse(apiClient.post(
    `${SUPPORT_TICKETS_ENDPOINT}/${ticketId(id)}/rate`,
    { rating },
    signal ? { signal } : undefined,
  ), { expectedId: ticketId(id), expectedStatus: 'closed', expectedRating: rating });
};

export const isSupportTicketRequestCanceled = (error) => (
  error?.code === 'ERR_CANCELED' || error?.name === 'AbortError'
);
