import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { formatCatalogMoney } from '../../services/programCatalogViewService.js';
import { ConfiguredRules, ProgramRules, primaryAction } from './CatalogUI';

export default function ProgramRuleFamily({ family, programs, unavailable = false }) {
  const [selectedId, setSelectedId] = useState('');
  const choices = programs.filter((program) => program.terms.type === family.type);
  // A changed catalog cannot leave a removed selection visible. Never substitute
  // another family, saved terms or the owner-approved draft model.
  const selected = choices.find((program) => String(program.id) === selectedId) ?? choices[0];
  return (
    <section id={family.anchor} className="mep-panel scroll-mt-28 rounded-2xl border p-6 sm:p-9" aria-labelledby={`${family.anchor}-heading`}>
      <p className="text-xs font-semibold uppercase tracking-[0.15em] text-cyan-300">Program rule category</p>
      <h2 id={`${family.anchor}-heading`} className="mep-heading mt-3 text-2xl font-semibold">{family.title}</h2>
      <p className="mt-3 leading-relaxed text-slate-300">{family.description}</p>
      <p className="mt-3 text-sm text-cyan-200">Evaluation stages: {family.stages === 0 ? 'None in this catalog family' : family.stages}</p>
      {!selected ? (
        <p className="mt-5 text-sm text-slate-400">{unavailable ? 'Catalog settings are not available yet. No substitute rules are displayed.' : 'No active program is currently listed in this category. No substitute rules are displayed.'}</p>
      ) : (
        <>
          <div className="mt-6">
            <label htmlFor={`${family.anchor}-program`} className="block text-sm font-semibold text-slate-200">Choose a program in this category</label>
            <select id={`${family.anchor}-program`} value={String(selected.id)} onChange={(event) => setSelectedId(event.target.value)} className="mt-2 min-h-11 w-full min-w-0 rounded-xl border border-slate-600 bg-slate-950 px-3 py-3 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-300">
              {choices.map((program) => <option key={program.id} value={String(program.id)}>{program.terms.name} — {formatCatalogMoney(program.terms.account_size)}</option>)}
            </select>
          </div>
          <div className="mt-5" data-family-program={selected.id}>
            <h3 className="break-words text-lg font-semibold text-cyan-100">{selected.terms.name}</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">Published catalog values for this selection. Not specified means missing information, not zero or unlimited permission.</p>
            <ProgramRules terms={selected.terms} />
          </div>
          {family.stages > 1 && (
            <aside className="mt-5 rounded-xl border border-amber-400/30 bg-amber-400/5 p-4 text-sm leading-relaxed text-amber-100">
              Individual stage targets and transition criteria still require confirmation. The catalog contains one profit-target field; it does not establish a separate target for each stage.
            </aside>
          )}
          <div className="mt-5"><ConfiguredRules terms={selected.terms} headingId={`${family.anchor}-additional`} /></div>
          <Link to={`/programs/${selected.id}`} className={`${primaryAction} mt-5`}>View this program <ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
          {family.type === 'one_phase' && <p className="mt-4 text-sm text-slate-400">The approved one-phase update below is a separate information model. It does not replace this selection’s catalog terms.</p>}
        </>
      )}
    </section>
  );
}
