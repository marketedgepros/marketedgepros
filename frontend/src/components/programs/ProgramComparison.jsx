import React, { useEffect, useId, useMemo, useState } from "react";
import { evaluationPolicyForTerms, isProgramComingSoon } from "../../services/programEvaluationPolicy.js";
import {
  formatCatalogMoney,
  formatCatalogPercent,
  typeLabel,
} from "../../services/programCatalogViewService";

import "./programComparison.css";

const MAX_SELECTED_PROGRAMS = 3;

const comparisonRows = [
  ["Catalog base fee", (program) => formatCatalogMoney(program.price)],
  ["Account size", (program) => formatCatalogMoney(program.terms.account_size)],
  ["Program type", (program) => typeLabel(program.terms.type)],
  ["Profit target", (program) => {
    const result = evaluationPolicyForTerms(program.terms);
    return result.status === "matched"
      ? result.policy.phase_targets.map((value, index) => `Phase ${index + 1}: ${formatCatalogPercent(value)}`).join(" · ")
      : formatCatalogPercent(program.terms.profit_target);
  }],
  [
    "Maximum daily loss",
    (program) => formatCatalogPercent(program.terms.max_daily_loss),
  ],
  [
    "Maximum total loss",
    (program) => formatCatalogPercent(program.terms.max_total_loss),
  ],
  ["Profit split", (program) => formatCatalogPercent(program.terms.profit_split)],
];

const programLabel = (program) => `${program.terms.name} #${program.id}`;

/**
 * Compares only the normalized catalog list passed by its parent. It keeps IDs,
 * rather than program objects, so a refreshed list always supplies current values.
 */
export default function ProgramComparison({ programs: catalogPrograms }) {
  const programs = useMemo(() => catalogPrograms.filter((program) => !isProgramComingSoon(program.terms)), [catalogPrograms]);
  const headingId = useId();
  const instructionsId = useId();
  const limitId = useId();
  const [selectedIds, setSelectedIds] = useState([]);

  const availableIds = useMemo(
    () => new Set(programs.map((program) => program.id)),
    [programs],
  );

  useEffect(() => {
    setSelectedIds((current) => current.filter((id) => availableIds.has(id)));
  }, [availableIds]);

  const selectedPrograms = selectedIds
    .map((id) => programs.find((program) => program.id === id))
    .filter(Boolean);
  const selectedIdSet = new Set(selectedPrograms.map((program) => program.id));
  const hasComparison = selectedPrograms.length >= 2;

  const toggleProgram = (id) => {
    setSelectedIds((current) => {
      if (current.includes(id)) return current.filter((currentId) => currentId !== id);
      if (current.length >= MAX_SELECTED_PROGRAMS) return current;
      return [...current, id];
    });
  };

  const removeProgram = (id) => {
    setSelectedIds((current) => current.filter((currentId) => currentId !== id));
  };

  if (!programs.length) return null;

  return (
    <section
      id="program-comparison"
      className="program-comparison mb-12 scroll-mt-24"
      aria-labelledby={headingId}
      data-program-comparison="true"
    >
      <div className="program-comparison__heading">
        <div>
          <p className="program-comparison__eyebrow">Published values only</p>
          <h2 className="mep-heading" id={headingId}>Compare selected programs</h2>
          <p className="program-comparison__intro" id={instructionsId}>
            Select up to three distinct catalog programs. Choose at least two to
            compare their published values side by side.
          </p>
        </div>
        <p className="program-comparison__count" aria-live="polite" aria-atomic="true">
          {selectedPrograms.length} of {MAX_SELECTED_PROGRAMS} selected
        </p>
      </div>

      <div className="program-comparison__selection">
        <fieldset aria-describedby={`${instructionsId} ${limitId}`}>
          <legend>Select programs to compare</legend>
          <p className="program-comparison__limit" id={limitId}>
            Maximum {MAX_SELECTED_PROGRAMS} programs. Programs with the same name
            or account size remain separate choices by catalog ID.
          </p>
          <div className="program-comparison__choices">
            {programs.map((program) => {
              const selected = selectedIdSet.has(program.id);
              const atLimit = !selected && selectedPrograms.length >= MAX_SELECTED_PROGRAMS;
              return (
                <label
                  className={`program-comparison__choice${selected ? " program-comparison__choice--selected" : ""}`}
                  key={program.id}
                  data-program-id={program.id}
                >
                  <input
                    type="checkbox"
                    checked={selected}
                    disabled={atLimit}
                    onChange={() => toggleProgram(program.id)}
                    aria-label={`Select ${programLabel(program)} for comparison`}
                  />
                  <span className="program-comparison__choice-copy">
                    <span className="program-comparison__choice-name">
                      {program.terms.name}
                    </span>
                    <span className="program-comparison__choice-details">
                      {typeLabel(program.terms.type)} · {formatCatalogMoney(program.terms.account_size)} · #{program.id}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>

        <div className="program-comparison__actions" aria-label="Comparison selections">
          {selectedPrograms.length ? (
            <ul className="program-comparison__selected-list" aria-label="Selected programs">
              {selectedPrograms.map((program) => (
                <li key={program.id}>
                  <span>{programLabel(program)}</span>
                  <button
                    type="button"
                    onClick={() => removeProgram(program.id)}
                    aria-label={`Remove ${programLabel(program)} from comparison`}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="program-comparison__empty">No programs selected yet.</p>
          )}
          <button
            className="program-comparison__clear"
            type="button"
            onClick={() => setSelectedIds([])}
            disabled={!selectedPrograms.length}
          >
            Clear selections
          </button>
        </div>
      </div>

      {hasComparison ? (
        <div className="program-comparison__table-wrap">
          <table className="program-comparison__table">
            <caption>Published program values</caption>
            <thead>
              <tr>
                <th scope="col">Published value</th>
                {selectedPrograms.map((program) => (
                  <th scope="col" key={program.id}>
                    <span>{program.terms.name}</span>
                    <small>Catalog ID #{program.id}</small>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {comparisonRows.map(([label, valueFor]) => (
                <tr key={label}>
                  <th scope="row">{label}</th>
                  {selectedPrograms.map((program) => (
                    <td
                      data-label={`${program.terms.name} — ${label}`}
                      key={program.id}
                    >
                      {valueFor(program) ?? "Not specified"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="program-comparison__status" role="status">
          Select at least two programs to compare published values.
        </p>
      )}

      <aside className="program-comparison__glossary" aria-label="Comparison glossary">
        <h3>Published-value glossary</h3>
        <dl>
          <div>
            <dt>Catalog base fee</dt>
            <dd>The base fee listed in the current catalog.</dd>
          </div>
          <div>
            <dt>Account size</dt>
            <dd>The account size published for that program.</dd>
          </div>
          <div>
            <dt>Profit target, daily loss and total loss</dt>
            <dd>Stage targets come from a full recorded policy. A legacy single target is not assumed to repeat in every stage. Missing values are shown as Not specified.</dd>
          </div>
          <div>
            <dt>Profit split</dt>
            <dd>The published percentage value for the program.</dd>
          </div>
        </dl>
      </aside>
    </section>
  );
}
