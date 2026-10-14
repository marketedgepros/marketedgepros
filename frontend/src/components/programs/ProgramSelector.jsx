import React, { useEffect, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ProgramRules, primaryAction } from "./CatalogUI";
import ComingSoonProgram from "./ComingSoonProgram";
import { isProgramComingSoon } from "../../services/programEvaluationPolicy.js";
import {
  formatCatalogMoney,
  typeLabel,
} from "../../services/programCatalogViewService";

import "./programSelector.css";

const uniqueValues = (items, valueFor) => {
  const seen = new Set();
  return items.reduce((values, item) => {
    const value = valueFor(item);
    if (!seen.has(value)) {
      seen.add(value);
      values.push(value);
    }
    return values;
  }, []);
};

/**
 * A presentational chooser for already-normalized catalog data. It intentionally
 * performs no catalog reads, sorting, or mutation of the supplied program list.
 */
export default function ProgramSelector({ programs: catalogPrograms }) {
  const programs = useMemo(() => catalogPrograms.filter((program) => !isProgramComingSoon(program.terms)), [catalogPrograms]);
  const headingId = useId();
  const [selectedId, setSelectedId] = useState(() => programs[0]?.id ?? null);
  const selectedProgram =
    programs.find((program) => program.id === selectedId) || programs[0] || null;

  useEffect(() => {
    const current = programs.find((program) => program.id === selectedId);
    const nextId = current?.id ?? programs[0]?.id ?? null;
    if (nextId !== selectedId) setSelectedId(nextId);
  }, [programs, selectedId]);

  const types = useMemo(
    () => uniqueValues(programs, (program) => program.terms.type),
    [programs],
  );
  const typePrograms = useMemo(
    () =>
      selectedProgram
        ? programs.filter(
            (program) => program.terms.type === selectedProgram.terms.type,
          )
        : [],
    [programs, selectedProgram],
  );
  const sizes = useMemo(
    () => uniqueValues(typePrograms, (program) => program.terms.account_size),
    [typePrograms],
  );
  const sizePrograms = useMemo(
    () =>
      selectedProgram
        ? typePrograms.filter(
            (program) =>
              program.terms.account_size === selectedProgram.terms.account_size,
          )
        : [],
    [selectedProgram, typePrograms],
  );

  if (!selectedProgram) return catalogPrograms.some((program) => isProgramComingSoon(program.terms)) ? <ComingSoonProgram /> : null;

  const chooseType = (type) => {
    const next = programs.find((program) => program.terms.type === type);
    if (next) setSelectedId(next.id);
  };
  const chooseSize = (size) => {
    const next = typePrograms.find(
      (program) => program.terms.account_size === size,
    );
    if (next) setSelectedId(next.id);
  };

  return (
    <section
      className="mep-panel rounded-2xl border p-5 shadow-[0_0_0_1px_rgba(34,211,238,0.05),0_20px_50px_rgba(2,6,23,0.35)] sm:p-7"
      aria-labelledby={headingId}
      data-program-selector="true"
    >
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
            Current catalog
          </p>
          <h2 id={headingId} className="mep-heading mt-2 text-2xl font-semibold">
            Choose a program
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-400">
            Select a type and account size, then review the published rules for
            the exact program.
          </p>
        </div>
        <p className="text-xs tabular-nums text-slate-500">
          {programs.length} published {programs.length === 1 ? "program" : "programs"}
        </p>
      </div>

      <div className="program-selector-layout mt-7">
      <div className="space-y-6">
        <div>
          <p className="mb-3 text-sm font-medium text-slate-200">Program type</p>
          <div
            className="flex flex-wrap gap-2"
            role="group"
            aria-label="Program chooser: choose program type"
          >
            {types.map((type) => (
              <button
                type="button"
                key={type}
                aria-pressed={selectedProgram.terms.type === type}
                onClick={() => chooseType(type)}
                className={`rounded-xl border px-4 py-2.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0c1729] ${
                  selectedProgram.terms.type === type
                    ? "border-cyan-300 bg-cyan-400/15 text-cyan-100"
                    : "border-slate-700 bg-slate-950/35 text-slate-200 hover:border-cyan-400/70 hover:text-cyan-100"
                }`}
              >
                {typeLabel(type)}
              </button>
            ))}
            <Link to="/trading-rules#instant-funding-rules" className="inline-flex min-h-11 items-center rounded-xl border border-slate-700 px-4 py-2.5 text-sm text-slate-400 underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300">Instant Funding — Coming soon</Link>
          </div>
        </div>

        <div>
          <p className="mb-3 text-sm font-medium text-slate-200">Account size</p>
          <div
            className="flex flex-wrap gap-2"
            role="group"
            aria-label="Program chooser: choose account size"
          >
            {sizes.map((size) => (
              <button
                type="button"
                key={size}
                aria-pressed={selectedProgram.terms.account_size === size}
                onClick={() => chooseSize(size)}
                className={`rounded-xl border px-4 py-2.5 text-sm font-medium tabular-nums transition-colors duration-150 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0c1729] ${
                  selectedProgram.terms.account_size === size
                    ? "border-cyan-300 bg-cyan-400/15 text-cyan-100"
                    : "border-slate-700 bg-slate-950/35 text-slate-200 hover:border-cyan-400/70 hover:text-cyan-100"
                }`}
              >
                {formatCatalogMoney(size)}
              </button>
            ))}
          </div>
        </div>

        {sizePrograms.length > 1 && (
          <div>
            <p className="mb-3 text-sm font-medium text-slate-200">
              Available programs for this selection
            </p>
            <div
              className="flex flex-wrap gap-2"
              role="group"
              aria-label="Program chooser: choose matching program"
            >
              {sizePrograms.map((program) => (
                <button
                  type="button"
                  key={program.id}
                  aria-pressed={selectedProgram.id === program.id}
                  onClick={() => setSelectedId(program.id)}
                  className={`rounded-xl border px-4 py-2.5 text-left text-sm font-medium transition-colors duration-150 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0c1729] ${
                    selectedProgram.id === program.id
                      ? "border-cyan-300 bg-cyan-400/15 text-cyan-100"
                      : "border-slate-700 bg-slate-950/35 text-slate-200 hover:border-cyan-400/70 hover:text-cyan-100"
                  }`}
                >
                  {program.terms.name}
                  <span className="ml-2 text-xs tabular-nums text-slate-400">
                    {" "}#{program.id}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <p className="sr-only" aria-live="polite" aria-atomic="true">
        Selected {selectedProgram.terms.name}, {typeLabel(selectedProgram.terms.type)}, {formatCatalogMoney(selectedProgram.terms.account_size)}.
      </p>

      <article
        key={`${selectedProgram.tenantId}:${selectedProgram.id}`}
        className="mep-panel program-selector-card rounded-xl border p-5 shadow-[0_0_24px_rgba(34,211,238,0.08)] transition-colors duration-150 motion-reduce:transition-none sm:p-6"
        aria-label={`Selected program: ${selectedProgram.terms.name}`}
        data-selected-program-id={selectedProgram.id}
      >
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
              {typeLabel(selectedProgram.terms.type)}
            </p>
            <h3 className="mt-2 text-xl font-semibold text-slate-100">
              {selectedProgram.terms.name}
            </h3>
            <p className="mt-2 text-sm text-slate-400">Published catalog base fee</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums text-cyan-200">
              {formatCatalogMoney(selectedProgram.price)}
            </p>
          </div>
          <Link to={`/programs/${selectedProgram.id}`} className={primaryAction}>
            Review selected program
          </Link>
        </div>
        <div className="mt-5 border-t border-slate-700/70 pt-2">
          <ProgramRules terms={selectedProgram.terms} />
        </div>
      </article>
      </div>
    </section>
  );
}
