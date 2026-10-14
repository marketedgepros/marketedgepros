import api from "./api.js";
import { evaluationPolicyForTerms } from "./programEvaluationPolicy.js";

export const MAX_CATALOG_ITEMS = 200;
export const PROGRAM_TYPES = Object.freeze({
  two_phase: "Two phase",
  one_phase: "One phase",
  three_phase: "Three phase",
  instant_funding: "Instant funding",
  lightning: "Lightning",
});
const moneyPattern = /^(0|[1-9]\d*)\.\d{2}$/;
const record = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);
export class CatalogContractError extends Error {}
const invalid = (label) => {
  throw new CatalogContractError(
    `${label} is unavailable or invalid. No substitute catalog is displayed.`,
  );
};
export const catalogId = (value) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > 2147483647)
    invalid("Program identifier");
  return value;
};
export const routeCatalogId = (value) => {
  if (typeof value !== "string" || !/^[1-9]\d{0,9}$/.test(value))
    invalid("Program identifier");
  return catalogId(Number(value));
};
const text = (value, label, maximum = 255) => {
  if (typeof value !== "string" || !value.trim() || value.length > maximum)
    invalid(label);
  return value;
};
const nullableText = (value, label, maximum) =>
  value === null ? null : text(value, label, maximum);
export const exactCatalogAmount = (
  value,
  { positive = false, max = 9999999999n } = {},
) => {
  if (
    typeof value !== "string" ||
    !moneyPattern.test(value) ||
    value.length > 16
  )
    invalid("Catalog amount");
  const cents = BigInt(value.replace(".", ""));
  if (cents > max || (positive && cents === 0n)) invalid("Catalog amount");
  return value;
};
const percentage = (value) =>
  value === null ? null : exactCatalogAmount(value, { max: 10000n });
const jsonCopy = (value) => {
  if (!record(value)) invalid("Catalog rules");
  let encoded;
  try {
    encoded = JSON.stringify(value);
  } catch {
    invalid("Catalog rules");
  }
  if (new TextEncoder().encode(encoded).length > 65536)
    invalid("Catalog rules");
  return JSON.parse(encoded);
};
export const normalizeProgramTerms = (source) => {
  if (!record(source)) invalid("Program terms");
  const type = text(source.type, "Program type", 50);
  if (!/^[\x20-\x7e]+$/.test(type)) invalid("Program type");
  const terms = Object.freeze({
    name: text(source.name, "Program name"),
    type,
    description: nullableText(source.description, "Program description", 65536),
    account_size: exactCatalogAmount(source.account_size, {
      positive: true,
      max: 999999999999n,
    }),
    profit_target: percentage(source.profit_target),
    max_daily_loss: percentage(source.max_daily_loss),
    max_total_loss: percentage(source.max_total_loss),
    profit_split: percentage(source.profit_split),
    profit_split_percentage: percentage(source.profit_split_percentage),
    minimum_payout_amount:
      source.minimum_payout_amount === null
        ? null
        : exactCatalogAmount(source.minimum_payout_amount),
    payout_mode: nullableText(source.payout_mode, "Payout mode", 50),
    rules: jsonCopy(source.rules),
  });
  const policy = evaluationPolicyForTerms(terms);
  if (policy.status === "mismatch" || policy.status === "unsupported")
    invalid("Recorded evaluation policy");
  return terms;
};
const canonical = (value) => {
  if (Array.isArray(value)) return value.map(canonical);
  if (record(value))
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonical(value[key])]),
    );
  return value;
};
const signature = (value) => JSON.stringify(canonical(value));
export const normalizeCatalogProgram = (
  source,
  expectedId = null,
  withAddons = false,
) => {
  if (!record(source) || source.is_active !== true || source.currency !== "USD")
    invalid("Active USD program");
  const id = catalogId(source.id);
  catalogId(source.tenant_id);
  if (expectedId !== null && id !== expectedId) invalid("Requested program");
  const terms = normalizeProgramTerms(source.terms);
  for (const field of [
    "name",
    "type",
    "description",
    "account_size",
    "profit_target",
    "max_daily_loss",
    "max_total_loss",
    "profit_split",
    "rules",
  ]) {
    if (signature(source[field]) !== signature(terms[field]))
      invalid("Catalog and terms consistency");
  }
  const price = exactCatalogAmount(source.price, { positive: true });
  let addons = [];
  if (withAddons) {
    if (
      !Array.isArray(source.addons) ||
      source.addons.length > MAX_CATALOG_ITEMS
    )
      invalid("Program add-ons");
    const ids = new Set();
    addons = source.addons.map((addon) => {
      if (!record(addon) || addon.program_id !== id || addon.is_active !== true)
        invalid("Active program add-on");
      const addonId = catalogId(addon.id);
      if (
        ids.has(addonId) ||
        !["fixed", "percentage"].includes(addon.price_type)
      )
        invalid("Unique priced add-on");
      ids.add(addonId);
      return Object.freeze({
        id: addonId,
        name: text(addon.name, "Add-on name"),
        description: nullableText(
          addon.description,
          "Add-on description",
          65536,
        ),
        price: exactCatalogAmount(addon.price),
        priceType: addon.price_type,
        benefits: jsonCopy(addon.benefits),
      });
    });
  }
  return Object.freeze({
    id,
    tenantId: source.tenant_id,
    currency: "USD",
    price,
    terms,
    addons: Object.freeze(addons),
  });
};
export const normalizeCatalogList = (payload) => {
  if (
    !record(payload) ||
    !Array.isArray(payload.programs) ||
    payload.programs.length > MAX_CATALOG_ITEMS
  )
    invalid("Program catalog");
  const programs = payload.programs.map((program) =>
    normalizeCatalogProgram(program),
  );
  if (
    new Set(programs.map((program) => program.id)).size !== programs.length ||
    new Set(programs.map((program) => program.tenantId)).size > 1
  )
    invalid("Single-brand catalog");
  return programs;
};
export async function loadCatalog({
  programId = null,
  signal,
  client = api,
} = {}) {
  const id = programId === null ? null : catalogId(programId);
  const response = await client.get(
    id === null ? "/programs/" : `/programs/${id}`,
    { signal, timeout: 12000 },
  );
  return id === null
    ? normalizeCatalogList(response?.data)
    : normalizeCatalogProgram(response?.data, id, true);
}
export const formatCatalogMoney = (value) => {
  const exact = exactCatalogAmount(value, { max: 999999999999n });
  const [whole, fraction] = exact.split(".");
  return `USD ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${fraction}`;
};
export const formatCatalogPercent = (value) =>
  value === null
    ? "Not specified"
    : `${percentage(value)
        .replace(/\.00$/, "")
        .replace(/(\.\d)0$/, "$1")}%`;
export const typeLabel = (type) =>
  PROGRAM_TYPES[type] || type.replaceAll("_", " ");
export const addonPriceLabel = (addon) =>
  addon.priceType === "percentage"
    ? `${addon.price.replace(/\.00$/, "")}% of the base fee`
    : formatCatalogMoney(addon.price);
export const catalogErrorMessage = (error) =>
  error instanceof CatalogContractError
    ? error.message
    : error?.response?.status === 404
      ? "This program is unavailable. It may be inactive or outside the current catalog."
      : "The current catalog could not be loaded. No saved or substitute prices are being shown.";

export const mapQuotedCatalog = (quote, program, ownerId = null) => {
  const source = quote?.order?.snapshot;
  const terms = normalizeProgramTerms(source?.terms);
  const baseAmount = exactCatalogAmount(source?.baseAmount, { positive: true });
  if (quote?.context?.programId !== program.id) invalid("Quoted program");
  if (!Array.isArray(source.addons)) invalid("Quoted add-ons");
  const total = source.addons.reduce(
    (sum, addon) =>
      sum + BigInt(exactCatalogAmount(addon.amount).replace(".", "")),
    BigInt(baseAmount.replace(".", "")),
  );
  if (
    !/^\d+$/.test(String(quote.order.amountMinor)) ||
    total !== BigInt(quote.order.amountMinor)
  )
    invalid("Quoted total and line amounts");
  if (
    ownerId !== null &&
    (quote.order.userId !== ownerId ||
      source.userId !== ownerId ||
      quote.order.tenantId !== program.tenantId ||
      source.tenantId !== program.tenantId)
  )
    invalid("Quote owner and brand");
  return Object.freeze({
    terms,
    baseAmount,
    differsFromCatalog:
      baseAmount !== program.price ||
      signature(terms) !== signature(program.terms),
  });
};
