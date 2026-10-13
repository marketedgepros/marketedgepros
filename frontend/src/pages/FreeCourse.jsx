import { BookOpen, ShieldCheck, ChartNoAxesCombined, ArrowRight } from 'lucide-react';
import Layout from '../components/layout/Layout';
import SEO from '../components/SEO';

const topics = [
  {
    title: 'Market fundamentals',
    description: 'An introductory look at financial markets, market structure, instruments, charts and timeframes.',
    icon: BookOpen,
  },
  {
    title: 'Technical analysis',
    description: 'Explore concepts such as support and resistance, trends, chart patterns and indicators.',
    icon: ChartNoAxesCombined,
  },
  {
    title: 'Risk and planning',
    description: 'Review risk-management concepts, trading plans, entries and exits, and keeping a trading journal.',
    icon: ShieldCheck,
  },
];

export default function FreeCourse() {
  return (
    <Layout>
      <SEO
        title="Trading Course Outline | MarketEdgePros"
        description="Explore introductory trading topics, including market fundamentals, technical analysis, risk management and strategy. Course availability and materials are not confirmed here."
        keywords="trading course outline, trading education, technical analysis, risk management"
        canonical="https://marketedgepros.com/free-course"
      />
      <main className="mep-screen min-h-screen py-16 sm:py-20">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <header className="mb-14 max-w-3xl">
            <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-cyan-400/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-300">
              <BookOpen className="h-4 w-4" aria-hidden="true" /> Course outline
            </p>
            <h1 className="mep-heading mb-5 text-4xl font-bold tracking-tight text-white sm:text-5xl">
              Introductory trading topics
            </h1>
            <p className="max-w-2xl text-lg leading-8 text-slate-300">
              Review a concise outline of subjects that may be covered, from market fundamentals to risk management and strategy.
            </p>
          </header>

          <section aria-labelledby="topics-heading" className="mb-12">
            <h2 id="topics-heading" className="mep-heading mb-6 text-2xl font-semibold text-white">Topics in the outline</h2>
            <div className="grid gap-5 md:grid-cols-3">
              {topics.map(({ title, description, icon: Icon }) => (
                <article key={title} className="mep-panel rounded-2xl border p-6 transition-colors hover:border-cyan-400/40">
                  <Icon className="mb-5 h-7 w-7 text-cyan-300" aria-hidden="true" />
                  <h3 className="mb-3 text-xl font-semibold text-white">{title}</h3>
                  <p className="leading-7 text-slate-300">{description}</p>
                </article>
              ))}
            </div>
          </section>

          <section aria-labelledby="availability-heading" className="rounded-2xl border border-cyan-400/25 bg-cyan-400/[0.06] p-6 sm:p-8">
            <h2 id="availability-heading" className="mep-heading mb-3 text-2xl font-semibold text-white">Availability and materials</h2>
            <p className="max-w-3xl leading-7 text-slate-300">
              This page provides a topic outline only. Course access, delivery format and learning materials have not been confirmed here. No registration or email submission is available on this page.
            </p>
            <nav aria-label="Related information" className="mt-6 flex flex-wrap gap-4">
              <a href="/programs" className="mep-primary inline-flex min-h-11 items-center gap-2 px-5 py-3 font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300">
                Explore programs <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </a>
              <a href="/contact" className="inline-flex min-h-11 items-center rounded-lg border border-white/20 px-5 py-3 font-semibold text-white transition-colors hover:border-cyan-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300">
                Contact
              </a>
            </nav>
          </section>
        </div>
      </main>
    </Layout>
  );
}
