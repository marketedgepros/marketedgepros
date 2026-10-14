import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { JSDOM } from "jsdom";
import { transformWithEsbuild } from "vite";
import { approvedEvaluationPolicy } from "../src/services/programEvaluationPolicy.js";

const require = createRequire(import.meta.url);
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const componentFile = path.join(
  frontend,
  "src",
  "components",
  "programs",
  "ProgramComparison.jsx",
);
const pageFile = path.join(frontend, "src", "pages", "ProgramsNew.jsx");
const serviceUrl = pathToFileURL(
  path.join(frontend, "src", "services", "programCatalogViewService.js"),
).href;
const policyUrl = pathToFileURL(
  path.join(frontend, "src", "services", "programEvaluationPolicy.js"),
).href;

// ReactDOM must see a DOM at module initialization so its synthetic events work
// with the isolated JSDOM document installed for each interaction test.
const bootstrap = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://comparison-bootstrap.test/",
});
const bootstrapKeys = [
  "window",
  "document",
  "navigator",
  "HTMLElement",
  "HTMLInputElement",
  "Node",
  "Event",
  "MouseEvent",
  "IS_REACT_ACT_ENVIRONMENT",
];
const bootstrapPrior = new Map(
  bootstrapKeys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]),
);
for (const [key, value] of Object.entries({
  window: bootstrap.window,
  document: bootstrap.window.document,
  navigator: bootstrap.window.navigator,
  HTMLElement: bootstrap.window.HTMLElement,
  HTMLInputElement: bootstrap.window.HTMLInputElement,
  Node: bootstrap.window.Node,
  Event: bootstrap.window.Event,
  MouseEvent: bootstrap.window.MouseEvent,
  IS_REACT_ACT_ENVIRONMENT: true,
})) {
  Object.defineProperty(globalThis, key, {
    value,
    configurable: true,
    writable: true,
  });
}
const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
for (const [key, descriptor] of bootstrapPrior) {
  if (descriptor) Object.defineProperty(globalThis, key, descriptor);
  else delete globalThis[key];
}
bootstrap.window.close();

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "customer-program-comparison-"));
const external = new Map([
  ["react", pathToFileURL(require.resolve("react")).href],
  ["react/jsx-runtime", pathToFileURL(require.resolve("react/jsx-runtime")).href],
  ["react/jsx-dev-runtime", pathToFileURL(require.resolve("react/jsx-dev-runtime")).href],
]);
const externalize = (source) =>
  [...external].reduce(
    (next, [name, url]) =>
      next
        .replaceAll(`from '${name}'`, `from ${JSON.stringify(url)}`)
        .replaceAll(`from "${name}"`, `from ${JSON.stringify(url)}`),
    source,
  );

let source = fs
  .readFileSync(componentFile, "utf8")
  .replace(/import ['"][^'"]+\.css['"];?/, "")
  .replace(
    /['"]\.\.\/\.\.\/services\/programCatalogViewService['"]/,
    JSON.stringify(serviceUrl),
  )
  .replace(
    /['"]\.\.\/\.\.\/services\/programEvaluationPolicy\.js['"]/,
    JSON.stringify(policyUrl),
  );
const compiled = await transformWithEsbuild(externalize(source), componentFile, {
  loader: "jsx",
  jsx: "automatic",
  format: "esm",
});
const componentTarget = path.join(tempDir, "ProgramComparison.mjs");
fs.writeFileSync(componentTarget, externalize(compiled.code));
const ProgramComparison = (await import(pathToFileURL(componentTarget).href)).default;

function program(id, {
  name = "Duplicate program",
  type = "two_phase",
  accountSize = "25000.00",
  price = "199.99",
  profitTarget = "8.00",
  maxDailyLoss = "4.00",
  maxTotalLoss = "8.00",
  profitSplit = "80.00",
} = {}) {
  return Object.freeze({
    id,
    price,
    terms: Object.freeze({
      name,
      type,
      account_size: accountSize,
      profit_target: profitTarget,
      max_daily_loss: maxDailyLoss,
      max_total_loss: maxTotalLoss,
      profit_split: profitSplit,
    }),
  });
}

function assignedProgram(id, type, name) {
  const evaluationPolicy = approvedEvaluationPolicy(type);
  return Object.freeze({
    id,
    price: "199.99",
    terms: Object.freeze({
      name,
      type,
      account_size: "25000.00",
      profit_target: evaluationPolicy.phase_targets[0] ?? "0.00",
      max_daily_loss: evaluationPolicy.max_daily_loss,
      max_total_loss: evaluationPolicy.max_total_loss,
      profit_split: evaluationPolicy.profit_split,
      profit_split_percentage: evaluationPolicy.profit_split,
      rules: Object.freeze({
        drawdown_type: evaluationPolicy.drawdown_type,
        evaluation_policy: evaluationPolicy,
      }),
    }),
  });
}

function installDom() {
  const dom = new JSDOM(
    '<!doctype html><html><body><div id="root"></div></body></html>',
    { url: "http://customer-program-comparison.test/", pretendToBeVisual: true },
  );
  const keys = [
    "window",
    "document",
    "navigator",
    "HTMLElement",
    "HTMLInputElement",
    "Node",
    "Event",
    "MouseEvent",
    "MutationObserver",
    "getComputedStyle",
    "IS_REACT_ACT_ENVIRONMENT",
  ];
  const prior = new Map(
    keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]),
  );
  const bindings = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    HTMLElement: dom.window.HTMLElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Node: dom.window.Node,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    MutationObserver: dom.window.MutationObserver,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(bindings)) {
    Object.defineProperty(globalThis, key, {
      value,
      configurable: true,
      writable: true,
    });
  }
  const host = dom.window.document.getElementById("root");
  const root = createRoot(host);
  return {
    host,
    async render(programs) {
      await act(async () => {
        root.render(React.createElement(ProgramComparison, { programs }));
        await Promise.resolve();
      });
    },
    async close() {
      await act(async () => root.unmount());
      for (const [key, descriptor] of prior) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
      dom.window.close();
    },
  };
}

async function click(element) {
  assert.ok(element, "expected a concrete interactive element");
  await act(async () => {
    element.dispatchEvent(
      new window.MouseEvent("click", {
        bubbles: true,
        cancelable: true,
        button: 0,
      }),
    );
    await Promise.resolve();
  });
}

function checkbox(host, id) {
  return host.querySelector(`[data-program-id="${id}"] input[type="checkbox"]`);
}

function buttonByName(host, name) {
  return [...host.querySelectorAll("button")].find(
    (button) => button.getAttribute("aria-label") === name || button.textContent.trim() === name,
  );
}

test("customer comparison DOM: bounds selection, retains duplicate choices, and uses exact published Decimal/NULL values", { concurrency: false }, async () => {
  const programs = Object.freeze([
    program(101, {
      name: "Duplicate program",
      price: "1234.56",
      profitTarget: null,
      maxDailyLoss: "3.50",
    }),
    program(102, {
      name: "Duplicate program",
      price: "333.33",
      profitTarget: "7.50",
    }),
    program(103, { name: "Third program", accountSize: "50000.00", price: "444.44" }),
    program(104, { name: "Fourth program", accountSize: "100000.00", price: "555.55" }),
  ]);
  const harness = installDom();
  const priorFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.fetch = () => {
    fetchCalls += 1;
    throw new Error("Comparison must not make network requests");
  };
  try {
    await harness.render(programs);
    assert.equal(harness.host.querySelectorAll('[data-program-id]').length, 4);
    assert.equal(checkbox(harness.host, 101).checked, false, "selection defaults to empty");
    assert.equal(buttonByName(harness.host, "Clear selections").disabled, true);
    assert.equal(harness.host.querySelector("table"), null, "one or fewer selections never presents a comparison");

    await click(checkbox(harness.host, 101));
    await click(checkbox(harness.host, 102));
    assert.equal(harness.host.querySelectorAll("thead th").length, 3, "two selections produce a two-program comparison");
    assert.match(harness.host.textContent, /USD 1,234\.56/, "fee keeps its exact Decimal formatting");
    assert.match(harness.host.textContent, /USD 333\.33/, "duplicate program IDs have their own fee values");
    assert.match(harness.host.textContent, /Not specified/, "NULL published percentages are not treated as zero");
    assert.match(harness.host.textContent, /3\.5%/, "existing percent formatter removes only insignificant decimal zeros");

    await click(checkbox(harness.host, 103));
    assert.equal(harness.host.querySelectorAll("thead th").length, 4, "third selection is included");
    assert.equal(checkbox(harness.host, 104).disabled, true, "a fourth unselected checkbox is disabled at the limit");
    await click(checkbox(harness.host, 104));
    assert.equal(checkbox(harness.host, 104).checked, false, "fourth choice cannot exceed the three-program limit");
    assert.match(harness.host.textContent, /3 of 3 selected/);

    await click(buttonByName(harness.host, "Remove Duplicate program #102 from comparison"));
    assert.equal(checkbox(harness.host, 102).checked, false, "accessible removal targets the concrete duplicate ID");
    assert.equal(checkbox(harness.host, 104).disabled, false, "removal frees a comparison slot");
    await click(checkbox(harness.host, 104));
    assert.equal(harness.host.querySelectorAll("thead th").length, 4);

    await click(buttonByName(harness.host, "Clear selections"));
    assert.equal(harness.host.querySelector("table"), null, "clear returns the view to the minimum-selection state");
    assert.equal(checkbox(harness.host, 101).checked, false);
    assert.equal(checkbox(harness.host, 104).checked, false);
    assert.equal(fetchCalls, 0, "comparison interactions only consume supplied normalized catalog data");
  } finally {
    globalThis.fetch = priorFetch;
    await harness.close();
  }
});

test("customer comparison DOM: a replacement list supplies current values and an empty source removes selections immediately", { concurrency: false }, async () => {
  const initial = Object.freeze([
    program(201, { name: "Refreshable program", price: "1234.56", profitTarget: "8.00" }),
    program(202, { name: "Stable program", price: "200.00" }),
  ]);
  const replacement = Object.freeze([
    program(201, { name: "Refreshable program", price: "4321.09", profitTarget: "7.25" }),
    program(202, { name: "Stable program", price: "200.00" }),
  ]);
  const harness = installDom();
  try {
    await harness.render(initial);
    await click(checkbox(harness.host, 201));
    await click(checkbox(harness.host, 202));
    assert.match(harness.host.textContent, /USD 1,234\.56/);

    await harness.render(replacement);
    assert.match(harness.host.textContent, /USD 4,321\.09/, "same IDs use replacement program objects rather than stale selections");
    assert.equal(harness.host.textContent.includes("USD 1,234.56"), false);
    assert.match(harness.host.textContent, /7\.25%/);

    await harness.render([]);
    assert.equal(harness.host.querySelector('[data-program-comparison]'), null, "no comparison persists while the catalog source is absent");
    await harness.render(replacement);
    assert.equal(harness.host.querySelector("table"), null, "an empty/failing source clears prior selected IDs before replacement data returns");
  } finally {
    await harness.close();
  }
});

test("customer comparison DOM: full assigned stage targets render, while Instant Funding is absent from every quote-selection control", { concurrency: false }, async () => {
  const programs = Object.freeze([
    assignedProgram(3697, "two_phase", "Two-stage recorded program"),
    assignedProgram(3704, "three_phase", "Three-stage recorded program"),
    assignedProgram(3711, "instant_funding", "Instant Funding hidden from comparison"),
  ]);
  const before = JSON.stringify(programs);
  const harness = installDom();
  try {
    await harness.render(programs);
    assert.equal(harness.host.querySelectorAll('[data-program-id]').length, 2);
    assert.equal(harness.host.querySelector('[data-program-id="3711"]'), null);
    assert.doesNotMatch(harness.host.textContent, /Instant Funding hidden from comparison/);

    await click(checkbox(harness.host, 3697));
    await click(checkbox(harness.host, 3704));
    assert.match(harness.host.textContent, /Phase 1: 8% · Phase 2: 5%/);
    assert.match(harness.host.textContent, /Phase 1: 5% · Phase 2: 5% · Phase 3: 5%/);
    assert.doesNotMatch(harness.host.textContent, /Catalog ID #3711|Instant Funding hidden from comparison/);
    assert.equal(JSON.stringify(programs), before, "comparison must not mutate supplied catalog policy snapshots");
  } finally {
    await harness.close();
  }
});

test("customer comparison integration binds comparison lifetime to ready catalog data and catalog key", () => {
  const page = fs.readFileSync(pageFile, "utf8");
  assert.match(page, /import ProgramComparison from ["']\.\.\/components\/programs\/ProgramComparison["']/);
  assert.match(page, /const evaluationPrograms = programs\.filter\(\(program\) => !isProgramComingSoon\(program\.terms\)\)/);
  assert.match(page, /const catalogReady = !catalog\.loading && !catalog\.error && programs\.length > 0/);
  assert.match(page, /<ProgramComparison key=\{catalog\.key\} programs=\{evaluationPrograms\} \/>/);
  assert.doesNotMatch(source, /localStorage|fetch\s*\(/);
});

test.after(() => {
  fs.rmSync(tempDir, { recursive: true, force: true });
});
