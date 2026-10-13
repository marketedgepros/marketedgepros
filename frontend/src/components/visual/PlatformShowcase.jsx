import React, { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, Layers, ListChecks, MessageSquare, UserRound } from 'lucide-react';

const views = [
  { id: 'account', label: 'Account', Icon: UserRound, title: 'Your account, in one place.', text: 'Keep your profile and document records organized without switching between unrelated screens.', link: '/profile', action: 'Open your profile', items: [['Profile', 'Personal details'], ['Documents', 'Recorded review status'], ['Notifications', 'Account updates']], accent: 'Profile overview' },
  { id: 'challenges', label: 'Challenges', Icon: ListChecks, title: 'See the details behind the challenge.', text: 'Review your recorded challenges, their terms and history. Stored information is not a live trading connection.', link: '/challenges', action: 'Open your challenges', items: [['Overview', 'Recorded account details'], ['Rules', 'Program-specific terms'], ['History', 'Available records']], accent: 'Challenge workspace' },
  { id: 'support', label: 'Support', Icon: MessageSquare, title: 'Keep the conversation together.', text: 'Create a support ticket and follow your replies in the same account. No guaranteed response time is implied.', link: '/support/my-tickets', action: 'Open your tickets', items: [['Tickets', 'Your conversations'], ['Replies', 'Ticket message history'], ['Help', 'Browse available articles']], accent: 'Support workspace' },
];

export default function PlatformShowcase() {
  const [active, setActive] = useState('account');
  const id = useId();
  const view = views.find((entry) => entry.id === active) || views[0];
  return (
    <section className="platform-showcase relative border-y border-white/5 bg-[#091322] py-20" aria-labelledby={`${id}-heading`}>
      <div className="mx-auto max-w-7xl px-6 lg:px-8">
        <div className="mb-10 flex flex-wrap items-end justify-between gap-6">
          <div><p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">Inside MarketEdgePros</p><h2 id={`${id}-heading`} className="mep-heading mt-3 max-w-xl text-3xl font-semibold tracking-tight sm:text-4xl">A clearer view.<br /><span className="text-slate-400">A more connected workspace.</span></h2></div>
          <p className="max-w-sm text-sm leading-6 text-slate-400">Explore the workspace below. Account screens require sign-in; this illustration contains no customer data.</p>
        </div>
        <div className="mb-8 flex flex-wrap gap-3" role="group" aria-label="Choose a workspace view">
          {views.map(({ id: key, label, Icon }) => <button key={key} type="button" aria-pressed={active === key} aria-controls={`${id}-view`} onClick={() => setActive(key)} className="premium-view-button inline-flex min-h-12 items-center gap-2 rounded-xl border border-slate-600 px-5 py-3 text-sm font-semibold text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"><Icon size={17} aria-hidden="true" />{label}</button>)}
        </div>
        <div id={`${id}-view`} className="grid min-w-0 gap-10 lg:grid-cols-[.85fr_1.15fr] lg:items-center">
          <div key={view.id} className="premium-switch-in">
            <span className="inline-flex items-center gap-2 text-xs uppercase tracking-widest text-cyan-300"><Layers size={15} aria-hidden="true" />{view.accent}</span>
            <h3 className="mt-5 text-3xl font-semibold leading-tight tracking-tight">{view.title}</h3>
            <p className="mt-5 max-w-lg text-base leading-7 text-slate-400">{view.text}</p>
            <Link to={view.link} className="mt-7 inline-flex min-h-12 items-center gap-3 rounded-xl border border-cyan-300/40 px-5 py-3 font-semibold text-cyan-200 hover:border-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">{view.action}<ArrowUpRight size={18} aria-hidden="true" /></Link>
            <p className="mt-4 text-xs text-slate-500">Live trading, payments and payouts are not enabled.</p>
          </div>
          <div className="mep-panel premium-workspace-frame min-w-0 overflow-hidden rounded-2xl border shadow-2xl shadow-cyan-950/30" aria-label="Illustrative workspace preview">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-4"><span className="flex items-center gap-2 text-xs font-semibold text-slate-300"><span aria-hidden="true" className="h-2 w-2 rounded-full bg-cyan-300" />MarketEdgePros</span><span className="rounded-full border border-slate-600 px-3 py-1 text-[11px] text-slate-300">Illustrative preview · not live data</span></div>
            <div key={`workspace-${view.id}`} className="premium-switch-in p-5 sm:p-8">
              <div className="mb-7 flex items-start justify-between gap-3"><div><p className="text-xs uppercase tracking-[0.18em] text-cyan-300">{view.label}</p><p className="mt-2 text-xl font-semibold">{view.accent}</p></div><view.Icon className="shrink-0 text-cyan-300" size={24} aria-hidden="true" /></div>
              <div className="space-y-3">{view.items.map(([title, description]) => <div key={title} className="mep-panel flex flex-wrap items-center justify-between gap-2 rounded-xl border p-4"><span className="text-sm font-medium">{title}</span><span className="text-xs text-slate-400">{description}</span></div>)}</div>
              <div aria-hidden="true" className="premium-workspace-lines mt-7 flex h-14 items-end gap-2 overflow-hidden rounded-lg border border-cyan-400/10 bg-cyan-400/[0.03] p-3">{[32, 48, 36, 72, 55, 83, 65, 92, 78, 100, 88, 96].map((height, index) => <span key={index} style={{ height: `${height}%` }} className="w-full rounded-sm bg-cyan-300/15" />)}</div>
              <p className="mt-3 text-[11px] text-slate-500">Decorative layout only. No balance, performance or market feed.</p>
            </div>
          </div>
        </div>
        <p className="sr-only" aria-live="polite">{view.label} workspace preview selected.</p>
      </div>
    </section>
  );
}
