import { Link } from 'react-router-dom';
import {
  ArrowLeft, ArrowRight, CircleAlert, ClipboardCheck, DollarSign,
  Fingerprint, LifeBuoy, LockKeyhole, ReceiptText, ShieldCheck,
} from 'lucide-react';

const accountLink = 'inline-flex items-center gap-2 rounded-lg text-sm font-semibold text-cyan-300 transition-colors hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-4 focus-visible:ring-offset-slate-950 motion-reduce:transition-none';
const cardLink = 'group rounded-xl border p-4 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-4 focus-visible:ring-offset-slate-950 motion-reduce:transition-none';

// Conceptual examples only; no live payout state machine or approved customer policy.
const requirements = [
  { title: 'Referral records', icon: Fingerprint, text: 'A future service may need to associate a referral with the relevant account and order. No referral or identity review is performed on this page.' },
  { title: 'Payment records', icon: ReceiptText, text: 'A future service may need verified payment information and approved commission terms. A referral record alone does not establish an amount payable.' },
  { title: 'Review status', icon: ShieldCheck, text: 'Any future eligibility checks would depend on business terms approved for the program. No eligibility decision is made here.' },
  { title: 'Transfer handling', icon: ClipboardCheck, text: 'A future payout service would need an approved transfer process and reliable outcome handling. No payout is requested or sent here.' },
];

export default function AffiliatePayout() {
  return (
    <div className="mep-screen min-h-screen text-white">
      <section className="border-b border-cyan-400/10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-cyan-500/10 via-slate-950 to-slate-950">
        <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
          <Link to="/affiliate/dashboard" className={accountLink}>
            <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            Back to affiliate dashboard
          </Link>
          <div className="mt-8 flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">Affiliate account</p>
              <h1 className="mep-heading mt-3 text-3xl font-bold tracking-tight sm:text-4xl">Payout status</h1>
              <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-300 sm:text-base">
                Payout execution is unavailable. This page explains the current limitation and outlines possible future checks.
              </p>
            </div>
            <span className="inline-flex w-fit shrink-0 items-center gap-2 rounded-full border border-amber-300/25 bg-amber-300/5 px-3 py-2 text-xs font-semibold text-amber-200">
              <LockKeyhole aria-hidden="true" className="h-3.5 w-3.5" />
              Execution unavailable
            </span>
          </div>
        </div>
      </section>

      <main className="mx-auto max-w-5xl space-y-6 px-4 py-8 sm:px-6 lg:px-8">
        <section aria-labelledby="payout-availability" className="rounded-2xl border border-amber-300/25 bg-amber-400/10 p-5 sm:p-6">
          <div className="flex items-start gap-3 sm:gap-4">
            <div className="shrink-0 rounded-xl bg-amber-300/15 p-2.5 text-amber-200 sm:p-3">
              <CircleAlert aria-hidden="true" className="h-5 w-5 sm:h-6 sm:w-6" />
            </div>
            <div className="min-w-0">
              <h2 id="payout-availability" className="mep-heading text-lg font-semibold text-amber-100 sm:text-xl">Payout execution is unavailable</h2>
              <p className="mt-2 text-sm leading-6 text-amber-50/80">
                This page does not submit payouts, collect payout methods, or verify withdrawal eligibility. It does not show a verified withdrawable balance or payout history.
              </p>
              <p className="mt-3 text-sm leading-6 text-amber-50/80">
                Technical preconditions for a possible future payout service are not approved business or legal policy. No payout request can be made here.
              </p>
            </div>
          </div>
        </section>

        <section aria-labelledby="payout-requirements" className="mep-panel overflow-hidden rounded-2xl border">
          <div className="border-b border-white/10 p-5 sm:p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Conceptual outline</p>
            <h2 id="payout-requirements" className="mep-heading mt-2 text-xl font-semibold">Possible checks before a future payout service</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              These examples describe technical topics a future service might need to address. They are not approved program terms, binding eligibility requirements, account status, or a promise of payment.
            </p>
          </div>
          <ol className="grid gap-px bg-white/5 sm:grid-cols-2" aria-label="Conceptual checks for a possible future payout service">
            {requirements.map(({ title, icon: Icon, text }, index) => (
              <li key={title} className="bg-slate-900 p-5 sm:p-6">
                <div className="flex items-center justify-between gap-4">
                  <Icon aria-hidden="true" className="h-5 w-5 text-cyan-300" />
                  <span aria-hidden="true" className="font-mono text-sm tabular-nums text-slate-500">0{index + 1}</span>
                </div>
                <h3 className="mt-4 font-semibold text-slate-100">{title}</h3>
                <p className="mt-2 text-sm leading-6 text-slate-400">{text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="commission-records" className="mep-panel rounded-2xl border p-5 sm:p-6">
          <h2 id="commission-records" className="mep-heading text-xl font-semibold">Affiliate account links</h2>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Open the commissions page to review the information available there. A displayed commission record is not confirmation that an amount is approved, payable, or withdrawable.
          </p>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <Link to="/affiliate/commissions" className={`${cardLink} border-cyan-300/20 bg-cyan-300/5 hover:border-cyan-300/45 hover:bg-cyan-300/10`}>
              <DollarSign aria-hidden="true" className="h-5 w-5 text-cyan-300" />
              <h3 className="mt-3 font-semibold">Commissions</h3>
              <p className="mt-1 text-sm text-slate-400">Open the commissions page.</p>
              <span className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-cyan-200">Open commissions <ArrowRight aria-hidden="true" className="h-4 w-4" /></span>
            </Link>
            <Link to="/support/create-ticket" className={`${cardLink} border-white/10 bg-slate-950/45 hover:border-cyan-300/35`}>
              <LifeBuoy aria-hidden="true" className="h-5 w-5 text-cyan-300" />
              <h3 className="mt-3 font-semibold">Contact support</h3>
              <p className="mt-1 text-sm text-slate-400">Ask about your affiliate account or the payout status shown here.</p>
              <span className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-cyan-200">Create a ticket <ArrowRight aria-hidden="true" className="h-4 w-4" /></span>
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}
