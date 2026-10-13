import assert from "node:assert/strict";
import test from "node:test";
import {
  normalizeCatalogList,
  normalizeCatalogProgram,
  normalizeProgramTerms,
  routeCatalogId,
  loadCatalog,
  formatCatalogMoney,
  formatCatalogPercent,
  addonPriceLabel,
  mapQuotedCatalog,
} from "../src/services/programCatalogViewService.js";

export const terms = () => ({
  name: "Synthetic precision program",
  type: "two_phase",
  description: null,
  account_size: "25000.00",
  profit_target: "0.00",
  max_daily_loss: null,
  max_total_loss: "8.00",
  profit_split: "80.00",
  profit_split_percentage: "80.00",
  minimum_payout_amount: null,
  payout_mode: null,
  rules: { phase_targets: [8, 5], missing: null },
});
export const program = (id = 12) => ({
  ...terms(),
  id,
  tenant_id: 1,
  currency: "USD",
  price: "199.99",
  is_active: true,
  terms: terms(),
  addons: [
    {
      id: 9,
      program_id: id,
      name: "Synthetic percentage",
      description: null,
      price: "2.50",
      price_type: "percentage",
      benefits: {},
      is_active: true,
    },
  ],
});

test("catalog uses one active USD brand and exact decimal text preserving zero and unknown", () => {
  const p = normalizeCatalogProgram(program(), 12, true);
  assert.equal(p.price, "199.99");
  assert.equal(formatCatalogPercent(p.terms.profit_target), "0%");
  assert.equal(formatCatalogPercent(p.terms.max_daily_loss), "Not specified");
  assert.equal(formatCatalogMoney(p.terms.account_size), "USD 25,000.00");
  assert.equal(addonPriceLabel(p.addons[0]), "2.50% of the base fee");
  assert.equal(normalizeCatalogList({ programs: [] }).length, 0);
});

test("catalog refuses malformed money, inactive or foreign detail and inconsistent top terms", () => {
  for (const changed of [
    { price: 199.99 },
    { price: "0.00" },
    { price: "1.999" },
    { price: "-1.00" },
    { currency: "USDT" },
    { is_active: false },
    { name: "different top value" },
    { terms: null },
    { id: 11 },
    { account_size: undefined },
  ]) {
    assert.throws(() =>
      normalizeCatalogProgram({ ...program(), ...changed }, 12, true),
    );
  }
  for (const value of ["1e2", "01", "0", "NaN", "2147483648", true])
    assert.throws(() => routeCatalogId(value));
  assert.equal(routeCatalogId("12"), 12);
  assert.throws(() =>
    normalizeProgramTerms({ ...terms(), profit_target: "100.01" }),
  );
});

test("catalog rejects duplicate records, mixed brands, overflow and foreign or malformed add-ons", () => {
  assert.throws(() =>
    normalizeCatalogList({ programs: [program(), program()] }),
  );
  assert.throws(() =>
    normalizeCatalogList({
      programs: [program(), { ...program(13), tenant_id: 2 }],
    }),
  );
  assert.throws(() =>
    normalizeCatalogList({
      programs: Array.from({ length: 201 }, (_, index) => program(index + 1)),
    }),
  );
  for (const change of [
    { program_id: 13 },
    { is_active: false },
    { price_type: "unknown" },
    { price: false },
  ]) {
    const source = program();
    source.addons[0] = { ...source.addons[0], ...change };
    assert.throws(() => normalizeCatalogProgram(source, 12, true));
  }
  const source = program();
  source.addons.push(source.addons[0]);
  assert.throws(() => normalizeCatalogProgram(source, 12, true));
});

test("catalog request has only canonical path and signal with no client-selected brand", async () => {
  const calls = [],
    controller = new AbortController();
  const client = {
    get: async (path, options) => {
      calls.push([path, options]);
      return {
        data: path.endsWith("/") ? { programs: [program()] } : program(),
      };
    },
  };
  await loadCatalog({ client, signal: controller.signal });
  await loadCatalog({ client, programId: 12, signal: controller.signal });
  assert.deepEqual(
    calls.map(([path]) => path),
    ["/programs/", "/programs/12"],
  );
  assert.ok(
    calls.every(
      ([, options]) =>
        Object.keys(options).length === 2 &&
        Object.keys(options).every(key => ['signal', 'timeout'].includes(key)) &&
        options.timeout === 12000 &&
        options.signal === controller.signal,
    ),
  );
  await assert.rejects(
    loadCatalog({
      client: {
        get: async () => {
          throw new Error("unavailable");
        },
      },
    }),
  );
});

test("quote displays frozen terms, detects changed catalog and refuses missing source terms", () => {
  const p = normalizeCatalogProgram(program(), 12, true);
  const q = {
    context: { programId: 12 },
    order: {
      amountMinor: "19999",
      snapshot: { baseAmount: "199.99", terms: terms(), addons: [] },
    },
  };
  assert.equal(mapQuotedCatalog(q, p).differsFromCatalog, false);
  q.order.snapshot.baseAmount = "200.00";
  q.order.amountMinor = "20000";
  q.order.snapshot.terms = { ...terms(), profit_target: "9.00" };
  const result = mapQuotedCatalog(q, p);
  assert.equal(result.differsFromCatalog, true);
  assert.equal(result.terms.profit_target, "9.00");
  assert.equal(p.terms.profit_target, "0.00");
  q.order.snapshot.terms = null;
  assert.throws(() => mapQuotedCatalog(q, p));
});

test("quote row and snapshot must both match the current owner and catalog brand", () => {
  const p = normalizeCatalogProgram(program(), 12, true);
  const q = {
    context: { programId: 12 },
    order: {
      userId: 701,
      tenantId: 1,
      amountMinor: "19999",
      snapshot: {
        userId: 701,
        tenantId: 1,
        baseAmount: "199.99",
        terms: terms(),
        addons: [],
      },
    },
  };
  assert.equal(mapQuotedCatalog(q, p, 701).differsFromCatalog, false);
  for (const field of ["userId", "tenantId"]) {
    const previous = q.order[field];
    q.order[field] = 999;
    assert.throws(() => mapQuotedCatalog(q, p, 701), /owner and brand/);
    q.order[field] = previous;
    const snapshotPrevious = q.order.snapshot[field];
    q.order.snapshot[field] = 999;
    assert.throws(() => mapQuotedCatalog(q, p, 701), /owner and brand/);
    q.order.snapshot[field] = snapshotPrevious;
  }
  q.order.amountMinor = "20000";
  assert.throws(() => mapQuotedCatalog(q, p, 701), /total and line/);
});
