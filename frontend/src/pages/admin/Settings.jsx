import { useCallback, useRef, useState } from "react";
import { AlertTriangle, Loader2, RefreshCw, Save, ShieldAlert } from "lucide-react";
import useAuthStore from "../../store/authStore.js";
import {
  adminClosureSettingsError,
  isAdminClosureSettingsContactEmail,
  loadAdminClosureSettings,
  saveAdminClosureSettings,
} from "../../services/adminClosureSettingsService.js";
import useAdminClosureSettings from "../../hooks/useAdminClosureSettings.js";

const inputClass = "mt-2 block w-full rounded-lg border border-slate-600 bg-slate-950/70 px-3 py-2.5 text-sm text-white shadow-inner shadow-black/10 outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/30 disabled:cursor-not-allowed disabled:opacity-60";
const panelClass = "rounded-xl border border-slate-700/80 bg-slate-900/80 p-5 shadow-lg shadow-black/10 sm:p-6";

const messageFor = (error, fallback) => (
  error instanceof Error && error.message ? error.message : fallback
);

export function AdminClosureSettingsContent({ read }) {
  const tenant = read.draft;
  const disabled = read.loading || read.saving || !read.value;
  const contactEmailRef = useRef(null);
  const [contactEmailError, setContactEmailError] = useState(null);
  const save = async (event) => {
    event.preventDefault();
    if (!isAdminClosureSettingsContactEmail(tenant.contact_email)) {
      setContactEmailError("Enter a valid contact email address or leave this optional field blank.");
      contactEmailRef.current?.focus();
      return;
    }
    setContactEmailError(null);
    await read.saveDraft();
  };

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <header className="flex flex-col gap-4 border-b border-slate-700/80 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Administrator settings</p>
          <h1 className="mep-heading mt-2 text-2xl font-bold tracking-tight text-white sm:text-3xl">Tenant contact settings</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">Only persisted tenant contact fields are shown. The server confirms both the session owner and tenant scope before returning or changing a value.</p>
        </div>
        <button
          type="button"
          onClick={read.refresh}
          disabled={read.loading || read.saving}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-cyan-300/40 bg-cyan-300/10 px-4 py-2.5 text-sm font-semibold text-cyan-50 transition hover:border-cyan-200 hover:bg-cyan-300/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {read.loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
          Refresh persisted values
        </button>
      </header>

      <section className="rounded-xl border border-cyan-400/25 bg-cyan-400/5 p-4" aria-labelledby="settings-scope-heading">
        <div className="flex gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" aria-hidden="true" />
          <div className="min-w-0">
            <h2 id="settings-scope-heading" className="mep-heading font-semibold text-cyan-50">Explicit tenant scope</h2>
            <p className="mt-1 break-words text-sm leading-6 text-slate-200">{read.value ? `The server acknowledgement is scoped to tenant ${read.value.scope.tenantId}.` : "A configured platform-root session is required before any tenant setting can be loaded or saved."} This page never selects a tenant from a URL or form value.</p>
          </div>
        </div>
      </section>

      {read.loading && (
        <section role="status" aria-live="polite" aria-busy="true" className={`${panelClass} flex items-center gap-3 text-slate-200`}>
          <Loader2 className="h-5 w-5 animate-spin text-cyan-300" aria-hidden="true" />
          Loading the persisted tenant settings…
        </section>
      )}

      {read.error && (
        <section role="alert" className="rounded-xl border border-rose-400/40 bg-rose-500/10 p-4 text-rose-50">
          <div className="flex gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
            <div className="min-w-0">
              <h2 className="mep-heading font-semibold">Persisted settings are unavailable</h2>
              <p className="mt-1 break-words text-sm leading-6">{messageFor(read.error, adminClosureSettingsError())}</p>
            </div>
          </div>
        </section>
      )}

      {read.value && tenant && !read.loading && (
        <section className={panelClass} aria-labelledby="tenant-contact-heading">
          <div className="flex flex-col gap-2 border-b border-slate-700 pb-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 id="tenant-contact-heading" className="mep-heading text-lg font-semibold text-white">Persisted tenant contact fields</h2>
              <p className="mt-1 text-sm leading-6 text-slate-300">Blank contact fields are stored as unavailable values, not inferred or replaced with examples.</p>
            </div>
            <span className="text-xs font-medium uppercase tracking-wide text-cyan-200">Tenant {read.value.scope.tenantId}</span>
          </div>

          <form className="mt-5 space-y-5" onSubmit={save} noValidate>
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="lg:col-span-2">
                <label htmlFor="admin-closure-tenant-name" className="text-sm font-medium text-slate-100">Tenant name</label>
                <input
                  id="admin-closure-tenant-name"
                  name="name"
                  type="text"
                  autoComplete="organization"
                  maxLength={255}
                  required
                  disabled={disabled}
                  value={tenant.name}
                  onChange={(event) => read.editDraft((draft) => ({ ...draft, name: event.target.value }))}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="admin-closure-contact-email" className="text-sm font-medium text-slate-100">Contact email <span className="text-slate-400">(optional)</span></label>
                <input
                  id="admin-closure-contact-email"
                  name="contact_email"
                  type="email"
                  autoComplete="email"
                  maxLength={255}
                  disabled={disabled}
                  ref={contactEmailRef}
                  value={tenant.contact_email ?? ""}
                  aria-invalid={contactEmailError ? "true" : undefined}
                  aria-describedby={contactEmailError ? "admin-closure-contact-email-error" : undefined}
                  onChange={(event) => {
                    const contactEmail = event.target.value === "" ? null : event.target.value;
                    read.editDraft((draft) => ({ ...draft, contact_email: contactEmail }));
                    if (isAdminClosureSettingsContactEmail(contactEmail)) setContactEmailError(null);
                  }}
                  className={inputClass}
                />
                {contactEmailError && (
                  <p id="admin-closure-contact-email-error" role="alert" className="mt-2 text-sm leading-6 text-rose-200">
                    {contactEmailError}
                  </p>
                )}
              </div>
              <div>
                <label htmlFor="admin-closure-contact-phone" className="text-sm font-medium text-slate-100">Contact phone <span className="text-slate-400">(optional)</span></label>
                <input
                  id="admin-closure-contact-phone"
                  name="contact_phone"
                  type="tel"
                  autoComplete="tel"
                  maxLength={20}
                  disabled={disabled}
                  value={tenant.contact_phone ?? ""}
                  onChange={(event) => read.editDraft((draft) => ({ ...draft, contact_phone: event.target.value || null }))}
                  className={inputClass}
                />
              </div>
            </div>

            {read.actionError && (
              <p role="alert" className="rounded-lg border border-rose-400/40 bg-rose-500/10 px-3 py-2 text-sm leading-6 text-rose-100">{messageFor(read.actionError, adminClosureSettingsError())}</p>
            )}
            {read.acknowledgement && (
              <p role="status" aria-live="polite" className="rounded-lg border border-emerald-400/35 bg-emerald-500/10 px-3 py-2 text-sm leading-6 text-emerald-50">{read.acknowledgement}</p>
            )}

            <div className="flex flex-col gap-3 border-t border-slate-700 pt-5 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-slate-300">{read.dirty ? "Unsaved changes are local until the server acknowledges persistence." : "The form matches the latest server acknowledgement."}</p>
              <button
                type="submit"
                disabled={!read.dirty || disabled}
                className="mep-primary inline-flex min-h-11 items-center justify-center gap-2 px-4 py-2.5 text-sm font-bold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {read.saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Save className="h-4 w-4" aria-hidden="true" />}
                {read.saving ? "Saving persisted fields…" : "Save tenant contact fields"}
              </button>
            </div>
          </form>
        </section>
      )}

      <section className={`${panelClass} border-amber-300/25`} aria-labelledby="unavailable-settings-heading">
        <div className="flex gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-200" aria-hidden="true" />
          <div className="min-w-0">
            <h2 id="unavailable-settings-heading" className="mep-heading text-lg font-semibold text-white">Unavailable configuration categories</h2>
            <p className="mt-1 text-sm leading-6 text-slate-300">These categories have no editable controls because this repository has no verified persistence contract for them. No value, connection, restart, or success state is simulated.</p>
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <article className="mep-panel rounded-lg border p-4">
            <h3 className="font-semibold text-slate-100">Global system settings</h3>
            <p className="mt-2 text-sm leading-6 text-slate-300">Missing capability: a persisted global-settings model and a root-only global configuration write contract. Environment-backed application configuration is not edited here.</p>
          </article>
          <article className="mep-panel rounded-lg border p-4">
            <h3 className="font-semibold text-slate-100">Payment-provider configuration</h3>
            <p className="mt-2 text-sm leading-6 text-slate-300">Missing capability: an approved server-side provider-configuration persistence contract. Provider credentials, API keys, payout thresholds, enablement switches, and restart controls are intentionally not displayed or accepted.</p>
          </article>
        </div>
      </section>
    </div>
  );
}

export default function Settings() {
  const { user, isAuthenticated } = useAuthStore();
  const load = useCallback((expectedOwner, signal) => loadAdminClosureSettings({ expectedOwner, signal }), []);
  const save = useCallback((expectedOwner, draft, signal) => saveAdminClosureSettings({ expectedOwner, draft, signal }), []);
  const read = useAdminClosureSettings({
    isAuthenticated,
    userId: user?.id,
    tenantId: user?.tenant_id,
    role: user?.role,
    load,
    save,
  });
  return <AdminClosureSettingsContent read={read} />;
}
