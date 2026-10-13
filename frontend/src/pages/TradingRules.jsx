import React from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/layout/Layout';
import { ArrowRight, BookOpen, ShieldCheck } from 'lucide-react';
import { STANDARD_EVALUATION_POLICY as policy } from '../services/standardEvaluationPolicy.js';
import { PROGRAM_RULE_FAMILIES } from '../services/programRuleFamilies.js';
import useProgramCatalog from '../hooks/useProgramCatalog';
import ProgramRuleFamily from '../components/programs/ProgramRuleFamily';
import { CatalogState } from '../components/programs/CatalogUI';

const percent = (value) => `${value.replace('.00', '')}%`;
const action = 'mep-primary inline-flex min-h-11 items-center gap-2 px-5 py-2.5 font-semibold transition-colors motion-reduce:transition-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300';

export default function TradingRules() {
  const catalog = useProgramCatalog();
  const programs = catalog.loading || catalog.error ? [] : (catalog.data ?? []);
  return (
    <Layout>
      <div className="mep-screen min-h-screen text-white">
        <section className="relative overflow-hidden border-b border-cyan-400/15 bg-gradient-to-br from-slate-950 via-blue-950/50 to-slate-900">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(34,211,238,0.12),transparent_55%)]" />
          <div className="relative mx-auto max-w-5xl px-5 py-16 sm:px-8 sm:py-24">
            <p className="mb-4 text-sm font-semibold uppercase tracking-[0.18em] text-cyan-300">Trading information</p>
            <h1 className="mep-heading max-w-3xl text-4xl font-bold tracking-tight sm:text-5xl">Trading rules and program terms</h1>
            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-slate-300">
              Four program families, four rule categories. Select your program to review its own recorded terms, then read the separate approved one-phase update below.
            </p>
          </div>
        </section>

        <section className="mx-auto max-w-5xl space-y-7 px-5 py-12 sm:px-8 sm:py-16" aria-labelledby="program-settings-heading">
          <nav aria-label="Program rule categories" className="flex flex-wrap gap-3">
            {PROGRAM_RULE_FAMILIES.map((family) => <Link key={family.type} to={`#${family.anchor}`} className="inline-flex min-h-11 items-center rounded-xl border border-cyan-400/30 bg-slate-950/60 px-4 py-3 text-sm font-semibold text-cyan-100 hover:border-cyan-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300">{family.title}</Link>)}
          </nav>
          <p className="text-sm leading-relaxed text-slate-400">These categories read the same current catalog as program details. Recorded settings do not confirm live enforcement, payout eligibility or funding. Existing orders retain their recorded terms.</p>
          {(catalog.loading || catalog.error) && <CatalogState loading={catalog.loading} error={catalog.error} retry={catalog.retry} />}
          {PROGRAM_RULE_FAMILIES.map((family) => <ProgramRuleFamily key={family.type} family={family} programs={programs} unavailable={Boolean(catalog.loading || catalog.error)} />)}

          <div className="mep-panel rounded-2xl border p-6 sm:p-9">
            <div className="flex items-start gap-4">
              <ShieldCheck className="mt-1 h-6 w-6 shrink-0 text-cyan-300" aria-hidden="true" />
              <div className="min-w-0">
                <h2 id="program-settings-heading" className="mep-heading text-2xl font-semibold">Approved standard evaluation model</h2>
                <p className="mt-3 leading-relaxed text-slate-300">
                  A single-stage evaluation. The figures and loss definitions below describe only the approved one-phase update, not an automatic change to every program or existing order. They do not define the two-phase, three-phase or Instant Funding categories.
                </p>
                <dl data-standard-model className="mt-6 grid gap-3 sm:grid-cols-2">
                  {[
                    ['Evaluation stages', String(policy.phases)],
                    ['Profit target', percent(policy.profit_target)],
                    ['Maximum daily loss', percent(policy.max_daily_loss)],
                    ['Maximum total loss — fixed', percent(policy.max_total_loss)],
                    ['Trader share of eligible profit', percent(policy.profit_split)],
                    ['Operator share of eligible profit', percent(policy.operator_share)],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-xl border border-slate-700 bg-slate-950/40 p-4">
                      <dt className="text-sm text-slate-400">{label}</dt>
                      <dd className="mt-2 text-2xl font-semibold tabular-nums text-cyan-200">{value}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-5 break-words text-xs text-slate-400">Model version: {policy.version}</p>
              </div>
            </div>
          </div>

          <aside className="rounded-2xl border border-amber-400/30 bg-amber-400/5 p-6" aria-labelledby="rollout-heading">
            <h2 id="rollout-heading" className="mep-heading text-xl font-semibold text-amber-200">Catalog rollout pending</h2>
            <p className="mt-3 leading-relaxed text-slate-300">
              Program-specific settings are displayed in the catalog and on each program details page. This model applies only when explicitly assigned to that program. Current listings may have different terms; their values are not replaced by this page. All four families remain separate; new stage-specific targets and any revised family limits need explicit approval.
            </p>
            <p className="mt-3 leading-relaxed text-slate-300">
              An existing order keeps the terms recorded with it. This page does not rewrite past orders, confirm a funded account or enable live trading or payouts.
            </p>
            <Link to="/programs" className={`${action} mt-5`}>Browse programs <ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
          </aside>

          <section className="mep-panel rounded-2xl border p-6 sm:p-9" aria-labelledby="daily-loss-heading">
            <h2 id="daily-loss-heading" className="mep-heading text-2xl font-semibold">Daily loss: one budget for the entire day</h2>
            <p className="mt-4 leading-relaxed text-slate-300">
              The daily loss budget is {percent(policy.max_daily_loss)} of the initial account size. It is not a separate allowance for each trade and does not increase when the account grows.
            </p>
            <p className="mt-4 rounded-xl border border-cyan-400/20 bg-cyan-400/5 p-4 font-medium text-cyan-100">
              Daily threshold = closed balance at the start of the trading day − daily loss budget.
            </p>
            <p className="mt-4 leading-relaxed text-slate-300">
              Equity means the account value including open profit or loss and trading costs already reflected by the trading source. Do not subtract the same commission or swap twice. Under this model, reaching or falling below the daily threshold is a breach, even if the account later recovers.
            </p>
            <p className="mt-4 leading-relaxed text-slate-300">
              Illustration only: an initial account size of USD 100,000 gives a USD 5,000 daily budget. If the day starts at USD 100,000, the threshold is USD 95,000. If it starts at USD 102,000, the threshold is USD 97,000.
            </p>
            <p className="mt-4 text-sm leading-relaxed text-amber-200">
              The daily reset time and timezone still require confirmation before live enforcement. No live account calculation is performed by this page.
            </p>
          </section>

          <section className="mep-panel rounded-2xl border p-6 sm:p-9" aria-labelledby="total-loss-heading">
            <h2 id="total-loss-heading" className="mep-heading text-2xl font-semibold">Total loss: a fixed limit</h2>
            <p className="mt-4 leading-relaxed text-slate-300">
              The total loss limit is {percent(policy.max_total_loss)} of the initial account size. The threshold stays at 90% of that initial size; it does not trail account peaks and does not reset each day. Reaching or falling below it is a breach. Both daily and total limits must be respected.
            </p>
            <p className="mt-4 leading-relaxed text-slate-300">
              Illustration only: for an initial USD 100,000 account, the fixed total threshold is USD 90,000. The effect of a withdrawal on the account and its remaining buffer must be defined separately before payouts are enabled.
            </p>
          </section>

          <section className="mep-panel rounded-2xl border p-6 sm:p-9" aria-labelledby="passing-heading">
            <h2 id="passing-heading" className="mep-heading text-2xl font-semibold">Passing the evaluation</h2>
            <p className="mt-4 leading-relaxed text-slate-300">
              The standard target is {percent(policy.profit_target)} closed profit after trading costs, measured against the initial account size. Positions must be closed and the applicable rules must have been respected throughout the evaluation. Reaching the profit target does not erase an earlier breach.
            </p>
            <p className="mt-4 leading-relaxed text-slate-300">
              Minimum trading days, maximum evaluation duration, inactivity rules and the account provided after passing still require confirmation. A displayed target or a recorded purchase is not proof that a live trading account has been issued.
            </p>
          </section>

          <section className="mep-panel rounded-2xl border p-6 sm:p-9" aria-labelledby="profit-share-heading">
            <h2 id="profit-share-heading" className="mep-heading scroll-mt-24 text-2xl font-semibold">Profit sharing is not ownership of capital</h2>
            <p className="mt-4 leading-relaxed text-slate-300">
              The standard split is {percent(policy.profit_split)} to the trader and {percent(policy.operator_share)} to the operator from eligible profit after the evaluation. It is not a guaranteed return, a share of the account capital or an automatic payout of evaluation profits. The operator share is separate from the evaluation profit target.
            </p>
            <p className="mt-4 leading-relaxed text-slate-300">
              Illustration only: USD 1,000 of eligible profit would split into USD 900 for the trader and USD 100 for the operator. The eligible-profit definition, loss offsets, previously distributed profit, withdrawal timing, fees, currency and network still need an explicit policy. This illustration does not establish payout eligibility.
            </p>
          </section>

          <aside className="mep-panel rounded-2xl border p-6" aria-labelledby="availability-heading">
            <div className="flex items-center gap-3"><BookOpen className="h-5 w-5 text-cyan-300" aria-hidden="true" /><h2 id="availability-heading" className="mep-heading text-lg font-semibold">What is still not defined</h2></div>
            <p className="mt-3 leading-relaxed text-slate-300">
              Operator identity and jurisdiction, the funded-account model, refund terms, strategy permissions and the process for reviewing a disputed breach are not established by this page. No company, licence, payment schedule or provider capability is inferred from the MarketEdgePros brand name.
            </p>
            <div className="mt-5 flex flex-wrap gap-4">
              <Link to="/terms-of-service" className="rounded font-semibold text-cyan-200 underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300">Terms status</Link>
              <Link to="/contact" className="rounded font-semibold text-cyan-200 underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300">Contact options</Link>
            </div>
          </aside>
        </section>
      </div>
    </Layout>
  );
}
