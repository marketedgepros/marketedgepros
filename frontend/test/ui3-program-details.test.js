import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(
  new URL("../src/pages/ProgramDetails.jsx", import.meta.url),
  "utf8",
);

test("program details clearly separates catalog fee from an unpaid, conditional quote", () => {
  assert.match(source, /Catalog base fee/);
  assert.match(source, /base fee shown in the catalog/);
  assert.match(source, /If quotes are\s+available/);
  assert.match(source, /unpaid quote/);
  assert.match(source, /No charge is made/);
  assert.match(source, /<PaymentBoundary \/>/);
});

test("quote CTA and optional add-on copy do not promise quote availability", () => {
  assert.match(source, /Check quote availability/);
  assert.match(source, /If quotes are\s+available, options can be selected there/);
  assert.match(source, /Percentage add-ons use the\s+base program fee/);
  assert.doesNotMatch(source, /Select options on the quote page/);
  assert.doesNotMatch(source, /will record the\s+server's current price/);
});

test("page keeps the catalog source, protected-route identity behavior, and opaque program ID", () => {
  assert.match(source, /useProgramCatalog\(id\)/);
  assert.match(source, /const destination = `\/programs\/\$\{program\.id\}\/checkout`/);
  assert.match(source, /user \? destination : `\/login\?redirect=\$\{encodeURIComponent\(destination\)\}`/);
  assert.match(source, /state: \{ from: destination \}/);
  assert.match(source, /<CatalogPage>/);
  assert.match(source, /<ProgramRules terms=\{program\.terms\} \/>/);
  assert.match(source, /<ConfiguredRules terms=\{program\.terms\} \/>/);
  assert.doesNotMatch(source, /\b(funding guaranteed|instant payout|MT5 live|success rate)\b/i);
});
