import React from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/layout/Layout';
import { FileText, AlertCircle } from 'lucide-react';
import { APPROVED_ACCOUNT_MODEL, approvedEvaluationPolicy } from '../services/programEvaluationPolicy.js';

const policy = approvedEvaluationPolicy('one_phase');
const targets = (type) => approvedEvaluationPolicy(type).phase_targets.map((value) => `${value.replace('.00', '')}%`).join(' / ');

export default function TermsOfService() {
  if (!policy) return (
    <Layout><section className="mep-screen min-h-screen px-5 py-16 text-white"><div className="mx-auto max-w-5xl">
      <h1 className="mep-heading text-4xl font-bold">Terms of Service</h1>
      <p role="alert" className="mt-6 leading-relaxed text-amber-100">The approved evaluation policy is unavailable. No substitute program terms or completed contractual agreement are represented.</p>
      <Link to="/programs" className="mep-primary mt-6 inline-flex min-h-11 items-center px-5 py-3 font-semibold">Review current program information</Link>
    </div></section></Layout>
  );
  const sections = [
    {
      title: 'Operator information',
      content: 'MarketEdgePros is the brand name. No registered company, company number, licence or legal department is represented by this page. The responsible operator, operating jurisdiction and contact details for the contractual provider still need to be supplied.',
    },
    {
      title: 'Evaluation and account access',
      content: `The evaluation catalog has one-phase, two-phase and three-phase families with their own recorded stage targets. ${APPROVED_ACCOUNT_MODEL.description} Instant Funding is Coming soon and is not available for purchase, quote requests or new payments. No launch date, immediate funding or trading access is promised. Payment for an evaluation is not a deposit into an investment account and does not transfer ownership of the stated account capital. Account-delivery conditions and timing still require confirmation. Trading access is not activated by this page.`,
    },
    {
      title: 'Which program terms apply',
      content: `Read the selected program’s recorded policy in its rule category. The approved targets are ${targets('one_phase')} for one-phase, ${targets('two_phase')} for two-phase and ${targets('three_phase')} for three-phase. They require a full explicit versioned snapshot in the specific program; matching percentages alone do not assign a policy. The policies use a ${policy.max_daily_loss.replace('.00', '')}% maximum daily loss based on initial account size and a ${policy.max_total_loss.replace('.00', '')}% fixed maximum total loss. Targets require closed positions after trading costs and no breach. A new stage starts at initial account size without profit or loss carryover. Existing orders and historical challenges retain their previous recorded terms; they are not rewritten.`,
    },
    {
      title: 'Eligible profit and distributions',
      content: `A program with the approved versioned evaluation policy allocates ${policy.profit_split.replace('.00', '')}% of eligible profit to the trader and ${policy.operator_share.replace('.00', '')}% to the operator. An old order keeps its originally recorded split. These figures do not promise a return, distribution of evaluation profits or withdrawal of account capital. Eligible-profit calculation, payout eligibility, timing, minimums and any withdrawal fees or methods still need a complete approved policy. Payouts are not enabled by this page.`,
    },
    {
      title: 'Fees, refunds and changes',
      content: 'Catalog prices and a server-recorded quote are separate from a verified payment. No automatic refund exclusion, unilateral change to an existing order or waiver of legal rights is established here. The applicable cancellation and refund terms require an approved policy before they can be presented as contractual terms.',
    },
    {
      title: 'Remaining contractual details',
      content: 'Operator identification, governing law, eligibility, privacy, strategy permissions, breach review and account closure procedures still need a complete, applicable agreement. The standard evaluation figures alone do not supply that agreement.',
    },
  ];

  return (
    <Layout>
      <div className="mep-screen min-h-screen text-white">
        <section className="relative overflow-hidden border-b border-cyan-400/15 bg-gradient-to-br from-slate-950 via-blue-950/50 to-slate-900 px-5 py-16 sm:px-8 sm:py-24">
          <div className="mx-auto max-w-5xl">
            <FileText className="mb-6 h-10 w-10 text-cyan-300" aria-hidden="true" />
            <h1 className="mep-heading text-4xl font-bold tracking-tight sm:text-5xl">Terms of Service</h1>
            <p className="mt-5 max-w-3xl text-lg leading-relaxed text-slate-300">Approved evaluation information and the contractual details that still need to be completed.</p>
          </div>
        </section>
        <section className="mx-auto max-w-5xl space-y-6 px-5 py-12 sm:px-8 sm:py-16" aria-labelledby="terms-status-heading">
          <aside className="rounded-2xl border border-amber-400/30 bg-amber-400/5 p-6 sm:p-8">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-1 h-6 w-6 shrink-0 text-amber-300" aria-hidden="true" />
              <div>
                <h2 id="terms-status-heading" className="mep-heading text-xl font-semibold text-amber-200">Contractual policy is not complete</h2>
                <p className="mt-3 leading-relaxed text-slate-300">This page is not a completed contractual agreement. The standard evaluation model is owner-approved, but unresolved provider and policy information must not be treated as confirmed. It does not enable payment, trading, funding or payouts.</p>
              </div>
            </div>
          </aside>
          {sections.map(({ title, content }) => (
            <section key={title} className="mep-panel rounded-2xl border p-6 sm:p-8">
              <h2 className="mep-heading text-2xl font-semibold">{title}</h2>
              <p className="mt-4 leading-relaxed text-slate-300" data-account-model={title === 'Evaluation and account access' ? APPROVED_ACCOUNT_MODEL.version : undefined}>{content}</p>
            </section>
          ))}
          <div className="mep-panel rounded-2xl border p-6 sm:p-8">
            <h2 className="mep-heading text-xl font-semibold">Review the available information</h2>
            <div className="mt-5 flex flex-wrap gap-4">
              <Link to="/trading-rules" className="mep-primary inline-flex min-h-11 items-center px-5 py-3 font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300">Read evaluation rules</Link>
              <Link to="/contact" className="inline-flex min-h-11 items-center rounded-xl border border-slate-600 px-5 py-3 font-semibold text-cyan-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300">View contact options</Link>
            </div>
          </div>
        </section>
      </div>
    </Layout>
  );
}
