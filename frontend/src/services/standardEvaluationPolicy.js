// Retained v1 snapshot compatibility. New assignments use the family policy.
// No runtime writes, network calls or live trading/payout enforcement.
import { EVALUATION_RULES_FAQ } from './programEvaluationPolicy.js';
export const STANDARD_EVALUATION_POLICY = Object.freeze({
  version: 'mep-standard-evaluation-v1',
  phases: 1,
  profit_target: '10.00',
  max_daily_loss: '5.00',
  max_total_loss: '10.00',
  drawdown_type: 'static',
  profit_split: '90.00',
  operator_share: '10.00',
  daily_loss_amount_base: 'initial_account_size',
  daily_threshold_base: 'day_start_closed_balance',
  breach_comparison: 'equity_less_than_or_equal_to_threshold',
  evaluation_target_basis: 'closed_profit_after_trading_costs',
  evaluation_requires_closed_positions: true,
  daily_reset_timezone: null,
  daily_reset_time: null,
  funded_account_type: null,
  minimum_trading_days: null,
  maximum_trading_days: null,
  eligible_profit_definition: null,
  payout_schedule: null,
});

// Backwards-compatible export name, not a second copy of the FAQ content.
export const STANDARD_RULES_FAQ = EVALUATION_RULES_FAQ;

// An explicit frozen copy can later be assigned to a program's rules JSON and
// retained by the existing immutable order-snapshot protocol. Never infer a policy
// from matching percentages alone or apply it to an untagged legacy program.
export function standardPolicyForTerms(terms) {
  const recorded = terms?.rules?.standard_evaluation_policy;
  if (!recorded) return { status: 'unassigned', policy: null };
  if (recorded.version !== STANDARD_EVALUATION_POLICY.version) return { status: 'unsupported', policy: null };
  const expected = STANDARD_EVALUATION_POLICY;
  const keys = Object.keys(expected);
  const matches = typeof recorded === 'object' && !Array.isArray(recorded)
    && Object.keys(recorded).length === keys.length
    && keys.every((key) => recorded[key] === expected[key])
    && terms.type === 'one_phase'
    && ['profit_target', 'max_daily_loss', 'max_total_loss', 'profit_split'].every((key) => terms[key] === expected[key])
    && terms.profit_split_percentage === expected.profit_split
    && terms.rules.drawdown_type === expected.drawdown_type;
  return matches
    ? { status: 'matched', policy: recorded }
    : { status: 'mismatch', policy: null };
}
