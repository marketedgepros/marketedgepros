import React from "react";
import { Link } from "react-router-dom";
import useProgramCatalog from "../../hooks/useProgramCatalog";
import ProgramSelector from "./ProgramSelector";
import {
  CatalogCard,
  CatalogState,
  PaymentBoundary,
  secondaryAction,
} from "./CatalogUI";

export default function CatalogPreview({ type = null, interactive = false }) {
  const catalog = useProgramCatalog();
  const programs = (catalog.data || []).filter(
    (program) => type === null || program.terms.type === type,
  );
  return (
    <div className="min-w-0 space-y-6">
      {catalog.loading || catalog.error || !programs.length ? (
        <CatalogState {...catalog} empty={!catalog.loading && !catalog.error} />
      ) : interactive ? (
        <ProgramSelector programs={programs} />
      ) : (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {programs.map((program) => (
            <CatalogCard key={program.id} program={program} />
          ))}
        </div>
      )}
      <PaymentBoundary />
      <Link to="/programs" className={secondaryAction}>
        Compare all current programs
      </Link>
    </div>
  );
}
