// Structural catalog families only: no default percentages, assignments or IO.
export const PROGRAM_RULE_FAMILIES = Object.freeze([
  Object.freeze({ type: 'one_phase', title: 'One-phase evaluation', stages: 1, anchor: 'one-phase-rules', description: 'A single evaluation stage. Review the selected program’s recorded target, loss limits and additional settings.' }),
  Object.freeze({ type: 'two_phase', title: 'Two-phase evaluation', stages: 2, anchor: 'two-phase-rules', description: 'Two evaluation stages. The catalog target below is not an approved target for each individual stage.' }),
  Object.freeze({ type: 'three_phase', title: 'Three-phase evaluation', stages: 3, anchor: 'three-phase-rules', description: 'Three evaluation stages. The catalog target below must not be assumed to repeat in every stage.' }),
  Object.freeze({ type: 'instant_funding', title: 'Instant Funding', stages: 0, anchor: 'instant-funding-rules', description: 'The catalog family without an evaluation stage. Its name does not confirm immediate funding, account delivery or live trading.' }),
]);

export function programRulesPath(type) {
  const family = PROGRAM_RULE_FAMILIES.find((item) => item.type === type);
  return family ? `/trading-rules#${family.anchor}` : '/trading-rules';
}
