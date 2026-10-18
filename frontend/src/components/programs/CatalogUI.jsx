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
import ComingSoonProgram from "./ComingSoonProgram";
import { evaluationPolicyForTerms, isProgramComingSoon } from "../../services/programEvaluationPolicy.js";
import {
  formatCatalogMoney,
  formatCatalogPercent,
  typeLabel,
} from "../../services/programCatalogViewService";

export const primaryAction =
  "mep-primary inline-flex items-center justify-center gap-2 px-5 py-3 font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 transition-colors duration-150 motion-reduce:transition-none disabled:opacity-50 disabled:cursor-not-allowed";
export const secondaryAction =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-slate-600 px-4 py-3 text-sm font-medium text-slate-200 hover:border-cyan-400 hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 transition-colors duration-150 motion-reduce:transition-none";
export const panelStyle =
  "mep-panel rounded-2xl border p-5 sm:p-7 min-w-0";

export function CatalogPage({ children }) {
  return (
    <Layout>
      <div className="mep-screen min-h-screen text-slate-100">
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
          <h2 className="mep-heading text-xl font-semibold">Loading current catalog…</h2>
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
          <h2 className="mep-heading text-xl font-semibold">
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
export function ProgramRules({ terms, historical = false }) {
  if (isProgramComingSoon(terms) && !historical) {
    return <p role="status" className="py-4 text-sm leading-relaxed text-cyan-100">Coming soon. No purchase price, evaluation target or account delivery is currently offered for Instant Funding.</p>;
  }
  const result = evaluationPolicyForTerms(terms);
  if (result.status === "mismatch" || result.status === "unsupported") {
    return <p role="alert" className="py-4 text-sm text-amber-100">Recorded evaluation policy is unavailable. No substitute rules are shown.</p>;
  }
  const policy = result.policy;
  const values = [
    ["Account size", formatCatalogMoney(terms.account_size)],
    ...(policy && policy.phases > 0
      ? policy.phase_targets.map((target, index) => [`Phase ${index + 1} profit target`, formatCatalogPercent(target)])
      : [["Profit target", formatCatalogPercent(terms.profit_target)]]),
    ["Maximum daily loss", formatCatalogPercent(terms.max_daily_loss)],
    ["Maximum total loss", formatCatalogPercent(terms.max_total_loss)],
    ["Profit split", formatCatalogPercent(terms.profit_split)],
    ...(policy ? [["Operator share of eligible profit", formatCatalogPercent(policy.operator_share)]] : []),
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
export function EvaluationPolicyDetails({ terms }) {
  const result = evaluationPolicyForTerms(terms);
  if (isProgramComingSoon(terms)) return null;
  if (result.status === "unassigned") return <p className="mt-4 text-sm leading-relaxed text-amber-100">Policy assignment pending for this entry. Its existing recorded settings remain unchanged; no individual stage targets are inferred.</p>;
  if (result.status !== "matched") return <p role="alert" className="mt-4 text-sm text-amber-100">The recorded evaluation policy cannot be verified. No replacement policy is assumed.</p>;
  const policy = result.policy;
  return (
    <aside className="mt-5 rounded-xl border border-cyan-400/20 bg-cyan-400/5 p-5 text-sm leading-relaxed" data-recorded-evaluation-policy={policy.version}>
      <h3 className="font-semibold text-cyan-100">Recorded evaluation policy</h3>
      <p className="mt-3 text-slate-300">Each stage starts at the selected initial account size. Profit and loss are not carried into the next stage. Passing requires the recorded target after trading costs, all positions closed and no breach.</p>
      <p className="mt-3 text-slate-300">The daily loss budget is {formatCatalogPercent(policy.max_daily_loss)} of the initial account size, measured from the closed balance at the start of the day. Equity at or below that threshold is a breach. The total loss threshold is fixed at 90% of initial account size.</p>
      <p className="mt-3 text-slate-300">The trader share is {formatCatalogPercent(policy.profit_split)} of eligible profit and the operator share is {formatCatalogPercent(policy.operator_share)}. This is not account capital or an entitlement to evaluation profit.</p>
      <p className="mt-3 text-slate-400">Daily reset timezone and time, account delivery/type and payout eligibility and schedule still require confirmation. These rules do not confirm live enforcement, funding, payment or payouts.</p>
      <p className="mt-3 break-words text-xs text-slate-500">Recorded version: {policy.version}</p>
    </aside>
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
            A quote is not a paid purchase.
          </p>
          <p className="mt-2 leading-relaxed">
            A quote does not charge you, activate a trading account or provide
            funding. Payment availability is checked separately for your account.
            An explicitly enabled purchase test does not activate trading,
            payouts or KYC-provider verification.
          </p>
        </div>
      </div>
    </aside>
  );
}
export function CatalogCard({ program }) {
  if (isProgramComingSoon(program.terms)) return <ComingSoonProgram />;
  return (
    <article
      className={`${panelStyle} flex flex-col hover:border-cyan-400/40 transition-colors motion-reduce:transition-none`}
    >
      <span className="break-words [overflow-wrap:anywhere] text-xs uppercase tracking-widest text-cyan-300">
        {typeLabel(program.terms.type)}
      </span>
      <h2 className="mep-heading mt-4 break-words text-xl font-semibold">
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
export function ConfiguredRules({ terms, headingId = 'additional-rules', headingTag = 'h2' }) {
  const entries = Object.entries(terms.rules).filter(([key]) => !["evaluation_policy", "product_availability", "_mep_legacy_challenge_terms"].includes(key));
  const Heading = headingTag;
  return (
    <section className={panelStyle} aria-labelledby={headingId}>
      <Heading id={headingId} className="mep-heading text-xl font-semibold">
        Additional catalog rules
      </Heading>
      <p className="mt-2 text-sm leading-relaxed text-slate-400">
        Stored settings, not confirmation of live enforcement or eligibility.
        Missing details must be clarified before payment.
      </p>
      <EvaluationPolicyDetails terms={terms} />
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
                    : typeof value === "boolean"
                      ? (value ? "Yes" : "No")
                      : key === "drawdown_type" && value === "static"
                        ? "Fixed (static)"
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
        The recorded drawdown type is a catalog setting, not evidence of live
        enforcement. These settings do not establish a refund, payout timetable
        or provider guarantee.
      </p>
    </section>
  );
}
