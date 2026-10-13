import { ArrowRight, ShieldCheck, Zap } from 'lucide-react';
import Layout from '../components/layout/Layout';
import SEO from '../components/SEO';
import CatalogPreview from '../components/programs/CatalogPreview';

export default function LightningChallenge() {
  return (
    <Layout>
      <SEO
        title="Lightning Challenge | MarketEdgePros"
        description="Explore current Lightning program options and published catalog terms. Availability and payment are not verified here."
        keywords="Lightning Challenge, trading program, program catalog"
      />
      <main className="min-h-screen bg-[#0b1220] text-slate-100">
        <section className="relative overflow-hidden border-b border-slate-800 bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950/50 py-24 sm:py-32">
          <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-cyan-400/10 blur-3xl" />
          <div className="relative mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
            <p className="mb-5 inline-flex items-center gap-2 rounded-full border border-cyan-300/25 bg-cyan-300/5 px-4 py-2 text-sm font-medium text-cyan-200">
              <Zap className="h-4 w-4" aria-hidden="true" />
              Lightning program
            </p>
            <h1 className="mep-heading max-w-3xl text-4xl font-semibold tracking-tight text-white sm:text-6xl">
              Explore Lightning program options
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-slate-300">
              Compare the current published catalog entries and review the settings shown for each program. Program terms are supplied by the catalog and may vary by listing.
            </p>
            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <a href="#programs" className="mep-primary inline-flex items-center justify-center gap-2 px-6 py-3 font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 motion-reduce:transition-none">
                Browse listed programs <ArrowRight size={18} aria-hidden="true" />
              </a>
              <a href="#important-information" className="inline-flex items-center justify-center rounded-xl border border-slate-600 px-6 py-3 font-medium text-slate-100 transition-colors hover:border-cyan-300 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 motion-reduce:transition-none">
                Availability and terms
              </a>
            </div>
          </div>
        </section>

        <section id="programs" className="scroll-mt-8 py-16 sm:py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="mb-10 max-w-3xl">
              <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-300">Current catalog</p>
              <h2 className="mep-heading mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">Lightning listings</h2>
              <p className="mt-4 leading-relaxed text-slate-300">Review the published details on each listing. If none appear, current Lightning availability is not shown in the catalog.</p>
            </div>
            <CatalogPreview type="lightning" />
          </div>
        </section>

        <section id="important-information" className="scroll-mt-8 border-y border-slate-800 bg-slate-900/70 py-12 sm:py-16">
          <div className="mx-auto grid max-w-7xl gap-8 px-4 sm:px-6 lg:grid-cols-[auto_1fr] lg:px-8">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-cyan-300/20 bg-cyan-300/5 text-cyan-200">
              <ShieldCheck aria-hidden="true" />
            </div>
            <div className="max-w-3xl">
              <h2 className="mep-heading text-2xl font-semibold text-white">Review terms and availability carefully</h2>
              <p className="mt-4 leading-relaxed text-slate-300">
                This page displays catalog information; it does not verify trading-rule enforcement, funding eligibility or timing, payout availability or timing, or provider connections. Check the published settings for an individual program before making a decision.
              </p>
              <p className="mt-3 leading-relaxed text-slate-300">
                Catalog information is not a payment or account activation. Quotes, if available, are unpaid and do not themselves activate an account or provide funding.
              </p>
              <a href="/trading-rules" className="mt-5 inline-flex items-center gap-2 font-medium text-cyan-200 underline decoration-cyan-400/40 underline-offset-4 hover:text-cyan-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">
                Review published trading rules <ArrowRight size={16} aria-hidden="true" />
              </a>
            </div>
          </div>
        </section>
      </main>
    </Layout>
  );
}
