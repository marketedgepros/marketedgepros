import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Activity, Calendar, ChevronLeft, ChevronRight, DollarSign, Mail, Phone, Plus, Search, Target, TrendingUp, Users, X } from 'lucide-react';
import AdminLayout from '../../components/admin/AdminLayout';
import { useToast } from '../../contexts/ToastContext';
import useAdminClosureCrmIdentityGuard from '../../hooks/useAdminClosureCrmIdentityGuard';
import useDialogFocus from '../../hooks/useDialogFocus';
import useAuthStore from '../../store/authStore';
import {
  ADMIN_CLOSURE_CRM_SOURCES,
  ADMIN_CLOSURE_CRM_STATUSES,
  adminClosureCrmError,
  adminClosureCrmPrincipalFromAuth,
  createAdminClosureCrmService,
  formatAdminClosureCrmBudget,
  isAdminClosureCrmRequestCanceled,
} from '../../services/adminClosureCrmService';

const crmService = createAdminClosureCrmService();
const emptyStats = { total: null, new: null, contacted: null, qualified: null, converted: null };
const blankLead = () => ({ first_name: '', last_name: '', email: '', phone: '', company: '', source: 'website', status: 'new', budget: '' });

const statusColor = (status) => ({
  new: 'bg-blue-500/15 text-blue-200 border-blue-400/30',
  contacted: 'bg-amber-500/15 text-amber-200 border-amber-400/30',
  qualified: 'bg-violet-500/15 text-violet-200 border-violet-400/30',
  proposal: 'bg-cyan-500/15 text-cyan-200 border-cyan-400/30',
  negotiation: 'bg-orange-500/15 text-orange-200 border-orange-400/30',
  converted: 'bg-emerald-500/15 text-emerald-200 border-emerald-400/30',
  lost: 'bg-rose-500/15 text-rose-200 border-rose-400/30',
}[status] || 'bg-slate-600 text-slate-100 border-slate-500');

const scoreColor = (score) => (score >= 80 ? 'text-emerald-300' : score >= 50 ? 'text-amber-200' : 'text-rose-200');
const displayName = (lead) => `${lead.first_name} ${lead.last_name}`;

function StatCard({ label, value, icon: Icon, tint }) {
  return (
    <div className="mep-panel rounded-xl border p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm text-slate-400">{label}</p>
          <p className="mt-1 text-2xl font-semibold text-white" aria-label={`${label}: ${value === null ? 'unavailable' : value}`}>
            {value === null ? '—' : value}
          </p>
        </div>
        <span className={`rounded-lg p-3 ${tint}`} aria-hidden="true"><Icon size={22} /></span>
      </div>
    </div>
  );
}

export default function CRM() {
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const principal = useMemo(() => adminClosureCrmPrincipalFromAuth(user, isAuthenticated), [user, isAuthenticated]);
  const identity = useAdminClosureCrmIdentityGuard(principal);

  return <CRMContent key={principal?.key ?? 'missing-principal'} principal={principal} identity={identity} />;
}

function CRMContent({ principal, identity }) {
  const navigate = useNavigate();
  const toast = useToast();
  const principalKey = principal?.key ?? null;
  const [view, setView] = useState('table');
  const [filters, setFilters] = useState({ status: null, source: null, search: '' });
  const [searchDraft, setSearchDraft] = useState('');
  const [page, setPage] = useState(1);
  const [leads, setLeads] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, per_page: 20, total: 0, pages: 0 });
  const [stats, setStats] = useState(emptyStats);
  const [listState, setListState] = useState({ loading: true, error: null });
  const [statsState, setStatsState] = useState({ loading: true, error: null });
  const [showAddModal, setShowAddModal] = useState(false);
  const [newLead, setNewLead] = useState(blankLead);
  const [creating, setCreating] = useState(false);
  const [listRefreshVersion, setListRefreshVersion] = useState(0);
  const [statsRefreshVersion, setStatsRefreshVersion] = useState(0);

  const closeAddModal = () => {
    if (!creating) setShowAddModal(false);
  };
  const addLeadDialogRef = useDialogFocus({ open: showAddModal, onClose: closeAddModal });

  useEffect(() => {
    const lease = identity.start();
    const actor = lease.principal;
    setLeads([]);
    setPagination({ page: 1, per_page: 20, total: 0, pages: 0 });
    if (!actor) {
      setListState({ loading: false, error: 'The active administrator identity is incomplete. CRM data was not requested.' });
      lease.finish();
      return () => lease.cancel();
    }
    setListState({ loading: true, error: null });
    crmService.loadLeads({
      expectedOwner: actor.owner,
      role: actor.role,
      signal: lease.signal,
      page,
      status: filters.status,
      source: filters.source,
      search: filters.search,
    })
      .then((result) => {
        if (!lease.isCurrent()) return;
        setLeads(result.leads);
        setPagination(result.pagination);
        setListState({ loading: false, error: null });
      })
      .catch((error) => {
        if (isAdminClosureCrmRequestCanceled(error) || !lease.isCurrent()) return;
        setLeads([]);
        setPagination({ page: 1, per_page: 20, total: 0, pages: 0 });
        setListState({ loading: false, error: adminClosureCrmError() });
      })
      .finally(() => lease.finish());
    return () => lease.cancel();
  }, [filters, identity, listRefreshVersion, page, principalKey]);

  useEffect(() => {
    const lease = identity.start();
    const actor = lease.principal;
    if (!actor) {
      setStats(emptyStats);
      setStatsState({ loading: false, error: 'CRM statistics were not requested without an active administrator identity.' });
      lease.finish();
      return () => lease.cancel();
    }
    setStats(emptyStats);
    setStatsState({ loading: true, error: null });
    crmService.loadStats({ expectedOwner: actor.owner, role: actor.role, signal: lease.signal })
      .then((result) => {
        if (!lease.isCurrent()) return;
        setStats(result.stats);
        setStatsState({ loading: false, error: null });
      })
      .catch((error) => {
        if (isAdminClosureCrmRequestCanceled(error) || !lease.isCurrent()) return;
        setStats(emptyStats);
        setStatsState({ loading: false, error: 'CRM statistics could not be verified and are unavailable.' });
      })
      .finally(() => lease.finish());
    return () => lease.cancel();
  }, [identity, principalKey, statsRefreshVersion]);

  const updateFilter = (key, value) => {
    setPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const applySearch = () => {
    setPage(1);
    setFilters((current) => ({ ...current, search: searchDraft }));
  };

  const resetFilters = () => {
    setPage(1);
    setSearchDraft('');
    setFilters({ status: null, source: null, search: '' });
  };

  const retryList = () => setListRefreshVersion((version) => version + 1);
  const retryStats = () => setStatsRefreshVersion((version) => version + 1);

  const handleCreateLead = async (event) => {
    event.preventDefault();
    if (creating) return;
    const lease = identity.start();
    const actor = lease.principal;
    if (!actor) {
      lease.finish();
      return;
    }
    setCreating(true);
    try {
      const result = await crmService.createLead({ expectedOwner: actor.owner, role: actor.role, payload: newLead, signal: lease.signal });
      if (!lease.isCurrent()) return;
      setShowAddModal(false);
      setNewLead(blankLead());
      toast.success(`Lead ${displayName(result.lead)} was saved.`);
      setPage(1);
      // Each follow-up effect owns a fresh AbortController. A filter/page change
      // cancels its list request, while an identity change cancels both requests.
      setListRefreshVersion((version) => version + 1);
      setStatsRefreshVersion((version) => version + 1);
    } catch (error) {
      if (lease.isCurrent() && !isAdminClosureCrmRequestCanceled(error)) toast.error(adminClosureCrmError());
    } finally {
      if (lease.isCurrent()) setCreating(false);
      lease.finish();
    }
  };

  const pipeline = useMemo(() => Object.fromEntries(
    ADMIN_CLOSURE_CRM_STATUSES.map((status) => [status, leads.filter((lead) => lead.status === status)]),
  ), [leads]);

  return (
    <AdminLayout>
      <section className="space-y-6 p-4 sm:p-6 lg:p-8" aria-labelledby="crm-heading">
        <div className="flex flex-col gap-4 border-b border-slate-700 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-medium uppercase tracking-[0.16em] text-cyan-300">Administration</p>
            <h1 id="crm-heading" className="mep-heading mt-1 text-3xl font-bold text-white">CRM leads</h1>
            <p className="mt-2 max-w-2xl text-slate-400">Review the tenant- and hierarchy-scoped lead records available to your active account.</p>
          </div>
          <button type="button" onClick={() => setShowAddModal(true)} disabled={!principal} className="mep-primary inline-flex items-center justify-center gap-2 px-5 py-3 font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-50">
            <Plus size={19} aria-hidden="true" /> Add lead
          </button>
        </div>

        <div aria-live="polite" className="sr-only">{listState.loading ? 'Loading leads' : listState.error || ''}</div>
        {statsState.error && <div role="status" className="flex flex-col gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-100 sm:flex-row sm:items-center sm:justify-between"><span>{statsState.error}</span><button type="button" onClick={retryStats} className="self-start rounded-lg border border-amber-300/60 px-3 py-2 text-sm font-semibold text-amber-100 hover:bg-amber-500/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 sm:self-auto">Retry statistics</button></div>}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5" aria-busy={statsState.loading}>
          <StatCard label="Total leads" value={stats.total} icon={Users} tint="bg-cyan-500/10 text-cyan-300" />
          <StatCard label="New" value={stats.new} icon={TrendingUp} tint="bg-blue-500/10 text-blue-300" />
          <StatCard label="Contacted" value={stats.contacted} icon={Activity} tint="bg-amber-500/10 text-amber-200" />
          <StatCard label="Qualified" value={stats.qualified} icon={Target} tint="bg-violet-500/10 text-violet-300" />
          <StatCard label="Converted" value={stats.converted} icon={DollarSign} tint="bg-emerald-500/10 text-emerald-300" />
        </div>

        <div className="mep-panel rounded-xl border p-4">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div className="flex gap-2" role="group" aria-label="Lead view">
              <button type="button" onClick={() => setView('table')} aria-pressed={view === 'table'} className={`rounded-lg px-4 py-2 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${view === 'table' ? 'bg-cyan-500 text-slate-950' : 'bg-slate-700 text-slate-100 hover:bg-slate-600'}`}>Table</button>
              <button type="button" onClick={() => setView('pipeline')} aria-pressed={view === 'pipeline'} className={`rounded-lg px-4 py-2 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${view === 'pipeline' ? 'bg-cyan-500 text-slate-950' : 'bg-slate-700 text-slate-100 hover:bg-slate-600'}`}>Pipeline</button>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="relative block text-sm text-slate-300">
                <span className="sr-only">Search leads</span>
                <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={17} aria-hidden="true" />
                <input value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="Search name, email, phone" className="w-full rounded-lg border border-slate-600 bg-slate-900 py-2 pl-9 pr-3 text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none" />
              </label>
              <label className="text-sm text-slate-300"><span className="sr-only">Lead status</span><select value={filters.status ?? ''} onChange={(event) => updateFilter('status', event.target.value || null)} className="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none"><option value="">All statuses</option>{ADMIN_CLOSURE_CRM_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
              <label className="text-sm text-slate-300"><span className="sr-only">Lead source</span><select value={filters.source ?? ''} onChange={(event) => updateFilter('source', event.target.value || null)} className="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none"><option value="">All sources</option>{ADMIN_CLOSURE_CRM_SOURCES.map((source) => <option key={source} value={source}>{source.replace('_', ' ')}</option>)}</select></label>
              <div className="flex gap-2 sm:col-span-3 sm:justify-end"><button type="button" onClick={applySearch} className="mep-primary px-4 py-2 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Apply search</button><button type="button" onClick={resetFilters} className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-semibold text-slate-100 hover:border-cyan-300 hover:bg-cyan-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Reset filters</button></div>
            </div>
          </div>
        </div>

        {listState.error ? (
          <div role="alert" className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-6 text-rose-100"><h2 className="mep-heading font-semibold">CRM leads are unavailable</h2><p className="mt-2 text-sm">{listState.error}</p><button type="button" onClick={retryList} className="mt-4 rounded-lg border border-rose-300/60 px-4 py-2 text-sm font-semibold text-rose-100 hover:bg-rose-500/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Retry lead list</button></div>
        ) : listState.loading ? (
          <div className="mep-panel flex min-h-56 items-center justify-center rounded-xl border" role="status"><div className="h-9 w-9 animate-spin rounded-full border-2 border-slate-600 border-t-cyan-300" aria-label="Loading leads" /></div>
        ) : leads.length === 0 ? (
          <div className="mep-panel rounded-xl border p-10 text-center"><h2 className="mep-heading text-lg font-semibold text-white">No matching leads</h2><p className="mt-2 text-sm text-slate-400">This is a verified empty result for the current filters and page.</p>{(filters.status || filters.source || filters.search) && <button type="button" onClick={resetFilters} className="mt-4 rounded-lg border border-cyan-400/60 px-4 py-2 text-sm font-semibold text-cyan-200 hover:bg-cyan-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">Clear filters</button>}</div>
        ) : view === 'table' ? (
          <div className="mep-panel overflow-hidden rounded-xl border"><div className="overflow-x-auto"><table className="min-w-[1000px] w-full text-left"><caption className="sr-only">Scoped CRM leads</caption><thead className="bg-slate-900/80 text-xs uppercase tracking-wide text-slate-400"><tr><th className="px-5 py-4">Lead</th><th className="px-5 py-4">Contact</th><th className="px-5 py-4">Status</th><th className="px-5 py-4">Source</th><th className="px-5 py-4">Score</th><th className="px-5 py-4">Budget</th><th className="px-5 py-4">Assigned to</th><th className="px-5 py-4">Follow-up</th></tr></thead><tbody className="divide-y divide-slate-700">{leads.map((lead) => <tr key={lead.id}  className="text-sm text-slate-200 transition hover:bg-cyan-500/5"><td className="px-5 py-4"><Link to={`/admin/crm/${lead.id}`} className="font-semibold text-white hover:text-cyan-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">{displayName(lead)}</Link><p className="mt-1 max-w-48 break-words text-xs text-slate-400">{lead.company ?? 'No company'}</p></td><td className="px-5 py-4"><p className="flex max-w-56 items-start gap-2 break-all"><Mail size={14} className="mt-0.5 shrink-0 text-cyan-300" aria-hidden="true" />{lead.email}</p>{lead.phone && <p className="mt-2 flex items-start gap-2 break-all text-slate-400"><Phone size={14} className="mt-0.5 shrink-0" aria-hidden="true" />{lead.phone}</p>}</td><td className="px-5 py-4"><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${statusColor(lead.status)}`}>{lead.status}</span></td><td className="px-5 py-4 capitalize text-slate-300">{lead.source.replace('_', ' ')}</td><td className={`px-5 py-4 font-semibold ${scoreColor(lead.score)}`}>{lead.score}</td><td className="px-5 py-4 whitespace-nowrap text-slate-200">{formatAdminClosureCrmBudget(lead.budget)}</td><td className="px-5 py-4 max-w-40 break-words text-slate-300">{lead.assigned_user?.name ?? 'Unassigned'}</td><td className="px-5 py-4 text-slate-300">{lead.next_follow_up ? <span className="flex items-center gap-2"><Calendar size={14} className="text-cyan-300" aria-hidden="true" />{lead.next_follow_up.slice(0, 10)}</span> : 'Not set'}</td></tr>)}</tbody></table></div></div>
        ) : (
          <div className="mep-panel overflow-x-auto rounded-xl border p-4"><div className="flex min-w-max gap-4">{ADMIN_CLOSURE_CRM_STATUSES.map((status) => <section key={status} className="mep-panel w-72 rounded-lg border p-3" aria-labelledby={`stage-${status}`}><div className="mb-3 flex items-center justify-between"><h2 id={`stage-${status}`} className="mep-heading font-semibold capitalize text-white">{status}</h2><span className="rounded-full bg-slate-700 px-2 py-0.5 text-xs text-slate-200">{pipeline[status].length}</span></div><div className="space-y-3">{pipeline[status].length === 0 ? <p className="p-3 text-sm text-slate-500">No leads on this page.</p> : pipeline[status].map((lead) => <button type="button" key={lead.id} onClick={() => navigate(`/admin/crm/${lead.id}`)} className="w-full rounded-lg border border-slate-700 bg-slate-800 p-3 text-left transition hover:border-cyan-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"><p className="font-semibold text-white">{displayName(lead)}</p><p className="mt-1 break-words text-xs text-slate-400">{lead.company ?? lead.email}</p><div className="mt-3 flex items-center justify-between border-t border-slate-700 pt-2 text-xs"><span className={scoreColor(lead.score)}>Score {lead.score}</span><span className="text-slate-300">{formatAdminClosureCrmBudget(lead.budget)}</span></div></button>)}</div></section>)}</div></div>
        )}

        {!listState.loading && !listState.error && pagination.pages > 0 && <nav className="flex flex-wrap items-center justify-between gap-3" aria-label="CRM list pages"><p className="text-sm text-slate-400">Page {pagination.page} of {pagination.pages} · {pagination.total} leads</p><div className="flex gap-2"><button type="button" disabled={pagination.page <= 1} onClick={() => setPage((current) => current - 1)} className="inline-flex items-center gap-1 rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:border-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"><ChevronLeft size={16} aria-hidden="true" />Previous</button><button type="button" disabled={pagination.page >= pagination.pages} onClick={() => setPage((current) => current + 1)} className="inline-flex items-center gap-1 rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:border-cyan-300 disabled:cursor-not-allowed disabled:opacity-50">Next<ChevronRight size={16} aria-hidden="true" /></button></div></nav>}
      </section>

      {showAddModal && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4" role="presentation"><div ref={addLeadDialogRef} role="dialog" aria-modal="true" aria-labelledby="add-lead-title" className="mep-panel max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border p-5 shadow-2xl sm:p-7"><div className="flex items-start justify-between gap-4"><div><h2 id="add-lead-title" className="mep-heading text-xl font-bold text-white">Add lead</h2><p className="mt-1 text-sm text-slate-400">The lead appears only after the server persists and validates the response.</p></div><button type="button" onClick={closeAddModal} aria-label="Close add lead dialog" className="rounded-lg p-2 text-slate-400 hover:bg-slate-700 hover:text-white disabled:opacity-50" disabled={creating}><X size={20} /></button></div><form onSubmit={handleCreateLead} className="mt-6 space-y-4"><div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium text-slate-200">First name<input data-autofocus required value={newLead.first_name} onChange={(event) => setNewLead((current) => ({ ...current, first_name: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none" /></label><label className="text-sm font-medium text-slate-200">Last name<input required value={newLead.last_name} onChange={(event) => setNewLead((current) => ({ ...current, last_name: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none" /></label></div><label className="block text-sm font-medium text-slate-200">Email<input required type="email" value={newLead.email} onChange={(event) => setNewLead((current) => ({ ...current, email: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none" /></label><div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium text-slate-200">Phone<input type="tel" value={newLead.phone} onChange={(event) => setNewLead((current) => ({ ...current, phone: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none" /></label><label className="text-sm font-medium text-slate-200">Company<input value={newLead.company} onChange={(event) => setNewLead((current) => ({ ...current, company: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none" /></label></div><div className="grid gap-4 sm:grid-cols-3"><label className="text-sm font-medium text-slate-200">Status<select value={newLead.status} onChange={(event) => setNewLead((current) => ({ ...current, status: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none">{ADMIN_CLOSURE_CRM_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}</select></label><label className="text-sm font-medium text-slate-200">Source<select value={newLead.source} onChange={(event) => setNewLead((current) => ({ ...current, source: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none">{ADMIN_CLOSURE_CRM_SOURCES.map((source) => <option key={source} value={source}>{source.replace('_', ' ')}</option>)}</select></label><label className="text-sm font-medium text-slate-200">Budget<input inputMode="decimal" value={newLead.budget} onChange={(event) => setNewLead((current) => ({ ...current, budget: event.target.value }))} placeholder="Exact decimal" className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none" /></label></div><div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end"><button type="button" onClick={closeAddModal} disabled={creating} className="rounded-lg border border-slate-600 px-4 py-2 font-semibold text-slate-100 hover:bg-slate-700 disabled:opacity-50">Cancel</button><button type="submit" disabled={creating} className="mep-primary px-4 py-2 font-semibold disabled:cursor-not-allowed disabled:opacity-50">{creating ? 'Saving…' : 'Save lead'}</button></div></form></div></div>}
    </AdminLayout>
  );
}
