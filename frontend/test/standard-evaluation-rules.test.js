import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { JSDOM } from 'jsdom';
import { transformWithEsbuild } from 'vite';
import {
  EVALUATION_RULES_FAQ,
  approvedEvaluationPolicy,
  evaluationPolicyForTerms,
} from '../src/services/programEvaluationPolicy.js';
import { PROGRAM_RULE_FAMILIES, programRulesPath } from '../src/services/programRuleFamilies.js';

const require = createRequire(import.meta.url);
const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'program-evaluation-rules-'));
const src = (...parts) => path.join(PROJECT_ROOT, 'src', ...parts);
const srcUrl = (...parts) => pathToFileURL(src(...parts)).href;
const policyUrl = srcUrl('services', 'programEvaluationPolicy.js');
const viewUrl = srcUrl('services', 'programCatalogViewService.js');
const standardUrl = srcUrl('services', 'standardEvaluationPolicy.js');
let comingSoonUrl;
let uiUrl;
let familyUrl;

async function compile(page) {
  const relative = page.includes('/') ? page : `pages/${page}`;
  let source = fs.readFileSync(path.join(PROJECT_ROOT, 'src', `${relative}.jsx`), 'utf8');
  source = source
    .replace(/import Layout from ['"][^'"]+['"];?/, 'const Layout = ({children}) => <main>{children}</main>;')
    .replace(/from ['"][^'"]+programEvaluationPolicy\.js['"]/g, `from ${JSON.stringify(policyUrl)}`)
    .replace(/from ['"][^'"]+standardEvaluationPolicy\.js['"]/g, `from ${JSON.stringify(standardUrl)}`)
    .replace(/from ['"][^'"]+programRuleFamilies\.js['"]/g, `from ${JSON.stringify(srcUrl('services', 'programRuleFamilies.js'))}`)
    .replace(/from ['"][^'"]+programCatalogViewService(?:\.js)?['"]/g, `from ${JSON.stringify(viewUrl)}`)
    .replace(/import useProgramCatalog from ['"][^'"]+['"];?/, 'const useProgramCatalog = () => ({ loading: false, error: "", data: [], retry() {} });')
    .replace(/from ['"][^'"]*ComingSoonProgram['"]/g, `from ${JSON.stringify(comingSoonUrl)}`)
    .replace(/from ['"][^'"]*CatalogUI['"]/g, `from ${JSON.stringify(uiUrl)}`)
    .replace(/from ['"][^'"]+ProgramRuleFamily['"]/g, `from ${JSON.stringify(familyUrl)}`);
  for (const dep of ['react', 'react-router-dom', 'lucide-react']) {
    for (const quote of ["'", '"']) {
      source = source.replaceAll(`from ${quote}${dep}${quote}`, `from ${JSON.stringify(pathToFileURL(require.resolve(dep)).href)}`);
    }
  }
  const { code } = await transformWithEsbuild(source, `${page}.jsx`, { loader: 'jsx', jsx: 'transform', format: 'esm' });
  const file = path.join(dir, `${page.replaceAll('/', '-')}.mjs`);
  fs.writeFileSync(file, code);
  return (await import(pathToFileURL(file).href)).default;
}

const ComingSoonProgram = await compile('components/programs/ComingSoonProgram');
comingSoonUrl = pathToFileURL(path.join(dir, 'components-programs-ComingSoonProgram.mjs')).href;
await compile('components/programs/CatalogUI');
uiUrl = pathToFileURL(path.join(dir, 'components-programs-CatalogUI.mjs')).href;
const Family = await compile('components/programs/ProgramRuleFamily');
familyUrl = pathToFileURL(path.join(dir, 'components-programs-ProgramRuleFamily.mjs')).href;
const Rules = await compile('TradingRules');
const Terms = await compile('TermsOfService');
const view = (Component, props = {}) => new JSDOM(renderToStaticMarkup(
  React.createElement(MemoryRouter, { initialEntries: ['/trading-rules'] }, React.createElement(Component, props)),
)).window.document;

const assignedTerms = (type, name = `${type} recorded`) => {
  const evaluationPolicy = approvedEvaluationPolicy(type);
  return {
    name,
    type,
    account_size: '25000.00',
    profit_target: evaluationPolicy.phase_targets[0] ?? '0.00',
    max_daily_loss: evaluationPolicy.max_daily_loss,
    max_total_loss: evaluationPolicy.max_total_loss,
    profit_split: evaluationPolicy.profit_split,
    profit_split_percentage: evaluationPolicy.profit_split,
    minimum_payout_amount: null,
    payout_mode: null,
    rules: {
      drawdown_type: evaluationPolicy.drawdown_type,
      evaluation_policy: structuredClone(evaluationPolicy),
    },
  };
};

test('approved evaluation profiles define three assigned routes, their exact stage targets, and common loss/profit-share definitions', () => {
  for (const [type, targets] of [
    ['one_phase', ['10.00']],
    ['two_phase', ['8.00', '5.00']],
    ['three_phase', ['5.00', '5.00', '5.00']],
  ]) {
    const policy = approvedEvaluationPolicy(type);
    assert.deepEqual(policy.phase_targets, targets, type);
    assert.equal(policy.phases, targets.length, type);
    assert.equal(policy.max_daily_loss, '5.00', type);
    assert.equal(policy.max_total_loss, '10.00', type);
    assert.equal(policy.drawdown_type, 'static', type);
    assert.equal(policy.profit_split, '90.00', type);
    assert.equal(policy.operator_share, '10.00', type);
  }
  const instant = approvedEvaluationPolicy('instant_funding');
  assert.equal(instant.availability, 'coming_soon');
  assert.deepEqual(instant.phase_targets, []);
  assert.equal(instant.phases, 0);
});

test('a complete assignment is explicit, while matching legacy scalar values remain unassigned and immutable', () => {
  const current = assignedTerms('two_phase');
  const before = JSON.stringify(current);
  const matched = evaluationPolicyForTerms(current);
  assert.equal(matched.status, 'matched');
  assert.deepEqual(matched.policy.phase_targets, ['8.00', '5.00']);
  assert.equal(JSON.stringify(current), before);

  const legacy = assignedTerms('two_phase', 'legacy two-phase');
  delete legacy.rules.evaluation_policy;
  assert.deepEqual(evaluationPolicyForTerms(legacy), { status: 'unassigned', policy: null });
  assert.equal(legacy.profit_target, '8.00');
  assert.equal(legacy.rules.drawdown_type, 'static');

  const inconsistent = assignedTerms('three_phase');
  inconsistent.rules.evaluation_policy.phase_targets[2] = '4.00';
  assert.deepEqual(evaluationPolicyForTerms(inconsistent), { status: 'mismatch', policy: null });
});

test('trading rules render shared definitions and a truthful unavailable assignment status, not the retired universal one-phase rollout', () => {
  const doc = view(Rules);
  assert.equal(doc.querySelectorAll('main').length, 1);
  assert.equal(doc.querySelectorAll('h1').length, 1);
  assert.deepEqual([...doc.querySelectorAll('[data-shared-risk-policy] dd')].map((node) => node.textContent), ['5%', '10%', '90%', '10%']);
  assert.match(doc.body.textContent, /Catalog policy status unavailable/);
  assert.match(doc.body.textContent, /matching percentage alone is not an assignment/);
  assert.match(doc.body.textContent, /Instant Funding remains Coming soon/);
  assert.doesNotMatch(doc.body.textContent, /Approved standard evaluation model|Catalog rollout pending/);
  assert.match(doc.body.textContent, /one-phase has one target, two-phase has two and three-phase has three/);
  for (const family of PROGRAM_RULE_FAMILIES) {
    assert.ok(doc.getElementById(family.anchor));
    assert.ok(doc.querySelector(`nav a[href="/trading-rules#${family.anchor}"]`));
    assert.equal(programRulesPath(family.type), `/trading-rules#${family.anchor}`);
  }
  assert.equal(programRulesPath('unknown'), '/trading-rules');
});

test('family SSR renders recorded phase targets for three evaluation types, retains an unassigned legacy program, and makes Instant Funding non-selectable', () => {
  const rows = [
    { id: 3690, terms: assignedTerms('one_phase', 'one recorded') },
    { id: 3697, terms: assignedTerms('two_phase', 'two recorded') },
    { id: 3704, terms: assignedTerms('three_phase', 'three recorded') },
  ];
  const before = JSON.stringify(rows);
  for (const family of PROGRAM_RULE_FAMILIES.filter(({ type }) => type !== 'instant_funding')) {
    const doc = view(Family, { family, programs: rows });
    const policy = approvedEvaluationPolicy(family.type);
    assert.equal(doc.querySelectorAll('option').length, 1, family.type);
    assert.equal(doc.querySelector('[data-family-program]').getAttribute('data-family-program'), String(rows.find((row) => row.terms.type === family.type).id));
    for (const [index, target] of policy.phase_targets.entries()) {
      assert.match(doc.body.textContent, new RegExp(`Phase ${index + 1} profit target`));
      assert.match(doc.body.textContent, new RegExp(`${target.replace('.00', '')}%`));
    }
    assert.match(doc.body.textContent, /Operator share of eligible profit/);
    assert.doesNotMatch(doc.body.textContent, /Individual stage targets.*require confirmation/);
  }
  const legacy = { id: 3999, terms: assignedTerms('two_phase', 'legacy recorded') };
  delete legacy.terms.rules.evaluation_policy;
  const legacyDoc = view(Family, { family: PROGRAM_RULE_FAMILIES[1], programs: [legacy] });
  assert.match(legacyDoc.body.textContent, /approved policy has not been assigned/);
  assert.match(legacyDoc.body.textContent, /Individual stage targets are not inferred/);
  assert.match(legacyDoc.body.textContent, /Profit target/);

  const instantDoc = view(Family, { family: PROGRAM_RULE_FAMILIES[3], programs: [{ id: 3711, terms: assignedTerms('instant_funding') }] });
  assert.match(instantDoc.body.textContent, /Coming soon/);
  assert.match(instantDoc.body.textContent, /not available for purchase, quote requests or new payments/);
  assert.equal(instantDoc.querySelector('select'), null);
  assert.equal(instantDoc.querySelector('[data-family-program]'), null);
  assert.equal(instantDoc.querySelector('a[href="/programs/3711"]'), null);
  assert.doesNotMatch(instantDoc.body.textContent, /Catalog base fee|USD/);
  assert.equal(JSON.stringify(rows), before, 'rendering never writes supplied catalog terms');
});

test('the shared FAQ and terms require all three evaluation policy types, describe Instant Funding as unavailable, and invent no operator or contractual readiness', () => {
  const termsSource = fs.readFileSync(src('pages', 'TermsOfService.jsx'), 'utf8');
  const faqSource = fs.readFileSync(src('pages', 'FAQ.jsx'), 'utf8');
  assert.match(termsSource, /EVALUATION_RULES_FAQ|programEvaluationPolicy/);
  assert.match(termsSource, /one-phase.*two-phase.*three-phase/i);
  assert.match(termsSource, /Instant Funding.*Coming soon|Coming soon.*Instant Funding/i);
  assert.doesNotMatch(termsSource, /STANDARD_EVALUATION_POLICY|Catalog rollout is pending|approved standard update concerns a single-stage/i);
  assert.match(faqSource, /EVALUATION_RULES_FAQ/);
  assert.doesNotMatch(faqSource, /STANDARD_RULES_FAQ|standardEvaluationPolicy/);
  assert.match(EVALUATION_RULES_FAQ.trading, /One-phase uses a 10% evaluation target.*Two-phase uses 8% then 5%.*Three-phase uses 5%/);
  assert.match(EVALUATION_RULES_FAQ.payout, /90%.*10%.*Instant Funding is Coming soon/);

  const doc = view(Terms);
  assert.match(doc.body.textContent, /Contractual policy is not complete/);
  assert.match(doc.body.textContent, /No registered company/);
  assert.doesNotMatch(doc.body.textContent, /registered in [A-Z]|governed by the laws of|non-refundable/i);
});

test('policy and UI display paths remain local, source-backed and do not add payment, trading or catalog I/O', () => {
  const policySource = fs.readFileSync(src('services', 'programEvaluationPolicy.js'), 'utf8');
  const details = fs.readFileSync(src('pages', 'ProgramDetails.jsx'), 'utf8');
  const checkout = fs.readFileSync(src('pages', 'Checkout.jsx'), 'utf8');
  assert.doesNotMatch(policySource, /fetch\(|axios|setInterval|localStorage|sessionStorage|Date\.now/);
  assert.match(details, /isProgramComingSoon\(program\.terms\)/);
  assert.match(details, /<ComingSoonProgram showTitle=\{false\} \/>/);
  assert.doesNotMatch(details, /isProgramComingSoon\(program\.terms\)[\s\S]{0,240}Check quote availability/);
  assert.match(checkout, /instantComingSoon/);
  assert.match(checkout, /instantComingSoon && !savedOrderId/);
  assert.match(checkout, /No new payment is available for Instant Funding/);
  assert.doesNotMatch(checkout, /instantComingSoon[\s\S]{0,120}requestOrderQuote/);
});

test.after(() => fs.rmSync(dir, { recursive: true, force: true }));

test('account model is readable ordinary rules/terms content, never a heading, popup or completed agreement', () => {
  for (const Component of [Rules, Terms]) {
    const doc = view(Component);
    const note = doc.querySelector('[data-account-model="mep-simulated-rewards-description-v1"]');
    assert.ok(note);
    assert.equal(note.tagName, 'P');
    assert.match(note.textContent, /simulated trading/);
    assert.match(note.textContent, /MarketEdgePros operator/);
    assert.match(note.className, /text-(sm|slate-300)/);
    assert.equal(note.closest('dialog,[role="dialog"],[aria-modal="true"]'), null);
    assert.equal(note.hasAttribute('hidden'), false);
    assert.equal(note.hasAttribute('aria-hidden'), false);
    assert.doesNotMatch(note.className, /sr-only|opacity-0|text-xs|hidden/);
    assert.equal([...doc.querySelectorAll('h1,h2,h3,h4')].some(node => /simulated trading|simulated account/i.test(node.textContent)), false);
    assert.equal(doc.querySelectorAll('input[type="checkbox"]').length, 0);
  }
  assert.match(view(Terms).body.textContent, /Contractual policy is not complete/);
});
