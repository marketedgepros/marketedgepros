import React, { useMemo, useState } from 'react';
import { ChevronDown, HelpCircle, Search } from 'lucide-react';
import Layout from '../components/layout/Layout';
import StructuredData from '../components/seo/StructuredData';

const categories = [
  {
    name: 'Getting Started',
    questions: [
      { q: 'What is MarketEdgePros?', a: 'MarketEdgePros provides information about trading programs and related account services. Program availability and details may change; review the current program information before making a decision.' },
      { q: 'How do I get started?', a: 'Explore the available programs and review the information shown for the program you are considering. Registration and purchase availability are not guaranteed by this FAQ.' },
      { q: 'Where can I find current program details?', a: 'Visit the Programs page and review the specific program listing. Do not assume that a rule or term shown for one program applies to another.' },
    ],
  },
  {
    name: 'Programs & Rules',
    questions: [
      { q: 'What program types and terms are available?', a: 'Available programs and their displayed details are listed on the Programs page. Check the specific listing for its current information; this FAQ does not establish universal program terms.' },
      { q: 'What trading rules apply?', a: 'Review the rules and terms presented for the specific program. General trading permissions or restrictions are not established by this FAQ.' },
      { q: 'Are trading platforms or automated strategies supported?', a: 'This FAQ does not verify platform availability or permissions for automated strategies. Check current program information and applicable rules before relying on either.' },
    ],
  },
  {
    name: 'Account & Payments',
    questions: [
      { q: 'When will an account or trading access be available?', a: 'This FAQ cannot confirm account issuance, access timing, or trading availability. Review the current program information; do not treat a quote or displayed price as payment settlement or account entitlement.' },
      { q: 'What are the payout terms?', a: 'Payout availability, eligibility, methods, timing, and amounts are not confirmed here. No payout or payment terms should be inferred from this FAQ.' },
      { q: 'What fees, add-ons, or refund terms apply?', a: 'This FAQ does not establish fees, add-on availability, or refund rights. Review the information applicable to the specific program and any separately approved terms.' },
    ],
  },
  {
    name: 'Help & Information',
    questions: [
      { q: 'Where can I ask a question?', a: 'Use the Contact page to view the available contact options. This page does not promise support availability or a response time.' },
      { q: 'Where can I find information about privacy and security?', a: 'See the Privacy Policy for the published privacy information. This FAQ makes no separate security, compliance, or data-protection guarantee.' },
    ],
  },
];

const allQuestions = categories.flatMap((category, categoryIndex) =>
  category.questions.map((question, questionIndex) => ({
    ...question,
    category: category.name,
    index: `${categoryIndex}-${questionIndex}`,
  })),
);

export default function FAQ() {
  const [searchTerm, setSearchTerm] = useState('');
  const [openIndex, setOpenIndex] = useState(null);
  const filteredQuestions = useMemo(() => {
    const query = searchTerm.trim().toLocaleLowerCase();
    if (!query) return allQuestions;
    return allQuestions.filter(({ q, a, category }) =>
      `${q} ${a} ${category}`.toLocaleLowerCase().includes(query),
    );
  }, [searchTerm]);
  const faqData = { questions: allQuestions.map(({ q, a }) => ({ question: q, answer: a })) };

  const renderQuestion = (item, showCategory = false) => {
    const expanded = openIndex === item.index;
    const answerId = `faq-answer-${item.index}`;
    return (
      <article key={item.index} className="overflow-hidden rounded-2xl border border-cyan-900/70 bg-slate-900/80 transition-colors hover:border-cyan-700">
        <button
          type="button"
          onClick={() => setOpenIndex(expanded ? null : item.index)}
          aria-expanded={expanded}
          aria-controls={answerId}
          className="flex w-full items-center justify-between gap-5 px-6 py-5 text-left text-white outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-400 sm:px-8"
        >
          <span className="flex-1">
            {showCategory && <span className="mb-2 block text-sm font-semibold text-cyan-300">{item.category}</span>}
            <span className="block text-lg font-semibold">{item.q}</span>
          </span>
          <ChevronDown aria-hidden="true" className={`h-5 w-5 shrink-0 text-cyan-300 transition-transform motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`} />
        </button>
        <div id={answerId} hidden={!expanded}>
          <p className="border-t border-slate-700 px-6 py-5 leading-relaxed text-slate-300 sm:px-8">{item.a}</p>
        </div>
      </article>
    );
  };

  return (
    <Layout>
      <StructuredData type="faq" data={faqData} />
      <main className="min-h-screen bg-slate-950 text-white">
        <section className="relative overflow-hidden border-b border-cyan-950 bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950/50 px-4 py-20 sm:py-28">
          <div className="relative mx-auto max-w-5xl text-center">
            <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl border border-cyan-700/70 bg-cyan-950/60 text-cyan-300">
              <HelpCircle aria-hidden="true" className="h-7 w-7" />
            </div>
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">MarketEdgePros</p>
            <h1 className="text-4xl font-bold tracking-tight sm:text-6xl">Frequently Asked Questions</h1>
            <p className="mx-auto mt-5 max-w-2xl text-lg leading-relaxed text-slate-300">Find general information and where to check current program details.</p>
            <div className="relative mx-auto mt-9 max-w-2xl">
              <Search aria-hidden="true" className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
              <label className="sr-only" htmlFor="faq-search">Search questions and answers</label>
              <input
                id="faq-search"
                type="search"
                placeholder="Search questions and answers…"
                value={searchTerm}
                onChange={(event) => { setSearchTerm(event.target.value); setOpenIndex(null); }}
                className="w-full rounded-xl border border-slate-700 bg-slate-900/90 py-4 pl-12 pr-4 text-white placeholder:text-slate-400 outline-none focus-visible:border-cyan-400 focus-visible:ring-2 focus-visible:ring-cyan-400/40"
              />
            </div>
          </div>
        </section>
        <section aria-label="Frequently asked questions" className="px-4 py-14 sm:py-20">
          <div className="mx-auto max-w-4xl">
            {searchTerm.trim() ? (
              <div className="space-y-4" aria-live="polite">
                <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-300">
                  <p>{filteredQuestions.length ? `${filteredQuestions.length} matching question${filteredQuestions.length === 1 ? '' : 's'}` : 'No questions match your search.'}</p>
                  <button type="button" onClick={() => { setSearchTerm(''); setOpenIndex(null); }} className="rounded-md px-2 py-1 font-semibold text-cyan-300 underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">Clear search</button>
                </div>
                {filteredQuestions.map((item) => renderQuestion(item, true))}
              </div>
            ) : (
              <div className="space-y-12">
                {categories.map((category) => (
                  <section key={category.name}>
                    <h2 className="mb-5 border-l-2 border-cyan-400 pl-4 text-2xl font-bold text-white">{category.name}</h2>
                    <div className="space-y-3">{category.questions.map((item, questionIndex) => renderQuestion({ ...item, index: `${categories.indexOf(category)}-${questionIndex}` }))}</div>
                  </section>
                ))}
              </div>
            )}
          </div>
        </section>
        <section className="border-t border-slate-800 bg-slate-900/60 px-4 py-14">
          <div className="mx-auto max-w-4xl text-center">
            <h2 className="text-2xl font-bold sm:text-3xl">Need more information?</h2>
            <p className="mt-3 text-slate-300">Visit the programs page for program-specific details, or see the contact options.</p>
            <div className="mt-7 flex flex-wrap justify-center gap-4">
              <a href="/programs" className="rounded-lg bg-cyan-700 px-6 py-3 font-semibold text-white outline-none transition-colors hover:bg-cyan-600 focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900">Explore programs</a>
              <a href="/contact" className="rounded-lg border border-slate-600 px-6 py-3 font-semibold text-white outline-none transition-colors hover:border-cyan-400 hover:text-cyan-200 focus-visible:ring-2 focus-visible:ring-cyan-300">Contact</a>
            </div>
          </div>
        </section>
      </main>
    </Layout>
  );
}
