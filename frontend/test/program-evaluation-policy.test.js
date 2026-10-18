import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const servicePath = path.join(PROJECT_ROOT, 'src', 'services', 'programEvaluationPolicy.js');
const profilesPath = path.join(PROJECT_ROOT, 'src', 'services', 'programEvaluationProfiles.json');
const source = fs.readFileSync(servicePath, 'utf8');
const sharedProfiles = JSON.parse(fs.readFileSync(profilesPath, 'utf8'));
const policy = await import(pathToFileURL(servicePath).href);

const clone = (value) => JSON.parse(JSON.stringify(value));
const profileTerms = (type) => {
  const expected = policy.approvedEvaluationPolicy(type);
  return {
    type,
    profit_target: expected.phase_targets[0] ?? '0.00',
    max_daily_loss: expected.max_daily_loss,
    max_total_loss: expected.max_total_loss,
    profit_split: expected.profit_split,
    profit_split_percentage: expected.profit_split,
    rules: {
      drawdown_type: expected.drawdown_type,
      evaluation_policy: clone(expected),
    },
  };
};

const assertNotMatched = (terms, label) => {
  const result = policy.evaluationPolicyForTerms(terms);
  assert.notEqual(result.status, 'matched', label);
  assert.equal(result.policy, null, `${label} must not return a policy`);
};

test('approved versioned snapshots use the single shared JSON source and record all approved family values', () => {
  assert.equal(policy.EVALUATION_POLICY_VERSION, sharedProfiles.version);
  assert.match(source, /programEvaluationProfiles\.json/);
  assert.equal(policy.isApprovedEvaluationSource(sharedProfiles), true);
  assert.match(source, /isApprovedEvaluationSource/);

  const expectedTargets = {
    one_phase: ['10.00'],
    two_phase: ['8.00', '5.00'],
    three_phase: ['5.00', '5.00', '5.00'],
    instant_funding: [],
  };
  for (const [type, phaseTargets] of Object.entries(expectedTargets)) {
    const snapshot = policy.approvedEvaluationPolicy(type);
    assert.deepEqual(snapshot.phase_targets, phaseTargets, type);
    assert.equal(snapshot.phases, phaseTargets.length, type);
    assert.equal(snapshot.version, sharedProfiles.version, type);
    assert.equal(snapshot.program_type, type, type);
    assert.equal(snapshot.max_daily_loss, '5.00', type);
    assert.equal(snapshot.max_total_loss, '10.00', type);
    assert.equal(snapshot.drawdown_type, 'static', type);
    assert.equal(snapshot.profit_split, '90.00', type);
    assert.equal(snapshot.operator_share, '10.00', type);
    assert.equal(snapshot.daily_loss_amount_base, 'initial_account_size', type);
    assert.equal(snapshot.daily_threshold_base, 'day_start_closed_balance', type);
    assert.equal(snapshot.breach_comparison, 'equity_less_than_or_equal_to_threshold', type);
  }
  assert.equal(policy.approvedEvaluationPolicy('not-a-family'), null);
  for (const inheritedName of ['__proto__', 'constructor', 'toString']) {
    assert.equal(policy.approvedEvaluationPolicy(inheritedName), null, inheritedName);
  }

  const instant = policy.approvedEvaluationPolicy('instant_funding');
  assert.equal(instant.availability, 'coming_soon');
  assert.equal(instant.evaluation_target_basis, null);
  assert.equal(instant.evaluation_requires_closed_positions, null);
  assert.equal(policy.isProgramComingSoon({ type: 'instant_funding' }), true);
  assert.equal(policy.isProgramComingSoon({ type: 'one_phase' }), false);
  assert.equal(policy.isProgramComingSoon(null), false);
});

test('a policy assignment requires its full versioned snapshot, exact scalar aliases and static drawdown', () => {
  for (const type of ['one_phase', 'two_phase', 'three_phase', 'instant_funding']) {
    const current = profileTerms(type);
    const before = JSON.stringify(current);
    const result = policy.evaluationPolicyForTerms(current);
    assert.equal(result.status, 'matched', type);
    assert.deepEqual(result.policy, current.rules.evaluation_policy, type);
    assert.notEqual(result.policy, current.rules.evaluation_policy, `${type} returns an isolated snapshot`);
    assert.equal(JSON.stringify(current), before, `${type} input remains unchanged`);
  }

  const unassigned = profileTerms('one_phase');
  delete unassigned.rules.evaluation_policy;
  assert.deepEqual(policy.evaluationPolicyForTerms(unassigned), { status: 'unassigned', policy: null });
  assert.deepEqual(policy.evaluationPolicyForTerms(null), { status: 'unassigned', policy: null });

  const wrongVersion = profileTerms('two_phase');
  wrongVersion.rules.evaluation_policy.version = 'mep-evaluation-families-v0';
  assert.deepEqual(policy.evaluationPolicyForTerms(wrongVersion), { status: 'unsupported', policy: null });

  for (const field of Object.keys(policy.approvedEvaluationPolicy('three_phase'))) {
    const incomplete = profileTerms('three_phase');
    delete incomplete.rules.evaluation_policy[field];
    assertNotMatched(incomplete, `missing snapshot key ${field}`);
  }
  const extended = profileTerms('one_phase');
  extended.rules.evaluation_policy.unapproved_field = true;
  assertNotMatched(extended, 'extended snapshot');
  const ownPrototypeName = profileTerms('one_phase');
  Object.defineProperty(ownPrototypeName.rules.evaluation_policy, 'constructor', {
    value: 'unapproved', enumerable: true,
  });
  assertNotMatched(ownPrototypeName, 'own constructor snapshot key');

  for (const [field, value] of [
    ['profit_target', '10'],
    ['max_daily_loss', 5],
    ['max_total_loss', '10.0'],
    ['profit_split', '90'],
    ['profit_split_percentage', '90.0'],
  ]) {
    const scalarMismatch = profileTerms('one_phase');
    scalarMismatch[field] = value;
    assertNotMatched(scalarMismatch, `${field} must retain its exact published string`);
  }
  for (const drawdown of [undefined, null, 'trailing', 'STATIC']) {
    const drawdownMismatch = profileTerms('two_phase');
    if (drawdown === undefined) delete drawdownMismatch.rules.drawdown_type;
    else drawdownMismatch.rules.drawdown_type = drawdown;
    assertNotMatched(drawdownMismatch, `drawdown ${String(drawdown)}`);
  }

  const targetOnly = profileTerms('three_phase');
  delete targetOnly.rules.evaluation_policy;
  targetOnly.profit_target = '5.00';
  targetOnly.max_daily_loss = '5.00';
  targetOnly.max_total_loss = '10.00';
  targetOnly.profit_split = targetOnly.profit_split_percentage = '90.00';
  targetOnly.rules.drawdown_type = 'static';
  assert.deepEqual(policy.evaluationPolicyForTerms(targetOnly), { status: 'unassigned', policy: null });
});

test('current catalog terms and an old stored snapshot stay isolated and are never rewritten or relabelled', () => {
  const current = profileTerms('two_phase');
  const stored = profileTerms('two_phase');
  stored.profit_target = '7.00';
  stored.rules.evaluation_policy.phase_targets[0] = '7.00';
  const currentBefore = JSON.stringify(current);
  const storedBefore = JSON.stringify(stored);

  assert.equal(policy.evaluationPolicyForTerms(current).status, 'matched');
  assert.deepEqual(policy.evaluationPolicyForTerms(stored), { status: 'mismatch', policy: null });
  assert.equal(JSON.stringify(current), currentBefore, 'current catalog terms are not modified');
  assert.equal(JSON.stringify(stored), storedBefore, 'stored order terms are not rewritten to current policy');

  const returned = policy.approvedEvaluationPolicy('two_phase');
  returned.phase_targets[0] = '99.00';
  returned.max_daily_loss = '0.00';
  assert.deepEqual(policy.approvedEvaluationPolicy('two_phase').phase_targets, ['8.00', '5.00']);
  assert.equal(policy.approvedEvaluationPolicy('two_phase').max_daily_loss, '5.00');
});

test('the pure policy performs no browser, network, storage, clock or catalog I/O', () => {
  assert.doesNotMatch(source, /\b(fetch|axios|XMLHttpRequest|localStorage|sessionStorage|Date\.now|setInterval|setTimeout)\b/);
});


for (const [label, mutate] of [
  ['unapproved target', (doc) => { doc.profiles.two_phase.phase_targets[1] = '7.00'; }],
  ['unapproved daily loss', (doc) => { doc.common.max_daily_loss = '7.00'; }],
  ['unapproved profit split', (doc) => { doc.common.profit_split = '95.00'; doc.common.operator_share = '5.00'; }],
  ['invented reset timezone', (doc) => { doc.common.daily_reset_timezone = 'UTC'; }],
  ['numeric boolean coercion', (doc) => { doc.common.phase_profit_carryover = 0; }],
  ['extra common key', (doc) => { doc.common.unapproved = true; }],
  ['unapproved version', (doc) => { doc.version = 'mep-evaluation-families-v999'; }],
  ['missing profile', (doc) => { delete doc.profiles.three_phase; }],
  ['instant purchase availability', (doc) => { doc.profiles.instant_funding.availability = 'evaluation_catalog'; }],
]) {
  test(`poisoned source fails closed without adopting ${label}`, async () => {
    const doc = clone(sharedProfiles); mutate(doc);
    assert.equal(policy.isApprovedEvaluationSource(doc), false);
    const injected = source.replace(/^import profiles from[^\n]+;/m, `const profiles = ${JSON.stringify(doc)};`);
    assert.notEqual(injected, source);
    const poisoned = await import(`data:text/javascript;base64,${Buffer.from(injected).toString('base64')}`);
    assert.equal(poisoned.isApprovedEvaluationSource(), false);
    for (const type of ['one_phase', 'two_phase', 'three_phase', 'instant_funding']) {
      assert.equal(poisoned.approvedEvaluationPolicy(type), null);
      assert.deepEqual(poisoned.evaluationPolicyForTerms(profileTerms(type)), { status: 'unsupported', policy: null });
    }
    assert.equal(poisoned.isProgramComingSoon({ type: 'instant_funding' }), true);
    assert.match(poisoned.EVALUATION_RULES_FAQ.trading, /unavailable/);
    assert.doesNotMatch(poisoned.EVALUATION_RULES_FAQ.trading + poisoned.EVALUATION_RULES_FAQ.payout, /\d+%/);
  });
}

test('malformed or reordered source is checked by exact shape and values, not object order or defaults', () => {
  for (const doc of [null, [], {}, { version: sharedProfiles.version }]) assert.equal(policy.isApprovedEvaluationSource(doc), false);
  const reordered = Object.fromEntries(Object.entries(clone(sharedProfiles)).reverse());
  assert.equal(policy.isApprovedEvaluationSource(reordered), true);
});

test('owner-approved account description is explicit, immutable and separate from the recorded v1 policy', () => {
  const model = policy.APPROVED_ACCOUNT_MODEL;
  assert.equal(model.version, 'mep-simulated-rewards-description-v1');
  assert.equal(model.evaluation, 'simulated');
  assert.equal(model.postEvaluation, 'simulated');
  assert.equal(model.rewardProvider, 'operator');
  assert.equal(Object.isFrozen(model), true);
  assert.match(model.description, /simulated trading.*evaluation.*account after passing/);
  assert.match(model.description, /MarketEdgePros operator.*not withdrawals/);
  assert.match(model.availability, /not an active trading account or an enabled payout service/);
  for (const type of ['one_phase', 'two_phase', 'three_phase']) {
    const before = profileTerms(type);
    assert.equal(before.rules.evaluation_policy.funded_account_type, null);
    assert.equal(policy.evaluationPolicyForTerms(before).status, 'matched');
    assert.equal(before.rules.evaluation_policy.version, 'mep-evaluation-families-v1');
    assert.equal(Object.hasOwn(before.rules.evaluation_policy, 'rewardProvider'), false);
  }
});

test('FAQ description states simulation and operator rewards without inventing availability or leaving account type undecided', () => {
  for (const copy of [policy.EVALUATION_RULES_FAQ.trading, policy.EVALUATION_RULES_FAQ.payout]) {
    assert.ok(copy.includes(policy.APPROVED_ACCOUNT_MODEL.description));
    assert.match(copy, /90%.*10%/);
    assert.doesNotMatch(copy, /account type still require|real-capital or simulated-account model/);
    assert.match(copy, /Coming soon/);
  }
  assert.match(policy.EVALUATION_RULES_FAQ.payout, /Payouts are not enabled/);
});
