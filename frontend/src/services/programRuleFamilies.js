// Structural catalog families only: no default percentages, assignments or IO.
export const PROGRAM_RULE_FAMILIES = Object.freeze([
  Object.freeze({ type: 'one_phase', title: 'One-phase evaluation', stages: 1, anchor: 'one-phase-rules', description: 'A single evaluation stage. Review the selected program’s recorded target, loss limits and additional settings.' }),
  Object.freeze({ type: 'two_phase', title: 'Two-phase evaluation', stages: 2, anchor: 'two-phase-rules', description: 'Two evaluation stages with separate targets in the program’s recorded policy. Each stage starts at the selected initial account size.' }),
  Object.freeze({ type: 'three_phase', title: 'Three-phase evaluation', stages: 3, anchor: 'three-phase-rules', description: 'Three evaluation stages with separate recorded targets. Profit and loss are not carried into the next stage under the assigned policy.' }),
  Object.freeze({ type: 'instant_funding', title: 'Instant Funding', stages: 0, anchor: 'instant-funding-rules', description: 'Coming soon. This family is not available for quotes, purchases or new payments. No launch date or account delivery is promised.' }),
]);

export function programRulesPath(type) {
  const family = PROGRAM_RULE_FAMILIES.find((item) => item.type === type);
  return family ? `/trading-rules#${family.anchor}` : '/trading-rules';
}
