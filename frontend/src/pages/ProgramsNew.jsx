import React from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  FileText,
  SlidersHorizontal,
  ShieldCheck,
} from "lucide-react";
import useProgramCatalog from "../hooks/useProgramCatalog";
import { typeLabel } from "../services/programCatalogViewService";
import { APPROVED_ACCOUNT_MODEL, isProgramComingSoon } from "../services/programEvaluationPolicy.js";
import ComingSoonProgram from "../components/programs/ComingSoonProgram";
import {
  CatalogPage,
  CatalogState,
  CatalogCard,
  PaymentBoundary,
  panelStyle,
  secondaryAction,
} from "../components/programs/CatalogUI";
import ProgramSelector from "../components/programs/ProgramSelector";
import ProgramComparison from "../components/programs/ProgramComparison";

export default function ProgramsNew() {
  const catalog = useProgramCatalog();
  const [searchParams, setSearchParams] = useSearchParams();
  const aliases = {
    "one-phase": "one_phase",
    "two-phase": "two_phase",
    "three-phase": "three_phase",
    instant: "instant_funding",
  };
  const rawFilter = searchParams.get("filter") || "all";
  const selectedType = aliases[rawFilter] || rawFilter;
  const setSelectedType = (type) => {
    const next = new URLSearchParams(searchParams);
    if (type === "all") next.delete("filter");
    else next.set("filter", type);
    setSearchParams(next);
  };
  const programs = catalog.data || [];
  const evaluationPrograms = programs.filter((program) => !isProgramComingSoon(program.terms));
  const types = [...new Set([...programs.map((program) => program.terms.type), "instant_funding"])];
  const activeType =
    selectedType === "all" || types.includes(selectedType)
      ? selectedType
      : "all";
  const visible =
    activeType === "all"
      ? evaluationPrograms
      : evaluationPrograms.filter((program) => program.terms.type === activeType);
  const catalogReady = !catalog.loading && !catalog.error && programs.length > 0;
  return (
    <CatalogPage>
      <header className="mb-12 grid items-start gap-8 lg:grid-cols-[1.35fr_1fr]">
        <div>
          <p className="mb-5 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
            Program catalog
          </p>
          <h1 className="mep-heading max-w-2xl text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
            Your next challenge.
            <br />
            <span className="text-cyan-300">Know the rules first.</span>
          </h1>
          <p className="mt-6 max-w-xl text-base leading-relaxed text-slate-300">
            Compare account sizes, fees and published limits. Choose a program
            to review its options. Quote requests may not be available.
          </p>
          <a href="#program-comparison" className={`${secondaryAction} mt-7`}>
            Compare programs
            <ArrowDown size={16} aria-hidden="true" />
          </a>
          <p data-account-model={APPROVED_ACCOUNT_MODEL.version} className="mt-5 max-w-xl text-sm leading-relaxed text-slate-300">
            {APPROVED_ACCOUNT_MODEL.description}
          </p>
        </div>
        <aside className={panelStyle} aria-label="Selection process">
          <ol className="space-y-6">
            {[
              [
                SlidersHorizontal,
                "01",
                "Compare the catalog",
                "Active programs from the configured brand.",
              ],
              [
                FileText,
                "02",
                "Review a quote",
                "If enabled, the server can return a quote for your selection.",
              ],
              [
                ShieldCheck,
                "03",
                "Check availability",
                "Payment and account activation are not enabled.",
              ],
            ].map(([Icon, step, title, description]) => (
              <li key={step} className="flex gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-cyan-400/10 text-cyan-300">
                  <Icon size={19} aria-hidden="true" />
                </div>
                <div>
                  <p className="text-xs tabular-nums text-slate-500">{step}</p>
                  <p className="font-semibold">{title}</p>
                  <p className="mt-1 text-sm text-slate-400">{description}</p>
                </div>
              </li>
            ))}
          </ol>
        </aside>
      </header>
      {catalogReady && (
        <section className="mb-10" aria-label="Program chooser">
          <ProgramSelector programs={evaluationPrograms} />
        </section>
      )}
      {catalogReady && (
        <ProgramComparison key={catalog.key} programs={evaluationPrograms} />
      )}
      <section
        id="program-catalog"
        className="scroll-mt-24"
        aria-labelledby="catalog-heading"
      >
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 id="catalog-heading" className="mep-heading text-2xl font-semibold">
              Compare current programs
            </h2>
            <p className="mt-2 text-sm text-slate-400">
              Catalog fees are shown in USD. Unspecified rules are never treated
              as zero.
            </p>
          </div>
        </div>
        {catalogReady && (
          <div className="mb-7">
            <p className="mb-3 text-sm font-medium text-slate-300">
              Filter the full comparison
            </p>
            <div
              className="flex flex-wrap gap-2"
              role="group"
              aria-label="Filter by program type"
            >
              {["all", ...types].map((type) => (
                <button
                  type="button"
                  key={type}
                  aria-pressed={activeType === type}
                  onClick={() => setSelectedType(type)}
                  className={`${secondaryAction} ${activeType === type ? "border-cyan-400 bg-cyan-400/10 text-cyan-200" : ""}`}
                >
                  {type === "all" ? "All programs" : type === "instant_funding" ? "Instant Funding — Coming soon" : typeLabel(type)}
                </button>
              ))}
            </div>
          </div>
        )}
        {catalog.loading || catalog.error || !programs.length ? (
          <CatalogState
            loading={catalog.loading}
            error={catalog.error}
            retry={catalog.retry}
            empty={!catalog.loading && !catalog.error}
          />
        ) : (
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {visible.map((program) => (
              <CatalogCard key={program.id} program={program} />
            ))}
          </div>
        )}
        {(activeType === "all" || activeType === "instant_funding") && <div className="mt-6"><ComingSoonProgram /></div>}
      </section>
      <div className="mt-8">
        <PaymentBoundary />
      </div>
    </CatalogPage>
  );
}
