import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, HelpCircle, Search } from 'lucide-react';
import Layout from '../components/layout/Layout';
import StructuredData from '../components/seo/StructuredData';
import { EVALUATION_RULES_FAQ } from '../services/programEvaluationPolicy.js';

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
      { q: 'What trading rules apply?', a: EVALUATION_RULES_FAQ.trading },
      { q: 'Are trading platforms or automated strategies supported?', a: 'This FAQ does not verify platform availability or permissions for automated strategies. Check current program information and applicable rules before relying on either.' },
    ],
  },
  {
    name: 'Account & Payments',
    questions: [
      { q: 'When will an account or trading access be available?', a: 'This FAQ cannot confirm account issuance, access timing, or trading availability. Review the current program information; do not treat a quote or displayed price as payment settlement or account entitlement.' },
      { q: 'What are the payout terms?', a: EVALUATION_RULES_FAQ.payout },
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
const answerLinks = {
  '0-1': { to: '/programs', label: 'Explore programs' },
  '0-2': { to: '/programs', label: 'View current programs' },
  '1-0': { to: '/programs', label: 'View current programs' },
  '1-1': { to: '/trading-rules', label: 'Read evaluation rules' },
  '2-1': { to: '/trading-rules#profit-share-heading', label: 'Read profit sharing information' },
  '3-0': { to: '/contact', label: 'View contact options' },
  '3-1': { to: '/privacy-policy', label: 'View privacy information' },
};

export default function FAQ() {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [openIndex, setOpenIndex] = useState(null);
  const hasSearch = Boolean(searchTerm.trim());
  const filteredQuestions = useMemo(() => {
    const query = searchTerm.trim().toLocaleLowerCase();
    return allQuestions.filter(({ q, a, category }) =>
      (selectedCategory === null || category === selectedCategory) &&
      (!query || `${q} ${a} ${category}`.toLocaleLowerCase().includes(query)),
    );
  }, [searchTerm, selectedCategory]);
  const faqData = { questions: allQuestions.map(({ q, a }) => ({ question: q, answer: a })) };
  const clearSearch = () => { setSearchTerm(''); setOpenIndex(null); };
  const resetFilters = () => { clearSearch(); setSelectedCategory(null); };

  const renderQuestion = (item, showCategory = false) => {
    const expanded = openIndex === item.index;
    const answerId = `faq-answer-${item.index}`;
    const link = answerLinks[item.index];
    return (
      <article key={item.index} className="mep-panel overflow-hidden rounded-2xl border transition-colors motion-reduce:transition-none hover:border-cyan-700">
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
          {link && (
            <Link to={link.to} className="mx-6 mb-5 inline-block rounded font-semibold text-cyan-200 underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 sm:mx-8">
              {link.label}
            </Link>
          )}
        </div>
      </article>
    );
  };

  return (
    <Layout>
      <StructuredData type="faq" data={faqData} />
      <div className="mep-screen min-h-screen text-white">
        <section className="relative overflow-hidden border-b border-cyan-950 bg-gradient-to-br from-slate-950 via-slate-900 to-cyan-950/50 px-4 py-20 sm:py-28">
          <div className="relative mx-auto max-w-5xl text-center">
            <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl border border-cyan-700/70 bg-cyan-950/60 text-cyan-300">
              <HelpCircle aria-hidden="true" className="h-7 w-7" />
            </div>
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300">MarketEdgePros</p>
            <h1 className="mep-heading text-4xl font-bold tracking-tight sm:text-6xl">Frequently Asked Questions</h1>
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
                aria-describedby="faq-results-status"
                className="w-full rounded-xl border border-slate-700 bg-slate-900/90 py-4 pl-12 pr-4 text-white placeholder:text-slate-400 outline-none focus-visible:border-cyan-400 focus-visible:ring-2 focus-visible:ring-cyan-400/40"
              />
            </div>
          </div>
        </section>
        <section aria-label="Frequently asked questions" className="px-4 py-14 sm:py-20">
          <div className="mx-auto max-w-4xl">
            <div className="mb-8 flex flex-wrap gap-2" role="group" aria-label="Filter questions by topic">
              {[null, ...categories.map(({ name }) => name)].map((name) => (
                <button
                  key={name ?? 'all'}
                  type="button"
                  aria-pressed={selectedCategory === name}
                  onClick={() => { setSelectedCategory(name); setOpenIndex(null); }}
                  className={`rounded-full border px-4 py-2 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${selectedCategory === name ? 'border-cyan-400 bg-cyan-400 text-slate-950' : 'border-slate-600 text-slate-200 hover:border-cyan-400'}`}
                >
                  {name ?? 'All topics'}
                </button>
              ))}
            </div>
            <div className="mb-7 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-300">
              <p id="faq-results-status" role="status" aria-live="polite">
                {filteredQuestions.length
                  ? `${filteredQuestions.length} ${hasSearch ? 'matching' : 'available'} question${filteredQuestions.length === 1 ? '' : 's'}${selectedCategory ? ` in ${selectedCategory}` : ''}`
                  : 'No questions match your search.'}
              </p>
              <div className="flex flex-wrap gap-3">
                {hasSearch && <button type="button" onClick={clearSearch} className="rounded-md px-2 py-1 font-semibold text-cyan-300 underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">Clear search</button>}
                {(hasSearch || selectedCategory !== null) && <button type="button" onClick={resetFilters} className="rounded-md px-2 py-1 font-semibold text-cyan-300 underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">Reset filters</button>}
              </div>
            </div>
            {!filteredQuestions.length ? (
              <div className="mep-panel rounded-2xl border p-6">
                <h2 className="mep-heading text-xl font-semibold">Try another topic or search</h2>
                <p className="mt-3 leading-relaxed text-slate-300">Clear the search to see this topic, or reset filters to browse all questions. Program-specific details are in the current program listings.</p>
              </div>
            ) : hasSearch ? (
              <div className="space-y-4">{filteredQuestions.map((item) => renderQuestion(item, true))}</div>
            ) : (
              <div className="space-y-12">
                {categories.filter(({ name }) => selectedCategory === null || name === selectedCategory).map((category) => (
                  <section key={category.name}>
                    <h2 className="mep-heading mb-5 border-l-2 border-cyan-400 pl-4 text-2xl font-bold text-white">{category.name}</h2>
                    <div className="space-y-3">{filteredQuestions.filter((item) => item.category === category.name).map((item) => renderQuestion(item))}</div>
                  </section>
                ))}
              </div>
            )}
          </div>
        </section>
        <section className="border-t border-slate-800 bg-slate-900/60 px-4 py-14">
          <div className="mx-auto max-w-4xl text-center">
            <h2 className="mep-heading text-2xl font-bold sm:text-3xl">Need more information?</h2>
            <p className="mt-3 text-slate-300">Visit the programs page for program-specific details, or see the contact options.</p>
            <div className="mt-7 flex flex-wrap justify-center gap-4">
              <Link to="/programs" className="mep-primary px-6 py-3 font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900">Explore programs</Link>
              <Link to="/contact" className="rounded-lg border border-slate-600 px-6 py-3 font-semibold text-white outline-none transition-colors hover:border-cyan-400 hover:text-cyan-200 focus-visible:ring-2 focus-visible:ring-cyan-300">Contact</Link>
            </div>
          </div>
        </section>
      </div>
    </Layout>
  );
}
