import api from "./api.js";
import { ALL_ROLES, ROLES } from "../constants/roles.js";

export const ADMIN_CLOSURE_SETTINGS_ENDPOINT = "/admin/settings";
export const ADMIN_CLOSURE_SETTINGS_REQUEST_TIMEOUT_MS = 5000;

const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const CONTROL_CHARACTERS = /[\u0000-\u001F\u007F]/;
// Matches the ASCII email syntax enforced by an HTML <input type="email">.
const CONTACT_EMAIL_PATTERN = /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;

export class AdminClosureSettingsContractError extends Error {
  constructor(message) {
    super(message);
    this.name = "AdminClosureSettingsContractError";
  }
}

const fail = (message) => {
  throw new AdminClosureSettingsContractError(message);
};

const requireRecord = (value, label) => {
  if (!isRecord(value)) fail(`${label} must be an object.`);
  return value;
};

const requireExactFields = (value, fields, label) => {
  const record = requireRecord(value, label);
  const actual = Object.keys(record);
  if (actual.length !== fields.length || fields.some((field) => !hasOwn(record, field))) {
    fail(`${label} contains fields outside the canonical settings contract.`);
  }
  return record;
};

const requirePositiveId = (value, label) => {
  if (!Number.isSafeInteger(value) || value < 1) fail(`${label} must be a positive safe integer.`);
  return value;
};

const requireNullableText = (value, label, maximum) => {
  if (value === null) return null;
  if (typeof value !== "string" || value.length > maximum || CONTROL_CHARACTERS.test(value)) {
    fail(`${label} must be a bounded text string or null.`);
  }
  return value;
};

/** Keeps the optional field's null semantics while matching the UI's email syntax. */
export const isAdminClosureSettingsContactEmail = (value) => (
  value === null
  || (
    typeof value === "string"
    && value.length > 0
    && value.length <= 255
    && !CONTROL_CHARACTERS.test(value)
    && CONTACT_EMAIL_PATTERN.test(value)
  )
);

const requireNullableContactEmail = (value, label) => {
  if (!isAdminClosureSettingsContactEmail(value)) {
    fail(`${label} must be a valid bounded email address or null.`);
  }
  return value;
};

const requireTenantName = (value, label) => {
  if (typeof value !== "string" || value.length < 1 || value.length > 255 || CONTROL_CHARACTERS.test(value)) {
    fail(`${label} must be a non-empty bounded text string.`);
  }
  return value;
};

/**
 * Independent auth identity only. A browser-side role is never proof of platform
 * root authority; the server verifies the configured root again before any SQL.
 */
export const normaliseAdminClosureSettingsExpectedOwner = (expectedOwner) => {
  const source = requireExactFields(expectedOwner, ["user_id", "tenant_id", "role"], "Expected settings owner");
  if (typeof source.role !== "string" || !ALL_ROLES.includes(source.role)) {
    fail("Expected settings role is unsupported.");
  }
  if (source.role !== ROLES.SUPERMASTER) {
    fail("Tenant settings require a supermaster session before transport.");
  }
  return {
    user_id: requirePositiveId(source.user_id, "Expected settings user ID"),
    tenant_id: requirePositiveId(source.tenant_id, "Expected settings tenant ID"),
    role: source.role,
  };
};
export const normalizeAdminClosureSettingsExpectedOwner = normaliseAdminClosureSettingsExpectedOwner;

export const adminClosureSettingsIdentityKey = ({ isAuthenticated, userId, tenantId, role }) => (
  JSON.stringify([isAuthenticated === true, userId ?? null, tenantId ?? null, role ?? null])
);

export const adminClosureSettingsPrincipalFromAuth = (user, isAuthenticated) => {
  try {
    if (isAuthenticated !== true) return null;
    const owner = normaliseAdminClosureSettingsExpectedOwner({
      user_id: user?.id,
      tenant_id: user?.tenant_id,
      role: user?.role,
    });
    return {
      owner,
      key: adminClosureSettingsIdentityKey({
        isAuthenticated,
        userId: owner.user_id,
        tenantId: owner.tenant_id,
        role: owner.role,
      }),
    };
  } catch {
    return null;
  }
};

export const normaliseAdminClosureTenantDraft = (draft) => {
  const source = requireExactFields(draft, ["name", "contact_email", "contact_phone"], "Tenant settings draft");
  return {
    name: requireTenantName(source.name, "Tenant name"),
    contact_email: requireNullableText(source.contact_email, "Tenant contact email", 255),
    contact_phone: requireNullableText(source.contact_phone, "Tenant contact phone", 20),
  };
};
export const normalizeAdminClosureTenantDraft = normaliseAdminClosureTenantDraft;

const normaliseAdminClosureTenantSaveDraft = (draft) => {
  const normalized = normaliseAdminClosureTenantDraft(draft);
  return {
    ...normalized,
    contact_email: requireNullableContactEmail(normalized.contact_email, "Tenant contact email"),
  };
};

const normalizeOwnerContext = (value, expectedOwner) => {
  const source = requireExactFields(value, ["user_id", "tenant_id"], "Settings owner context");
  const owner = {
    user_id: requirePositiveId(source.user_id, "Settings owner-context user ID"),
    tenant_id: requirePositiveId(source.tenant_id, "Settings owner-context tenant ID"),
  };
  if (owner.user_id !== expectedOwner.user_id || owner.tenant_id !== expectedOwner.tenant_id) {
    fail("Settings owner context does not match the active account.");
  }
  return owner;
};

const normalizeScope = (value, owner) => {
  const source = requireExactFields(value, ["kind", "tenant_id"], "Settings scope");
  if (source.kind !== "tenant") fail("Settings scope must be tenant-scoped.");
  const tenantId = requirePositiveId(source.tenant_id, "Settings scope tenant ID");
  if (tenantId !== owner.tenant_id) fail("Settings scope does not match the active tenant.");
  return { kind: "tenant", tenantId };
};

const normalizeCapabilities = (value) => {
  const source = requireExactFields(value, ["tenant_contact", "global_system", "payment_providers"], "Settings capabilities");
  if (source.tenant_contact !== "persisted") fail("Tenant contact capability must be persisted.");
  if (source.global_system !== "unavailable_no_persistence") {
    fail("Global settings capability is invalid.");
  }
  if (source.payment_providers !== "unavailable_no_persistence") {
    fail("Payment-provider settings capability is invalid.");
  }
  return {
    tenantContact: "persisted",
    globalSystem: "unavailable_no_persistence",
    paymentProviders: "unavailable_no_persistence",
  };
};

/** Maps a direct server acknowledgement only; it never inserts defaults for unknown data. */
export const mapAdminClosureSettings = (payload, { expectedOwner } = {}) => {
  const owner = normaliseAdminClosureSettingsExpectedOwner(expectedOwner);
  const source = requireExactFields(payload, ["owner_context", "scope", "tenant_settings", "capabilities"], "Settings response");
  const ownerContext = normalizeOwnerContext(source.owner_context, owner);
  return {
    ownerContext,
    scope: normalizeScope(source.scope, ownerContext),
    tenantSettings: normaliseAdminClosureTenantDraft(source.tenant_settings),
    capabilities: normalizeCapabilities(source.capabilities),
  };
};

const abortError = () => {
  const error = new Error("Admin settings request was cancelled.");
  error.name = "AbortError";
  return error;
};

const throwIfAborted = (signal) => {
  if (signal?.aborted) throw abortError();
};

const normalizeReadRequest = ({ expectedOwner } = {}) => ({
  owner: normaliseAdminClosureSettingsExpectedOwner(expectedOwner),
});

const normalizeSaveRequest = ({ expectedOwner, draft } = {}) => ({
  owner: normaliseAdminClosureSettingsExpectedOwner(expectedOwner),
  draft: normaliseAdminClosureTenantSaveDraft(draft),
});

/** Injectable Axios-compatible one-shot reader/writer. It neither polls nor retries. */
export const createAdminClosureSettingsService = (client = api) => ({
  loadSettings: async (options = {}) => {
    const request = normalizeReadRequest(options);
    throwIfAborted(options.signal);
    const response = await client.get(ADMIN_CLOSURE_SETTINGS_ENDPOINT, {
      signal: options.signal,
      timeout: ADMIN_CLOSURE_SETTINGS_REQUEST_TIMEOUT_MS,
      _skipAuthRefresh: true,
    });
    throwIfAborted(options.signal);
    return mapAdminClosureSettings(response?.data, { expectedOwner: request.owner });
  },

  saveSettings: async (options = {}) => {
    const request = normalizeSaveRequest(options);
    throwIfAborted(options.signal);
    const response = await client.put(
      ADMIN_CLOSURE_SETTINGS_ENDPOINT,
      { tenant_settings: request.draft },
      {
        signal: options.signal,
        timeout: ADMIN_CLOSURE_SETTINGS_REQUEST_TIMEOUT_MS,
        _skipAuthRefresh: true,
      },
    );
    throwIfAborted(options.signal);
    const acknowledgement = mapAdminClosureSettings(response?.data, { expectedOwner: request.owner });
    if (JSON.stringify(acknowledgement.tenantSettings) !== JSON.stringify(request.draft)) {
      fail("Settings acknowledgement does not match the submitted tenant draft.");
    }
    return acknowledgement;
  },
});

const defaultAdminClosureSettingsService = createAdminClosureSettingsService();
export const loadAdminClosureSettings = (options = {}) => defaultAdminClosureSettingsService.loadSettings(options);
export const saveAdminClosureSettings = (options = {}) => defaultAdminClosureSettingsService.saveSettings(options);

export const isAdminClosureSettingsRequestCanceled = (error) => (
  error?.name === "AbortError" || error?.code === "ERR_CANCELED"
);

export const adminClosureSettingsError = () => (
  "The tenant settings service is unavailable or its response could not be validated. No saved value has been assumed."
);
