import { Link } from 'react-router-dom';
import { ArrowLeft, ArrowRight, CircleAlert, ClipboardCheck, DollarSign, LifeBuoy } from 'lucide-react';

export default function AffiliatePayout() {
  return (
    <div className="min-h-screen bg-slate-950 text-white">
      <section className="border-b border-cyan-400/10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-cyan-500/10 via-slate-950 to-slate-950">
        <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6 lg:px-8">
          <Link to="/affiliate/dashboard" className="inline-flex items-center gap-2 text-sm font-semibold text-cyan-300 hover:text-cyan-200">
            <ArrowLeft className="h-4 w-4" />
            Back to affiliate dashboard
          </Link>
          <p className="mt-7 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">Affiliate account</p>
          <h1 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">Payout status</h1>
          <p className="mt-3 max-w-2xl text-slate-300">
            Review what is available in the affiliate account experience without submitting payment details or a payout request.
          </p>
        </div>
      </section>

      <main className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
        <section className="rounded-2xl border border-amber-300/25 bg-amber-400/10 p-5 shadow-xl shadow-amber-950/10 sm:p-6">
          <div className="flex gap-4">
            <div className="shrink-0 rounded-xl bg-amber-300/15 p-3 text-amber-200">
              <CircleAlert className="h-6 w-6" />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-amber-100">Payout execution is not enabled</h2>
              <p className="mt-2 text-sm leading-6 text-amber-50/80">
                This account page does not submit payouts, collect payout methods, or verify withdrawal eligibility. No withdrawable balance or payout history is shown because the current view contract does not provide verified payout data.
              </p>
            </div>
          </div>
        </section>

        <section className="mt-6 rounded-2xl border border-white/10 bg-slate-900/70 p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <ClipboardCheck className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" />
            <div>
              <h2 className="font-semibold">What you can review</h2>
              <p className="mt-1 text-sm leading-6 text-slate-400">
                Recorded commission categories can be reviewed on the commissions page. Those records are not a confirmation that an amount is approved, payable, or withdrawable.
              </p>
            </div>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <Link to="/affiliate/commissions" className="group rounded-xl border border-cyan-300/20 bg-cyan-300/5 p-4 transition hover:border-cyan-300/45 hover:bg-cyan-300/10">
              <DollarSign className="h-5 w-5 text-cyan-300" />
              <p className="mt-3 font-semibold">Review commissions</p>
              <p className="mt-1 text-sm text-slate-400">See current commission records.</p>
              <span className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-cyan-200">Open commissions <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" /></span>
            </Link>
            <Link to="/support/create-ticket" className="group rounded-xl border border-white/10 bg-slate-950/45 p-4 transition hover:border-cyan-300/35">
              <LifeBuoy className="h-5 w-5 text-cyan-300" />
              <p className="mt-3 font-semibold">Contact support</p>
              <p className="mt-1 text-sm text-slate-400">Ask about your affiliate account or payout process.</p>
              <span className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-cyan-200">Create a ticket <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" /></span>
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}
