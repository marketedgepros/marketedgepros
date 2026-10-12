import React from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  AlertCircle,
  FileText,
  ShieldCheck,
} from "lucide-react";
import Layout from "../layout/Layout";
import {
  formatCatalogMoney,
  formatCatalogPercent,
  typeLabel,
} from "../../services/programCatalogViewService";

export const primaryAction =
  "inline-flex items-center justify-center gap-2 rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950 hover:bg-cyan-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 transition-colors duration-150 motion-reduce:transition-none disabled:opacity-50 disabled:cursor-not-allowed";
export const secondaryAction =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-slate-600 px-4 py-3 text-sm font-medium text-slate-200 hover:border-cyan-400 hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 transition-colors duration-150 motion-reduce:transition-none";
export const panelStyle =
  "rounded-2xl border border-slate-700/70 bg-slate-900/80 p-5 sm:p-7 min-w-0";

export function CatalogPage({ children }) {
  return (
    <Layout>
      <div className="min-h-screen bg-[#0b1220] text-slate-100">
        <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 sm:py-16 lg:px-8">
          {children}
        </div>
      </div>
    </Layout>
  );
}
export function BackToPrograms() {
  return (
    <Link
      to="/programs"
      className="mb-7 inline-flex items-center gap-2 text-sm text-slate-300 hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 rounded"
    >
      <ArrowLeft size={16} aria-hidden="true" />
      All programs
    </Link>
  );
}
export function CatalogState({ loading, error, retry, empty = false }) {
  return (
    <section
      className={`${panelStyle} py-12 text-center`}
      aria-live="polite"
      aria-busy={loading || undefined}
    >
      {loading ? (
        <>
          <FileText className="mx-auto mb-4 text-cyan-400" aria-hidden="true" />
          <h2 className="text-xl font-semibold">Loading current catalog…</h2>
          <p className="mt-2 text-slate-400">
            Prices and terms are requested from the server.
          </p>
        </>
      ) : (
        <>
          <AlertCircle
            className="mx-auto mb-4 text-cyan-400"
            aria-hidden="true"
          />
          <h2 className="text-xl font-semibold">
            {empty ? "No active programs available" : "Catalog unavailable"}
          </h2>
          <p
            className="mx-auto mt-3 max-w-xl text-slate-300"
            role={error ? "alert" : undefined}
          >
            {error ||
              "There are no active programs in the current brand catalog. Contact support for availability."}
          </p>
          {!empty && (
            <button
              type="button"
              onClick={retry}
              className={`${secondaryAction} mt-6`}
            >
              Try again
            </button>
          )}
          <Link
            to="/support/create-ticket"
            className={`${secondaryAction} mt-6 ml-2`}
          >
            Contact support
          </Link>
        </>
      )}
    </section>
  );
}
export function ProgramRules({ terms }) {
  const values = [
    ["Account size", formatCatalogMoney(terms.account_size)],
    ["Profit target", formatCatalogPercent(terms.profit_target)],
    ["Maximum daily loss", formatCatalogPercent(terms.max_daily_loss)],
    ["Maximum total loss", formatCatalogPercent(terms.max_total_loss)],
    ["Profit split", formatCatalogPercent(terms.profit_split)],
  ];
  return (
    <dl className="divide-y divide-slate-700/60">
      {values.map(([label, value]) => (
        <div
          key={label}
          className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-3"
        >
          <dt className="text-sm text-slate-400">{label}</dt>
          <dd className="font-medium tabular-nums text-slate-100">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
export function PaymentBoundary() {
  return (
    <aside
      className="rounded-xl border border-cyan-400/20 bg-cyan-400/5 p-4 text-sm text-slate-300"
      aria-label="Payment availability"
    >
      <div className="flex gap-3">
        <ShieldCheck
          className="mt-0.5 shrink-0 text-cyan-300"
          size={20}
          aria-hidden="true"
        />
        <div>
          <p className="font-semibold text-cyan-100">
            Quotes only. Payments are not enabled.
          </p>
          <p className="mt-2 leading-relaxed">
            A quote does not charge you, activate a trading account or provide
            funding. Payment and trading connections need separate verification
            before they can be offered.
          </p>
        </div>
      </div>
    </aside>
  );
}
export function CatalogCard({ program }) {
  return (
    <article
      className={`${panelStyle} flex flex-col hover:border-cyan-400/40 transition-colors motion-reduce:transition-none`}
    >
      <span className="break-words [overflow-wrap:anywhere] text-xs uppercase tracking-widest text-cyan-300">
        {typeLabel(program.terms.type)}
      </span>
      <h2 className="mt-4 break-words text-xl font-semibold">
        {program.terms.name}
      </h2>
      <p className="mt-2 text-sm text-slate-400">Program account size</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">
        {formatCatalogMoney(program.terms.account_size)}
      </p>
      <div className="my-6 border-l-2 border-cyan-400 pl-4">
        <p className="text-xs uppercase tracking-wider text-slate-400">
          Catalog base fee
        </p>
        <p className="mt-1 text-3xl font-bold tabular-nums text-cyan-200">
          {formatCatalogMoney(program.price)}
        </p>
        <p className="mt-2 text-xs text-slate-400">
          Optional add-ons are quoted separately.
        </p>
      </div>
      <ProgramRules terms={program.terms} />
      <Link to={`/programs/${program.id}`} className={`${primaryAction} mt-6`}>
        View rules & options
        <ArrowRight size={17} aria-hidden="true" />
      </Link>
    </article>
  );
}
export function ConfiguredRules({ terms }) {
  const entries = Object.entries(terms.rules);
  return (
    <section className={panelStyle} aria-labelledby="additional-rules">
      <h2 id="additional-rules" className="text-xl font-semibold">
        Additional catalog rules
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-slate-400">
        Stored settings, not confirmation of live enforcement or eligibility.
        Missing details must be clarified before payment.
      </p>
      {entries.length ? (
        <dl className="mt-5 space-y-4">
          {entries.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="break-words [overflow-wrap:anywhere] text-sm font-medium text-cyan-200">
                {key.replaceAll("_", " ")}
              </dt>
              <dd className="mt-1 whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-sm text-slate-300">
                {value === null
                  ? "Not specified"
                  : typeof value === "object"
                    ? JSON.stringify(value, null, 2)
                    : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-5 text-sm text-slate-300">
          No additional rules have been published in this catalog entry.
        </p>
      )}
      <p className="mt-5 border-t border-slate-700 pt-4 text-xs text-slate-400">
        These settings do not establish a refund, payout timetable, drawdown
        method or provider guarantee.
      </p>
    </section>
  );
}
