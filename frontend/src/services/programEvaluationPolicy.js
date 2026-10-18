import profiles from './programEvaluationProfiles.json' with { type: 'json' };

const record = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const clone = (value) => JSON.parse(JSON.stringify(value));
const percent = (value) => `${value.replace('.00', '')}%`;
// Owner-approved product description, not a replacement for a stored v1 policy
// or evidence of a provisioned account, paid reward or historical order term.
export const APPROVED_ACCOUNT_MODEL = Object.freeze({
  version: 'mep-simulated-rewards-description-v1',
  evaluation: 'simulated',
  postEvaluation: 'simulated',
  rewardProvider: 'operator',
  description: 'The program model uses simulated trading for both the evaluation and the account after passing. Eligible rewards are the responsibility of the MarketEdgePros operator, not withdrawals of the displayed account capital.',
  availability: 'This describes the approved account model, not an active trading account or an enabled payout service. Account delivery, reward eligibility and payout timing still require a complete approved policy.',
});
// Validation pin, not an alternative data source or a fallback policy. A new
// owner-approved version must deliberately update this pin and the backend pin.
const approvedContract = {
  version: 'mep-evaluation-families-v1',
  common: {
    max_daily_loss: '5.00', max_total_loss: '10.00', drawdown_type: 'static',
    profit_split: '90.00', operator_share: '10.00',
    daily_loss_amount_base: 'initial_account_size', daily_threshold_base: 'day_start_closed_balance',
    breach_comparison: 'equity_less_than_or_equal_to_threshold',
    evaluation_target_basis: 'closed_profit_after_trading_costs', evaluation_requires_closed_positions: true,
    phase_reset_basis: 'initial_account_size', phase_profit_carryover: false, phase_loss_carryover: false,
    daily_reset_timezone: null, daily_reset_time: null, funded_account_type: null,
    eligible_profit_definition: null, payout_schedule: null,
  },
  profiles: {
    one_phase: { availability: 'evaluation_catalog', phase_targets: ['10.00'] },
    two_phase: { availability: 'evaluation_catalog', phase_targets: ['8.00', '5.00'] },
    three_phase: { availability: 'evaluation_catalog', phase_targets: ['5.00', '5.00', '5.00'] },
    instant_funding: { availability: 'coming_soon', phase_targets: [], evaluation_target_basis: null,
      evaluation_requires_closed_positions: null, phase_reset_basis: null, phase_profit_carryover: null, phase_loss_carryover: null },
  },
};

function exactJson(expected, actual) {
  if (Array.isArray(expected)) return Array.isArray(actual) && actual.length === expected.length && expected.every((value, index) => exactJson(value, actual[index]));
  if (record(expected)) {
    if (!record(actual)) return false;
    const keys = Object.keys(expected);
    return Object.keys(actual).length === keys.length && keys.every((key) => Object.prototype.hasOwnProperty.call(actual, key) && exactJson(expected[key], actual[key]));
  }
  return Object.is(expected, actual);
}

export const EVALUATION_POLICY_VERSION = approvedContract.version;
export function isApprovedEvaluationSource(document = profiles) { return exactJson(approvedContract, document); }

export function approvedEvaluationPolicy(type) {
  if (!isApprovedEvaluationSource() || typeof type !== 'string' || !Object.prototype.hasOwnProperty.call(profiles.profiles, type)) return null;
  const profile = profiles.profiles[type];
  return clone({ version: profiles.version, program_type: type, ...profiles.common, ...profile, phases: profile.phase_targets.length });
}

export const isProgramComingSoon = (terms) => terms?.type === 'instant_funding';

export function evaluationPolicyForTerms(terms) {
  if (!isApprovedEvaluationSource()) return { status: 'unsupported', policy: null };
  const stored = terms?.rules?.evaluation_policy;
  if (stored === undefined) return { status: 'unassigned', policy: null };
  if (!record(stored)) return { status: 'mismatch', policy: null };
  if (stored.version !== EVALUATION_POLICY_VERSION) return { status: 'unsupported', policy: null };
  const expected = approvedEvaluationPolicy(terms?.type);
  if (!expected) return { status: 'unsupported', policy: null };
  const firstTarget = expected.phase_targets[0] ?? '0.00';
  const matchingTerms = terms.profit_target === firstTarget
    && terms.max_daily_loss === expected.max_daily_loss
    && terms.max_total_loss === expected.max_total_loss
    && terms.profit_split === expected.profit_split
    && terms.profit_split_percentage === expected.profit_split
    && terms.rules.drawdown_type === expected.drawdown_type;
  return exactJson(expected, stored) && matchingTerms
    ? { status: 'matched', policy: clone(stored) }
    : { status: 'mismatch', policy: null };
}

const targets = (type, separator) => profiles.profiles[type].phase_targets.map(percent).join(separator);
const unavailable = 'The approved evaluation policy is unavailable. No substitute targets, loss limits, profit split, funding or payout terms are assumed. Review the current program information before relying on any offer. Instant Funding remains Coming soon.';
export const EVALUATION_RULES_FAQ = Object.freeze(isApprovedEvaluationSource() ? {
  trading: `One-phase uses a ${targets('one_phase', ' / ')} evaluation target. Two-phase uses ${targets('two_phase', ' then ')}. Three-phase uses ${targets('three_phase', ' / ')} across its three stages. The approved evaluation policies use a ${percent(profiles.common.max_daily_loss)} maximum daily loss based on initial account size, a ${percent(profiles.common.max_total_loss)} fixed maximum total loss and a ${percent(profiles.common.profit_split)} trader / ${percent(profiles.common.operator_share)} operator share of eligible profit. Read your selected program’s recorded policy and each stage’s target. A new stage starts at the selected initial account size without carrying profit or loss forward; targets require closed positions, trading costs and no breach. A policy is assigned only when its full versioned snapshot is recorded in the program; a legacy listing or order keeps its own terms. ${APPROVED_ACCOUNT_MODEL.description} Instant Funding is Coming soon and cannot be purchased. Account delivery, daily reset timezone and payout availability remain unconfirmed.`,
  payout: `The approved evaluation policies allocate ${percent(profiles.common.profit_split)} of eligible profit to the trader and ${percent(profiles.common.operator_share)} to the operator. A saved order retains its recorded profit split; a new catalog policy never rewrites it. ${APPROVED_ACCOUNT_MODEL.description} This is not a share of account capital, an evaluation-profit entitlement or a guaranteed return. Reward eligibility, the precise eligible-profit definition, schedule and methods still require confirmation. Payouts are not enabled. Instant Funding is Coming soon; it is not available for quotes, purchases or new payments.`,
} : { trading: unavailable, payout: unavailable });
