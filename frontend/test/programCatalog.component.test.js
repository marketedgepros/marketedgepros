import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { transformWithEsbuild } from "vite";
import { normalizeCatalogProgram } from "../src/services/programCatalogViewService.js";
import { approvedEvaluationPolicy } from "../src/services/programEvaluationPolicy.js";

const terms = {
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
};
const assignedTerms = (type) => {
  const evaluationPolicy = approvedEvaluationPolicy(type);
  return {
    ...terms,
    type,
    profit_target: evaluationPolicy.phase_targets[0] ?? "0.00",
    max_daily_loss: evaluationPolicy.max_daily_loss,
    max_total_loss: evaluationPolicy.max_total_loss,
    profit_split: evaluationPolicy.profit_split,
    profit_split_percentage: evaluationPolicy.profit_split,
    rules: {
      drawdown_type: evaluationPolicy.drawdown_type,
      evaluation_policy: evaluationPolicy,
    },
  };
};
const file = new URL(
  "../src/components/programs/CatalogUI.jsx",
  import.meta.url,
);
let source = fs.readFileSync(file, "utf8");
source = source
  .replace(
    /import Layout from ['"]\.\.\/layout\/Layout['"];?/,
    "const Layout = ({ children }) => <main>{children}</main>;",
  )
  .replace(
    /['"]\.\.\/\.\.\/services\/programCatalogViewService['"]/,
    JSON.stringify(
      new URL("../src/services/programCatalogViewService.js", import.meta.url)
        .href,
    ),
  )
  .replace(
    /['"]\.\.\/\.\.\/services\/programEvaluationPolicy\.js['"]/,
    JSON.stringify(
      new URL("../src/services/programEvaluationPolicy.js", import.meta.url)
        .href,
    ),
  );
const target = new URL(
  "../node_modules/.cache-program-catalog-component.mjs",
  import.meta.url,
);
const comingSoonFile = new URL(
  "../src/components/programs/ComingSoonProgram.jsx",
  import.meta.url,
);
const comingSoonTarget = new URL(
  "../node_modules/.cache-coming-soon-program.mjs",
  import.meta.url,
);
let components;
try {
  const transformedComingSoon = await transformWithEsbuild(
    fs.readFileSync(comingSoonFile, "utf8"),
    comingSoonFile.pathname,
    { loader: "jsx", jsx: "automatic" },
  );
  fs.writeFileSync(comingSoonTarget, transformedComingSoon.code);
  source = source.replace(
    /import ComingSoonProgram from ['"]\.\/ComingSoonProgram['"];?/,
    `import ComingSoonProgram from ${JSON.stringify(comingSoonTarget.href)};`,
  );
  const transformed = await transformWithEsbuild(source, file.pathname, {
    loader: "jsx",
    jsx: "automatic",
  });
  fs.writeFileSync(target, transformed.code);
  components = await import(target.href);
} finally {
  fs.rmSync(target, { force: true });
  fs.rmSync(comingSoonTarget, { force: true });
}
const render = (Component, props = {}) =>
  renderToStaticMarkup(
    React.createElement(
      MemoryRouter,
      null,
      React.createElement(Component, props),
    ),
  );

test("real catalog card renders exact fee, unknown/zero rules and canonical details destination", () => {
  const program = normalizeCatalogProgram({
    ...terms,
    id: 12,
    tenant_id: 1,
    price: "199.99",
    currency: "USD",
    is_active: true,
    terms,
  });
  const html = render(components.CatalogCard, { program });
  assert.match(html, /USD 199.99/);
  assert.match(html, /USD 25,000.00/);
  assert.match(html, /0%/);
  assert.match(html, /Not specified/);
  assert.match(html, /href="\/programs\/12"/);
  assert.doesNotMatch(html, /Get Funded|90%|24 hours|success|<form/);
});

test("real availability and error components distinguish load/failure/empty and do not invent money", () => {
  assert.match(
    render(components.CatalogState, { loading: true }),
    /aria-busy="true"/,
  );
  const failed = render(components.CatalogState, {
    error: "Synthetic catalog failure",
    retry: () => {},
  });
  assert.match(failed, /role="alert"/);
  assert.match(failed, /Try again/);
  const empty = render(components.CatalogState, { empty: true });
  assert.match(empty, /No active programs available/);
  assert.doesNotMatch(empty, /Try again/);
  const boundary = render(components.PaymentBoundary);
  assert.match(boundary, /A quote is not a paid purchase\./);
  assert.match(boundary, /Payment availability is checked separately for your account\./);
  assert.match(boundary, /does not charge you, activate a trading account or provide funding/);
  assert.match(boundary, /does not activate trading, payouts or KYC-provider verification/);
  assert.doesNotMatch(boundary, /Payments are not enabled/);
  assert.doesNotMatch(boundary, /<button|<form/);
});

test("real additional rules escape stored strings and retain explicit unknown semantics", () => {
  const html = render(components.ConfiguredRules, {
    terms: {
      ...terms,
      rules: { unsafe: "<script>bad</script>", missing: null },
    },
  });
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /Not specified/);
  assert.match(html, /not confirmation of live enforcement/);
});

test("assigned evaluation cards render the exact recorded stage targets and operator share", () => {
  const program = {
    id: 3699,
    price: "199.99",
    terms: assignedTerms("two_phase"),
  };
  const html = render(components.CatalogCard, { program });
  assert.match(html, /Phase 1 profit target/);
  assert.match(html, /Phase 2 profit target/);
  assert.match(html, /8%/);
  assert.match(html, /5%/);
  assert.match(html, /Operator share of eligible profit/);
  assert.match(html, /10%/);
  assert.doesNotMatch(html, /phase_targets|evaluation_policy/);
});

test("legacy unassigned rules retain five published rows while an historical Instant record retains its old values", () => {
  const legacy = {
    ...terms,
    type: "two_phase",
    profit_target: "8.00",
    max_daily_loss: "4.00",
    max_total_loss: "8.00",
    profit_split: "80.00",
    rules: { drawdown_type: "trailing" },
  };
  const legacyHtml = render(components.ProgramRules, { terms: legacy });
  assert.equal((legacyHtml.match(/<dt /g) || []).length, 5);
  for (const value of ["8%", "4%", "8%", "80%"]) assert.match(legacyHtml, new RegExp(value.replace("%", "%")));
  assert.doesNotMatch(legacyHtml, /Operator share/);

  const oldInstant = {
    ...assignedTerms("instant_funding"),
    profit_target: "0.00",
    max_daily_loss: "5.00",
    max_total_loss: "10.00",
    profit_split: "90.00",
  };
  const historicalHtml = render(components.ProgramRules, {
    terms: oldInstant,
    historical: true,
  });
  assert.equal((historicalHtml.match(/<dt /g) || []).length, 6);
  assert.match(historicalHtml, /Profit target/);
  assert.match(historicalHtml, /0%/);
  assert.match(historicalHtml, /Operator share of eligible profit/);
});

test("Instant Funding card is Coming soon and does not expose a fee, quote, checkout or purchase route", () => {
  const html = render(components.CatalogCard, {
    program: {
      id: 3711,
      price: "999.99",
      terms: assignedTerms("instant_funding"),
    },
  });
  assert.match(html, /data-coming-soon="instant_funding"/);
  assert.match(html, /Coming soon/);
  assert.match(html, /Instant Funding is not available for purchase, quote requests or new payments/);
  assert.doesNotMatch(html, /999\.99|USD|Catalog base fee|href="\/programs\/3711|checkout|<button/);
});

test("all active public pricing consumers use shared catalog and detail page has no legacy payment SDK", () => {
  for (const page of [
    "ProgramsNew.jsx",
    "ProgramDetails.jsx",
    "Checkout.jsx",
  ]) {
    const content = fs.readFileSync(
      new URL(`../src/pages/${page}`, import.meta.url),
      "utf8",
    );
    assert.match(content, /useProgramCatalog/);
    assert.doesNotMatch(
      content,
      /staticPrograms|loadStripe|CryptoCheckout|confirmCardPayment|paymentsAPI|success=true/,
    );
  }
  for (const page of ["NewHomePage.jsx", "LightningChallenge.jsx"]) {
    const content = fs.readFileSync(
      new URL(`../src/pages/${page}`, import.meta.url),
      "utf8",
    );
    assert.match(content, /CatalogPreview/);
    assert.doesNotMatch(content, /setPrograms|programs\[0\].*price/);
  }
});
