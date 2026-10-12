import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { transformWithEsbuild } from "vite";
import { normalizeCatalogProgram } from "../src/services/programCatalogViewService.js";

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
  );
const transformed = await transformWithEsbuild(source, file.pathname, {
  loader: "jsx",
  jsx: "automatic",
});
const target = new URL(
  "../node_modules/.cache-program-catalog-component.mjs",
  import.meta.url,
);
let components;
try {
  fs.writeFileSync(target, transformed.code);
  components = await import(target.href);
} finally {
  fs.rmSync(target, { force: true });
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
  assert.match(boundary, /Payments are not enabled/);
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
