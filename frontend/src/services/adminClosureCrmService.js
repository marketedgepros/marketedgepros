import api from "./api.js";
import { ADMIN_ROLES, ALL_ROLES, ROLES } from "../constants/roles.js";

export const ADMIN_CLOSURE_CRM_ENDPOINTS = Object.freeze({
  leads: "/crm/leads",
  stats: "/crm/stats",
  lead: (leadId) => `/crm/leads/${leadId}`,
  notes: (leadId) => `/crm/leads/${leadId}/notes`,
  activities: (leadId) => `/crm/leads/${leadId}/activities`,
  convert: (leadId) => `/crm/leads/${leadId}/convert`,
  lost: (leadId) => `/crm/leads/${leadId}/lost`,
});

export const ADMIN_CLOSURE_CRM_STATUSES = Object.freeze([
  "new", "contacted", "qualified", "proposal", "negotiation", "converted", "lost",
]);
export const ADMIN_CLOSURE_CRM_SOURCES = Object.freeze([
  "website", "referral", "affiliate", "social_media",
]);
export const ADMIN_CLOSURE_CRM_ACTIVITY_TYPES = Object.freeze(["call", "meeting", "follow_up", "other"]);
export const ADMIN_CLOSURE_CRM_PER_PAGE = 20;
export const ADMIN_CLOSURE_CRM_MAX_PAGE = 10000;
export const ADMIN_CLOSURE_CRM_MAX_PER_PAGE = 100;
export const ADMIN_CLOSURE_CRM_MAX_OFFSET = 10000;

/** The CRM contract returns an exact decimal or null, never a verified currency. */
export const formatAdminClosureCrmBudget = (budget) => (
  budget === null ? "Not specified" : `${budget} (currency unavailable)`
);

const ID_LIMIT = 2147483647;
const DECIMAL = /^(?:0|[1-9]\d*)(?:\.\d+)?$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$/;
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

export class AdminClosureCrmContractError extends Error {
  constructor(message) {
    super(message);
    this.name = "AdminClosureCrmContractError";
  }
}

const fail = (message) => { throw new AdminClosureCrmContractError(message); };
const requireRecord = (value, label) => {
  if (!isRecord(value)) fail(`${label} has an invalid shape.`);
  return value;
};
const requireArray = (value, label) => {
  if (!Array.isArray(value)) fail(`${label} has an invalid shape.`);
  return value;
};
const requirePositiveId = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > ID_LIMIT) fail(`${label} must be a bounded positive integer.`);
  return value;
};
/** React Router supplies strings; normalize only the route boundary, not API IDs. */
export const parseAdminClosureCrmRouteLeadId = (value) => {
  if (typeof value !== "string" || !/^[1-9][0-9]{0,9}$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id <= ID_LIMIT ? id : null;
};
const requireNonNegativeCount = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 0 || value > ID_LIMIT) fail(`${label} must be a bounded non-negative integer.`);
  return value;
};
const requireNullablePositiveId = (value, label) => (value === null ? null : requirePositiveId(value, label));
const requireNullableText = (value, label, maximum = 10000) => {
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0 || value.length > maximum || /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/.test(value)) {
    fail(`${label} must be bounded text or null.`);
  }
  return value;
};
const requireText = (value, label, maximum = 10000) => {
  const result = requireNullableText(value, label, maximum);
  if (result === null) fail(`${label} is required.`);
  return result;
};
const requireNullableDecimal = (value, label) => {
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0 || value.length > 128 || !DECIMAL.test(value)) {
    fail(`${label} must be an exact non-negative decimal string or null.`);
  }
  return value;
};
const requireNullableTimestamp = (value, label) => {
  if (value === null) return null;
  if (typeof value !== "string" || !ISO.test(value)) fail(`${label} must be a complete naive ISO timestamp or null.`);
  const date = new Date(`${value}Z`);
  if (Number.isNaN(date.getTime())) fail(`${label} must be a valid ISO timestamp or null.`);
  return value;
};
const requireEnum = (value, options, label) => {
  if (!options.includes(value)) fail(`${label} is unsupported.`);
  return value;
};

/** The active auth store is the independent source of principal identity. */
export const normalizeAdminClosureCrmExpectedOwner = (owner) => {
  const source = requireRecord(owner, "Expected CRM owner");
  const keys = Object.keys(source);
  if (keys.length !== 2 || !hasOwn(source, "user_id") || !hasOwn(source, "tenant_id")) {
    fail("Expected CRM owner contains fields outside its contract.");
  }
  return {
    user_id: requirePositiveId(source.user_id, "Expected CRM owner user ID"),
    tenant_id: requirePositiveId(source.tenant_id, "Expected CRM owner tenant ID"),
  };
};

export const adminClosureCrmIdentityKey = ({ isAuthenticated, userId, tenantId, role }) =>
  JSON.stringify([isAuthenticated === true, userId ?? null, tenantId ?? null, role ?? null]);

export const adminClosureCrmPrincipalFromAuth = (user, isAuthenticated) => {
  try {
    if (isAuthenticated !== true || !ALL_ROLES.includes(user?.role) || !ADMIN_ROLES.includes(user?.role)) return null;
    const owner = normalizeAdminClosureCrmExpectedOwner({ user_id: user?.id, tenant_id: user?.tenant_id });
    return {
      owner,
      role: user.role,
      key: adminClosureCrmIdentityKey({
        isAuthenticated, userId: owner.user_id, tenantId: owner.tenant_id, role: user.role,
      }),
    };
  } catch {
    return null;
  }
};

const requireAdminRole = (role) => {
  if (!ADMIN_ROLES.includes(role)) fail("CRM requires an existing admin role.");
  return role;
};
const normalizeOwnerContext = (value, expectedOwner) => {
  const received = normalizeAdminClosureCrmExpectedOwner(value);
  const expected = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
  if (received.user_id !== expected.user_id || received.tenant_id !== expected.tenant_id) {
    fail("CRM owner context does not match the active account.");
  }
  return received;
};
const boundedPositiveInteger = (value, label, maximum) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) fail(`${label} is out of range.`);
  return value;
};

export const buildAdminClosureCrmListParams = ({
  page = 1, perPage = ADMIN_CLOSURE_CRM_PER_PAGE, status = null, source = null, search = "",
} = {}) => {
  boundedPositiveInteger(page, "CRM page", ADMIN_CLOSURE_CRM_MAX_PAGE);
  boundedPositiveInteger(perPage, "CRM page size", ADMIN_CLOSURE_CRM_MAX_PER_PAGE);
  if ((page - 1) * perPage > ADMIN_CLOSURE_CRM_MAX_OFFSET) fail("CRM offset is out of range.");
  if (status !== null) requireEnum(status, ADMIN_CLOSURE_CRM_STATUSES, "CRM status filter");
  if (source !== null) requireEnum(source, ADMIN_CLOSURE_CRM_SOURCES, "CRM source filter");
  if (typeof search !== "string" || search.length > 100 || /[\u0000-\u001F\u007F]/.test(search)) fail("CRM search is invalid.");
  return {
    page,
    per_page: perPage,
    ...(status === null ? {} : { status }),
    ...(source === null ? {} : { source }),
    ...(search.length === 0 ? {} : { search }),
  };
};

const normalizeUser = (value, label) => {
  if (value === null) return null;
  const source = requireRecord(value, label);
  if (Object.keys(source).length !== 2 || !hasOwn(source, "id") || !hasOwn(source, "name")) fail(`${label} has unexpected fields.`);
  return { id: requirePositiveId(source.id, `${label} ID`), name: requireText(source.name, `${label} name`, 201) };
};

export const normalizeAdminClosureCrmLead = (value, { expectedLeadId = null } = {}) => {
  const source = requireRecord(value, "CRM lead");
  const allowed = [
    "id", "first_name", "last_name", "email", "phone", "country_code", "status", "source", "score",
    "assigned_to", "assigned_user", "interested_program_id", "budget", "company", "job_title", "notes", "tags",
    "next_follow_up", "converted_at", "lost_reason", "lost_at", "created_at", "updated_at", "notes_count", "activity_count",
  ];
  for (const key of Object.keys(source)) if (!allowed.includes(key)) fail("CRM lead contains unsupported fields.");
  for (const key of ["id", "first_name", "last_name", "email", "status", "source", "score", "assigned_to", "assigned_user", "interested_program_id", "budget", "company", "job_title", "notes", "tags", "next_follow_up", "converted_at", "lost_reason", "lost_at", "created_at", "updated_at"]) {
    if (!hasOwn(source, key)) fail(`CRM lead is missing ${key}.`);
  }
  const lead = {
    id: requirePositiveId(source.id, "CRM lead ID"),
    first_name: requireText(source.first_name, "CRM lead first name", 100),
    last_name: requireText(source.last_name, "CRM lead last name", 100),
    email: requireText(source.email, "CRM lead email", 255),
    phone: requireNullableText(source.phone, "CRM lead phone", 20),
    country_code: requireNullableText(source.country_code, "CRM lead country code", 2),
    status: requireEnum(source.status, ADMIN_CLOSURE_CRM_STATUSES, "CRM lead status"),
    source: requireText(source.source, "CRM lead source", 50),
    score: requireNonNegativeCount(source.score, "CRM lead score"),
    assigned_to: requireNullablePositiveId(source.assigned_to, "CRM lead assignee ID"),
    assigned_user: normalizeUser(source.assigned_user, "CRM lead assignee"),
    interested_program_id: requireNullablePositiveId(source.interested_program_id, "CRM lead program ID"),
    budget: requireNullableDecimal(source.budget, "CRM lead budget"),
    company: requireNullableText(source.company, "CRM lead company", 200),
    job_title: requireNullableText(source.job_title, "CRM lead job title", 100),
    notes: requireNullableText(source.notes, "CRM lead notes", 10000),
    tags: requireArray(source.tags, "CRM lead tags").map((tag) => requireText(tag, "CRM lead tag", 500)),
    next_follow_up: requireNullableTimestamp(source.next_follow_up, "CRM lead follow-up time"),
    converted_at: requireNullableTimestamp(source.converted_at, "CRM lead conversion time"),
    lost_reason: requireNullableText(source.lost_reason, "CRM lead lost reason", 50),
    lost_at: requireNullableTimestamp(source.lost_at, "CRM lead lost time"),
    created_at: requireNullableTimestamp(source.created_at, "CRM lead creation time"),
    updated_at: requireNullableTimestamp(source.updated_at, "CRM lead update time"),
  };
  if (lead.score > 100) fail("CRM lead score is out of range.");
  if ((lead.assigned_to === null) !== (lead.assigned_user === null)) fail("CRM lead assignee identity is inconsistent.");
  if (expectedLeadId !== null && lead.id !== requirePositiveId(expectedLeadId, "Expected CRM lead ID")) fail("CRM lead ID does not match the request.");
  if (hasOwn(source, "notes_count")) lead.notes_count = requireNonNegativeCount(source.notes_count, "CRM notes count");
  if (hasOwn(source, "activity_count")) lead.activity_count = requireNonNegativeCount(source.activity_count, "CRM activity count");
  return lead;
};

const normalizePagination = (value, params, rowCount) => {
  const source = requireRecord(value, "CRM pagination");
  if (Object.keys(source).length !== 4 || !["page", "per_page", "total", "pages"].every((key) => hasOwn(source, key))) fail("CRM pagination has unexpected fields.");
  const page = boundedPositiveInteger(source.page, "CRM response page", ADMIN_CLOSURE_CRM_MAX_PAGE);
  const perPage = boundedPositiveInteger(source.per_page, "CRM response page size", ADMIN_CLOSURE_CRM_MAX_PER_PAGE);
  const total = requireNonNegativeCount(source.total, "CRM response total");
  const pages = requireNonNegativeCount(source.pages, "CRM response pages");
  if (page !== params.page || perPage !== params.per_page) fail("CRM pagination does not match the request.");
  if (pages !== Math.ceil(total / perPage)) fail("CRM pagination is inconsistent.");
  const expectedRows = Math.min(perPage, Math.max(0, total - (page - 1) * perPage));
  if (rowCount !== expectedRows) fail("CRM page rows do not match its total.");
  return { page, per_page: perPage, total, pages };
};

export const normalizeAdminClosureCrmList = (payload, { expectedOwner, params }) => {
  const source = requireRecord(payload, "CRM list response");
  for (const key of ["owner_context", "leads", "pagination", "filters"]) if (!hasOwn(source, key)) fail(`CRM list response is missing ${key}.`);
  const leads = requireArray(source.leads, "CRM leads").map((lead) => normalizeAdminClosureCrmLead(lead));
  if (new Set(leads.map((lead) => lead.id)).size !== leads.length) fail("CRM list contains duplicate IDs.");
  const pagination = normalizePagination(source.pagination, params, leads.length);
  const filters = requireRecord(source.filters, "CRM filters");
  if (Object.keys(filters).length !== 3 || !["status", "source", "search"].every((key) => hasOwn(filters, key))) fail("CRM filters have unexpected fields.");
  if (filters.status !== (params.status ?? null) || filters.source !== (params.source ?? null) || filters.search !== (params.search ?? "")) fail("CRM filters do not echo the request.");
  if (leads.some((lead) => params.status !== undefined && lead.status !== params.status)) fail("CRM list contains a non-matching status.");
  if (leads.some((lead) => params.source !== undefined && lead.source !== params.source)) fail("CRM list contains a non-matching source.");
  return { ownerContext: normalizeOwnerContext(source.owner_context, expectedOwner), leads, pagination, filters: { ...filters } };
};

export const normalizeAdminClosureCrmStats = (payload, { expectedOwner }) => {
  const source = requireRecord(payload, "CRM stats response");
  const required = ["owner_context", "total_leads", "new_leads", "contacted_leads", "qualified_leads", "converted_leads", "lost_leads"];
  if (!required.every((key) => hasOwn(source, key))) fail("CRM stats response is incomplete.");
  const stats = {
    total: requireNonNegativeCount(source.total_leads, "CRM total leads"),
    new: requireNonNegativeCount(source.new_leads, "CRM new leads"),
    contacted: requireNonNegativeCount(source.contacted_leads, "CRM contacted leads"),
    qualified: requireNonNegativeCount(source.qualified_leads, "CRM qualified leads"),
    converted: requireNonNegativeCount(source.converted_leads, "CRM converted leads"),
    lost: requireNonNegativeCount(source.lost_leads, "CRM lost leads"),
  };
  if (Object.values(stats).slice(1).reduce((sum, item) => sum + item, 0) > stats.total) fail("CRM stats exceed the total.");
  return { ownerContext: normalizeOwnerContext(source.owner_context, expectedOwner), stats };
};

export const normalizeAdminClosureCrmDetail = (payload, { expectedOwner, expectedLeadId }) => {
  const source = requireRecord(payload, "CRM lead detail response");
  if (!hasOwn(source, "owner_context")) fail("CRM lead detail has no owner context.");
  const { owner_context: ownerContext, ...leadPayload } = source;
  return { ownerContext: normalizeOwnerContext(ownerContext, expectedOwner), lead: normalizeAdminClosureCrmLead(leadPayload, { expectedLeadId }) };
};

const normalizeNote = (value, expectedLeadId) => {
  const source = requireRecord(value, "CRM note");
  const keys = ["id", "lead_id", "content", "created_at", "created_by"];
  if (Object.keys(source).length !== keys.length || !keys.every((key) => hasOwn(source, key))) fail("CRM note has unexpected fields.");
  const note = {
    id: requirePositiveId(source.id, "CRM note ID"),
    lead_id: requirePositiveId(source.lead_id, "CRM note lead ID"),
    content: requireText(source.content, "CRM note content", 10000),
    created_at: requireNullableTimestamp(source.created_at, "CRM note timestamp"),
    created_by: (() => {
      const name = requireNullableText(source.created_by, "CRM note creator", 201);
      return name === null ? null : { name };
    })(),
  };
  if (note.lead_id !== requirePositiveId(expectedLeadId, "Expected CRM note lead ID")) fail("CRM note does not belong to the requested lead.");
  return note;
};
const normalizeActivity = (value, expectedLeadId) => {
  const source = requireRecord(value, "CRM activity");
  const keys = ["id", "lead_id", "activity_type", "subject", "description", "outcome", "scheduled_at", "completed", "completed_at", "created_at", "created_by"];
  if (Object.keys(source).length !== keys.length || !keys.every((key) => hasOwn(source, key))) fail("CRM activity has unexpected fields.");
  const activity = {
    id: requirePositiveId(source.id, "CRM activity ID"),
    lead_id: requirePositiveId(source.lead_id, "CRM activity lead ID"),
    activity_type: requireText(source.activity_type, "CRM activity type", 50),
    subject: requireNullableText(source.subject, "CRM activity subject", 200),
    description: requireNullableText(source.description, "CRM activity description", 10000),
    outcome: requireNullableText(source.outcome, "CRM activity outcome", 50),
    scheduled_at: requireNullableTimestamp(source.scheduled_at, "CRM activity scheduled time"),
    completed: source.completed === true,
    completed_at: requireNullableTimestamp(source.completed_at, "CRM activity completed time"),
    created_at: requireNullableTimestamp(source.created_at, "CRM activity creation time"),
    created_by: normalizeUser(source.created_by, "CRM activity creator"),
  };
  if (typeof source.completed !== "boolean") fail("CRM activity completed state is invalid.");
  if (activity.lead_id !== requirePositiveId(expectedLeadId, "Expected CRM activity lead ID")) fail("CRM activity does not belong to the requested lead.");
  return activity;
};
const normalizeChildResponse = (payload, expectedOwner, expectedLeadId, key, normalizer) => {
  const source = requireRecord(payload, `CRM ${key} response`);
  if (!hasOwn(source, "owner_context") || !hasOwn(source, key) || !hasOwn(source, "pagination")) fail(`CRM ${key} response is incomplete.`);
  const params = { page: 1, per_page: ADMIN_CLOSURE_CRM_PER_PAGE };
  const rows = requireArray(source[key], `CRM ${key}`).map((item) => normalizer(item, expectedLeadId));
  return {
    ownerContext: normalizeOwnerContext(source.owner_context, expectedOwner),
    [key]: rows,
    pagination: normalizePagination(source.pagination, params, rows.length),
  };
};

const requireUpdatePayload = (value) => {
  const source = requireRecord(value, "CRM update");
  const allowed = new Set(["status", "score", "budget", "notes", "next_follow_up", "expected_updated_at"]);
  const keys = Object.keys(source);
  if (keys.length === 0 || keys.some((key) => !allowed.has(key))) fail("CRM update contains unsupported fields.");
  const result = {};
  if (hasOwn(source, "status")) result.status = requireEnum(source.status, ADMIN_CLOSURE_CRM_STATUSES, "CRM update status");
  if (hasOwn(source, "score")) {
    result.score = requireNonNegativeCount(source.score, "CRM update score");
    if (result.score > 100) fail("CRM update score is out of range.");
  }
  if (hasOwn(source, "budget")) result.budget = requireNullableDecimal(source.budget, "CRM update budget");
  if (hasOwn(source, "notes")) result.notes = requireNullableText(source.notes, "CRM update notes", 10000);
  if (hasOwn(source, "next_follow_up")) result.next_follow_up = requireNullableTimestamp(source.next_follow_up, "CRM update follow-up time");
  if (!hasOwn(source, "expected_updated_at")) fail("CRM update requires the loaded lead version.");
  result.expected_updated_at = requireNullableTimestamp(source.expected_updated_at, "CRM expected update time");
  return result;
};
const requireCreatePayload = (value) => {
  const source = requireRecord(value, "CRM create");
  const allowed = new Set(["first_name", "last_name", "email", "phone", "company", "source", "status", "budget"]);
  if (Object.keys(source).some((key) => !allowed.has(key))) fail("CRM create contains unsupported fields.");
  const result = {
    first_name: requireText(source.first_name?.trim(), "CRM first name", 100),
    last_name: requireText(source.last_name?.trim(), "CRM last name", 100),
    email: requireText(source.email?.trim(), "CRM email", 255),
    source: source.source === undefined ? "website" : requireEnum(source.source, ADMIN_CLOSURE_CRM_SOURCES, "CRM source"),
    status: source.status === undefined ? "new" : requireEnum(source.status, ADMIN_CLOSURE_CRM_STATUSES, "CRM status"),
  };
  if (source.phone !== undefined) result.phone = requireNullableText(source.phone === "" ? null : source.phone.trim(), "CRM phone", 20);
  if (source.company !== undefined) result.company = requireNullableText(source.company === "" ? null : source.company.trim(), "CRM company", 200);
  if (source.budget !== undefined) result.budget = requireNullableDecimal(source.budget === "" ? null : source.budget, "CRM budget");
  return result;
};
const requireNotePayload = (content) => ({ content: requireText(content?.trim(), "CRM note", 10000) });
const requireActivityPayload = (value) => {
  const source = requireRecord(value, "CRM activity create");
  const allowed = new Set(["activity_type", "subject", "description", "outcome", "scheduled_at"]);
  if (Object.keys(source).some((key) => !allowed.has(key))) fail("CRM activity contains unsupported fields.");
  const result = {
    activity_type: requireEnum(source.activity_type, ADMIN_CLOSURE_CRM_ACTIVITY_TYPES, "CRM activity type"),
    description: requireText(source.description?.trim() || "Follow-up activity", "CRM activity description", 10000),
  };
  if (source.subject !== undefined) result.subject = requireNullableText(source.subject === "" ? null : source.subject.trim(), "CRM activity subject", 200);
  if (source.outcome !== undefined) result.outcome = requireNullableText(source.outcome === "" ? null : source.outcome.trim(), "CRM activity outcome", 50);
  if (source.scheduled_at !== undefined) result.scheduled_at = requireNullableTimestamp(source.scheduled_at, "CRM activity time");
  return result;
};

const normalizeLeadMutation = (payload, expectedOwner, expectedLeadId) => {
  const source = requireRecord(payload, "CRM lead mutation response");
  if (!hasOwn(source, "owner_context") || !hasOwn(source, "lead")) fail("CRM lead mutation response is incomplete.");
  return {
    ownerContext: normalizeOwnerContext(source.owner_context, expectedOwner),
    lead: normalizeAdminClosureCrmLead(source.lead, { expectedLeadId }),
  };
};
const normalizeNoteMutation = (payload, expectedOwner, expectedLeadId) => {
  const source = requireRecord(payload, "CRM note mutation response");
  if (!hasOwn(source, "owner_context") || !hasOwn(source, "note")) fail("CRM note mutation response is incomplete.");
  return { ownerContext: normalizeOwnerContext(source.owner_context, expectedOwner), note: normalizeNote(source.note, expectedLeadId) };
};
const normalizeActivityMutation = (payload, expectedOwner, expectedLeadId) => {
  const source = requireRecord(payload, "CRM activity mutation response");
  if (!hasOwn(source, "owner_context") || !hasOwn(source, "activity")) fail("CRM activity mutation response is incomplete.");
  return { ownerContext: normalizeOwnerContext(source.owner_context, expectedOwner), activity: normalizeActivity(source.activity, expectedLeadId) };
};

const abortError = () => {
  const error = new Error("CRM request was cancelled.");
  error.name = "AbortError";
  return error;
};
const throwIfAborted = (signal) => { if (signal?.aborted) throw abortError(); };
const transportConfig = (signal, extra = {}) => ({ signal, _skipAuthRefresh: true, ...extra });

/** Injectable, one-shot client; all reads and writes prevent automatic 401 replay. */
export const createAdminClosureCrmService = (client = api) => {
  const loadLeads = async ({ expectedOwner, role, signal, ...options } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const params = buildAdminClosureCrmListParams(options);
    throwIfAborted(signal);
    const response = await client.get(ADMIN_CLOSURE_CRM_ENDPOINTS.leads, transportConfig(signal, { params }));
    throwIfAborted(signal);
    return normalizeAdminClosureCrmList(response?.data, { expectedOwner: owner, params });
  };
  const loadStats = async ({ expectedOwner, role, signal } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    requireAdminRole(role);
    throwIfAborted(signal);
    const response = await client.get(ADMIN_CLOSURE_CRM_ENDPOINTS.stats, transportConfig(signal));
    throwIfAborted(signal);
    return normalizeAdminClosureCrmStats(response?.data, { expectedOwner: owner });
  };
  const loadLead = async ({ expectedOwner, role, leadId, signal } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const id = requirePositiveId(leadId, "CRM requested lead ID");
    throwIfAborted(signal);
    const response = await client.get(ADMIN_CLOSURE_CRM_ENDPOINTS.lead(id), transportConfig(signal));
    throwIfAborted(signal);
    return normalizeAdminClosureCrmDetail(response?.data, { expectedOwner: owner, expectedLeadId: id });
  };
  const loadNotes = async ({ expectedOwner, role, leadId, signal } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const id = requirePositiveId(leadId, "CRM requested lead ID");
    throwIfAborted(signal);
    const response = await client.get(ADMIN_CLOSURE_CRM_ENDPOINTS.notes(id), transportConfig(signal, { params: { page: 1, per_page: ADMIN_CLOSURE_CRM_PER_PAGE } }));
    throwIfAborted(signal);
    return normalizeChildResponse(response?.data, owner, id, "notes", normalizeNote);
  };
  const loadActivities = async ({ expectedOwner, role, leadId, signal } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const id = requirePositiveId(leadId, "CRM requested lead ID");
    throwIfAborted(signal);
    const response = await client.get(ADMIN_CLOSURE_CRM_ENDPOINTS.activities(id), transportConfig(signal, { params: { page: 1, per_page: ADMIN_CLOSURE_CRM_PER_PAGE } }));
    throwIfAborted(signal);
    return normalizeChildResponse(response?.data, owner, id, "activities", normalizeActivity);
  };
  const createLead = async ({ expectedOwner, role, payload, signal } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const body = requireCreatePayload(payload);
    throwIfAborted(signal);
    const response = await client.post(ADMIN_CLOSURE_CRM_ENDPOINTS.leads, body, transportConfig(signal));
    throwIfAborted(signal);
    const result = normalizeLeadMutation(response?.data, owner, response?.data?.lead?.id);
    return result;
  };
  const updateLead = async ({ expectedOwner, role, leadId, payload, signal } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const id = requirePositiveId(leadId, "CRM requested lead ID");
    const body = requireUpdatePayload(payload);
    throwIfAborted(signal);
    const response = await client.patch(ADMIN_CLOSURE_CRM_ENDPOINTS.lead(id), body, transportConfig(signal));
    throwIfAborted(signal);
    return normalizeLeadMutation(response?.data, owner, id);
  };
  const addNote = async ({ expectedOwner, role, leadId, content, signal } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const id = requirePositiveId(leadId, "CRM requested lead ID");
    const body = requireNotePayload(content);
    throwIfAborted(signal);
    const response = await client.post(ADMIN_CLOSURE_CRM_ENDPOINTS.notes(id), body, transportConfig(signal));
    throwIfAborted(signal);
    return normalizeNoteMutation(response?.data, owner, id);
  };
  const addActivity = async ({ expectedOwner, role, leadId, payload, signal } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const id = requirePositiveId(leadId, "CRM requested lead ID");
    const body = requireActivityPayload(payload);
    throwIfAborted(signal);
    const response = await client.post(ADMIN_CLOSURE_CRM_ENDPOINTS.activities(id), body, transportConfig(signal));
    throwIfAborted(signal);
    return normalizeActivityMutation(response?.data, owner, id);
  };
  const markConverted = async ({ expectedOwner, role, leadId, signal } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    requireAdminRole(role);
    const id = requirePositiveId(leadId, "CRM requested lead ID");
    throwIfAborted(signal);
    const response = await client.post(ADMIN_CLOSURE_CRM_ENDPOINTS.convert(id), {}, transportConfig(signal));
    throwIfAborted(signal);
    return normalizeLeadMutation(response?.data, owner, id);
  };
  const deleteLead = async ({ expectedOwner, role, leadId, signal } = {}) => {
    const owner = normalizeAdminClosureCrmExpectedOwner(expectedOwner);
    if (role !== ROLES.SUPERMASTER) fail("Only the declared supermaster role may request lead deletion.");
    const id = requirePositiveId(leadId, "CRM requested lead ID");
    throwIfAborted(signal);
    const response = await client.delete(ADMIN_CLOSURE_CRM_ENDPOINTS.lead(id), transportConfig(signal));
    throwIfAborted(signal);
    const source = requireRecord(response?.data, "CRM delete response");
    if (source.lead_id !== id || !hasOwn(source, "owner_context")) fail("CRM delete response does not match the request.");
    return { ownerContext: normalizeOwnerContext(source.owner_context, owner), leadId: id };
  };
  return { loadLeads, loadStats, loadLead, loadNotes, loadActivities, createLead, updateLead, addNote, addActivity, markConverted, deleteLead };
};

export const isAdminClosureCrmRequestCanceled = (error) => error?.name === "AbortError" || error?.code === "ERR_CANCELED";
export const adminClosureCrmError = () => "CRM data could not be loaded or its response could not be verified. No empty result or saved change has been assumed.";
