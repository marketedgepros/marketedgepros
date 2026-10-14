import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { transformWithEsbuild } from "vite";
import { normalizeCatalogProgram } from "../src/services/programCatalogViewService.js";

const uiFile = new URL(
  "../src/components/programs/CatalogUI.jsx",
  import.meta.url,
);
const previewFile = new URL(
  "../src/components/programs/CatalogPreview.jsx",
  import.meta.url,
);
const uiTarget = new URL(
  `../node_modules/.ui5-catalog-ui-${process.pid}.mjs`,
  import.meta.url,
);
const previewTarget = new URL(
  `../node_modules/.ui5-catalog-preview-${process.pid}.mjs`,
  import.meta.url,
);
const comingSoonFile = new URL(
  "../src/components/programs/ComingSoonProgram.jsx",
  import.meta.url,
);
const comingSoonTarget = new URL(
  `../node_modules/.ui5-coming-soon-${process.pid}.mjs`,
  import.meta.url,
);
const policyUrl = new URL(
  "../src/services/programEvaluationPolicy.js",
  import.meta.url,
).href;
const hookStub = new URL(
  `../node_modules/.ui5-catalog-hook-${process.pid}.mjs`,
  import.meta.url,
);

const selectorTarget = new URL(`../node_modules/.ui5-selector-${process.pid}.mjs`, import.meta.url);
let components;
let CatalogPreview;
try {
  fs.writeFileSync(
    hookStub,
    "export default function useProgramCatalog() { return globalThis.__ui5CatalogState; }\n",
  );
  const compiledComingSoon = await transformWithEsbuild(
    fs.readFileSync(comingSoonFile, "utf8"),
    comingSoonFile.pathname,
    { loader: "jsx", jsx: "automatic" },
  );
  fs.writeFileSync(comingSoonTarget, compiledComingSoon.code);
  const uiSource = fs
    .readFileSync(uiFile, "utf8")
    .replace(
      /import Layout from ['"]\.\.\/layout\/Layout['"];/,
      "const Layout = ({ children }) => <main>{children}</main>;",
    )
    .replace(
      /import ComingSoonProgram from ['"]\.\/ComingSoonProgram['"];/,
      `import ComingSoonProgram from ${JSON.stringify(comingSoonTarget.href)};`,
    )
    .replace(
      /['"]\.\.\/\.\.\/services\/programEvaluationPolicy\.js['"]/,
      JSON.stringify(policyUrl),
    )
    .replace(
      /['"]\.\.\/\.\.\/services\/programCatalogViewService['"]/,
      JSON.stringify(
        new URL(
          "../src/services/programCatalogViewService.js",
          import.meta.url,
        ).href,
      ),
    );
  const compiledUi = await transformWithEsbuild(uiSource, uiFile.pathname, {
    loader: "jsx",
    jsx: "automatic",
  });
  fs.writeFileSync(uiTarget, compiledUi.code);

  const selectorSource = fs.readFileSync(new URL('../src/components/programs/ProgramSelector.jsx', import.meta.url), 'utf8')
    .replace(/import ['"][^'"]+\.css['"];/, '')
    .replace(/['"]\.\/CatalogUI['"]/, JSON.stringify(uiTarget.href))
    .replace(/['"]\.\/ComingSoonProgram['"]/, JSON.stringify(comingSoonTarget.href))
    .replace(/['"]\.\.\/\.\.\/services\/programEvaluationPolicy\.js['"]/, JSON.stringify(policyUrl))
    .replace(/['"]\.\.\/\.\.\/services\/programCatalogViewService['"]/, JSON.stringify(new URL('../src/services/programCatalogViewService.js', import.meta.url).href));
  const compiledSelector = await transformWithEsbuild(selectorSource, 'ProgramSelector.jsx', { loader: 'jsx', jsx: 'automatic' });
  fs.writeFileSync(selectorTarget, compiledSelector.code);
  const previewSource = fs
    .readFileSync(previewFile, "utf8")
    .replace(
      /['"]\.\.\/\.\.\/hooks\/useProgramCatalog['"]/,
      JSON.stringify(hookStub.href),
    )
    .replace(/['"]\.\/CatalogUI['"]/, JSON.stringify(uiTarget.href))
    .replace(/['"]\.\/ProgramSelector['"]/, JSON.stringify(selectorTarget.href));
  const compiledPreview = await transformWithEsbuild(
    previewSource,
    previewFile.pathname,
    { loader: "jsx", jsx: "automatic" },
  );
  fs.writeFileSync(previewTarget, compiledPreview.code);

  components = await import(`${uiTarget.href}?ui5=${process.pid}`);
  CatalogPreview = (await import(`${previewTarget.href}?ui5=${process.pid}`))
    .default;
} finally {
  fs.rmSync(selectorTarget, { force: true });
  fs.rmSync(uiTarget, { force: true });
  fs.rmSync(previewTarget, { force: true });
  fs.rmSync(comingSoonTarget, { force: true });
  fs.rmSync(hookStub, { force: true });
}

const render = (element) =>
  renderToStaticMarkup(
    React.createElement(MemoryRouter, null, element),
  );

const longType = "x".repeat(50);
const longRuleKey = "unbroken_rule_key_without_natural_wrap_points_for_narrow_cards";
const terms = {
  name: "Synthetic catalog program",
  type: longType,
  description: null,
  account_size: "25000.00",
  profit_target: "8.00",
  max_daily_loss: "4.00",
  max_total_loss: "8.00",
  profit_split: "80.00",
  profit_split_percentage: "80.00",
  minimum_payout_amount: null,
  payout_mode: null,
  rules: { [longRuleKey]: "Stored value" },
};
const program = normalizeCatalogProgram({
  id: 77,
  tenant_id: 2,
  currency: "USD",
  price: "199.99",
  is_active: true,
  ...terms,
  terms,
});

test("UI-5 catalog card renders real dynamic content with safe narrow-width wrapping", () => {
  const card = render(React.createElement(components.CatalogCard, { program }));
  const rules = render(
    React.createElement(components.ConfiguredRules, { terms: program.terms }),
  );

  assert.ok(card.includes(longType));
  assert.ok(card.includes("USD 199.99"));
  assert.ok(card.includes('href="/programs/77"'));
  assert.ok(
    card.includes("break-words [overflow-wrap:anywhere]"),
    "the dynamic catalog type can wrap rather than expanding a narrow card",
  );
  assert.ok(rules.includes(longRuleKey.replaceAll("_", " ")));
  assert.ok(
    rules.includes("break-words [overflow-wrap:anywhere]"),
    "stored rule labels can wrap rather than expanding a narrow card",
  );
});

test("UI-5 catalog preview renders named navigable actions from its real hook state", () => {
  globalThis.__ui5CatalogState = {
    loading: false,
    error: "",
    data: [program],
    retry: () => {},
  };
  const html = render(React.createElement(CatalogPreview));
  const destinations = [...html.matchAll(/href="([^"]+)"/g)].map(
    (match) => match[1],
  );

  assert.deepEqual(destinations, ["/programs/77", "/programs"]);
  assert.ok(html.includes("View rules &amp; options"));
  assert.ok(html.includes("Compare all current programs"));
  assert.ok(
    html.includes('class="min-w-0 space-y-6"'),
    "the reusable preview can shrink when placed in a narrow flex or grid item",
  );
});

test("UI-5 catalog availability states expose status and named retry/support controls", () => {
  const loading = render(
    React.createElement(components.CatalogState, { loading: true }),
  );
  const failed = render(
    React.createElement(components.CatalogState, {
      error: "Synthetic catalog failure",
      retry: () => {},
    }),
  );

  assert.ok(loading.includes('aria-live="polite"'));
  assert.ok(loading.includes('aria-busy="true"'));
  assert.ok(failed.includes('role="alert"'));
  assert.ok(failed.includes(">Try again</button>"));
  assert.ok(failed.includes('href="/support/create-ticket"'));
  assert.ok(failed.includes(">Contact support</a>"));
});
