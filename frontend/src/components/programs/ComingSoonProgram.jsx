import React from 'react';
import { Link } from 'react-router-dom';
import { Clock3, ArrowRight } from 'lucide-react';

export default function ComingSoonProgram({ showTitle = true }) {
  return (
    <section className="mep-panel min-w-0 rounded-2xl border border-cyan-400/20 p-6 sm:p-8" data-coming-soon="instant_funding" aria-label="Instant Funding availability">
      <div className="flex flex-wrap items-center gap-3">
        <Clock3 className="h-5 w-5 text-cyan-300" aria-hidden="true" />
        <p role="status" className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1 text-sm font-semibold text-cyan-100">Coming soon</p>
      </div>
      {showTitle && <h2 className="mep-heading mt-5 text-2xl font-semibold">Instant Funding</h2>}
      <p className="mt-4 max-w-2xl text-sm leading-relaxed text-slate-300">Instant Funding is not available for purchase, quote requests or new payments. No launch date, funding or account delivery is promised.</p>
      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400">Explore the evaluation programs and review their recorded rules. A listed program does not itself enable payment, trading or payouts.</p>
      <Link to="/programs?filter=all" className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg text-sm font-semibold text-cyan-200 underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300">Explore evaluation programs <ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
    </section>
  );
}
