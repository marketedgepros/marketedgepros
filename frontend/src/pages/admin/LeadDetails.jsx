import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Activity, ArrowLeft, Calendar, CheckCircle, Edit3, Mail, MapPin, MessageSquare, Phone, Plus, Save, Send, ShieldAlert, Trash2, X } from 'lucide-react';
import { useToast } from '../../contexts/ToastContext';
import useAdminClosureCrmIdentityGuard from '../../hooks/useAdminClosureCrmIdentityGuard';
import useDialogFocus from '../../hooks/useDialogFocus';
import useAuthStore from '../../store/authStore';
import {
  ADMIN_CLOSURE_CRM_STATUSES,
  adminClosureCrmError,
  adminClosureCrmPrincipalFromAuth,
  createAdminClosureCrmService,
  formatAdminClosureCrmBudget,
  isAdminClosureCrmRequestCanceled,
  parseAdminClosureCrmRouteLeadId,
} from '../../services/adminClosureCrmService';

const crmService = createAdminClosureCrmService();
const displayName = (lead) => `${lead.first_name} ${lead.last_name}`;
const formatDate = (value, includeTime = false) => {
  if (!value) return 'Not recorded';
  const date = new Date(`${value}Z`);
  return Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleString(undefined, includeTime ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' });
};
const localToNaiveIso = (value) => (value.length === 16 ? `${value}:00` : value);
const statusColor = (status) => ({
  new: 'bg-blue-500/15 text-blue-200 border-blue-400/30', contacted: 'bg-amber-500/15 text-amber-200 border-amber-400/30', qualified: 'bg-violet-500/15 text-violet-200 border-violet-400/30', proposal: 'bg-cyan-500/15 text-cyan-200 border-cyan-400/30', negotiation: 'bg-orange-500/15 text-orange-200 border-orange-400/30', converted: 'bg-emerald-500/15 text-emerald-200 border-emerald-400/30', lost: 'bg-rose-500/15 text-rose-200 border-rose-400/30',
}[status] || 'bg-slate-600 text-slate-100 border-slate-500');

const formFromLead = (lead) => ({
  status: lead.status,
  score: lead.score,
  budget: lead.budget ?? '',
  notes: lead.notes ?? '',
  next_follow_up: lead.next_follow_up ?? '',
});

export default function LeadDetails() {
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const principal = useMemo(() => adminClosureCrmPrincipalFromAuth(user, isAuthenticated), [user, isAuthenticated]);
  const identity = useAdminClosureCrmIdentityGuard(principal);

  return <LeadDetailsContent key={principal?.key ?? 'missing-principal'} principal={principal} identity={identity} />;
}

function LeadDetailsContent({ principal, identity }) {
  const { id: rawId } = useParams();
  const id = parseAdminClosureCrmRouteLeadId(rawId);
  const navigate = useNavigate();
  const toast = useToast();
  const principalKey = principal?.key ?? null;
  const [lead, setLead] = useState(null);
  const [notes, setNotes] = useState([]);
  const [activities, setActivities] = useState([]);
  const [detailState, setDetailState] = useState({ loading: true, error: null });
  const [notesState, setNotesState] = useState({ loading: true, error: null });
  const [activitiesState, setActivitiesState] = useState({ loading: true, error: null });
  const [activeTab, setActiveTab] = useState('overview');
  const [newNote, setNewNote] = useState('');
  const [showEdit, setShowEdit] = useState(false);
  const [showActivity, setShowActivity] = useState(false);
  const [form, setForm] = useState(null);
  const [activityForm, setActivityForm] = useState({ scheduled_at: '', description: '' });
  const [saving, setSaving] = useState(false);

  const closeEditDialog = () => {
    if (!saving) setShowEdit(false);
  };
  const closeActivityDialog = () => {
    if (!saving) setShowActivity(false);
  };
  const editDialogRef = useDialogFocus({ open: showEdit, onClose: closeEditDialog });
  const activityDialogRef = useDialogFocus({ open: showActivity, onClose: closeActivityDialog });

  useEffect(() => {
    const lease = identity.start();
    const actor = lease.principal;
    setLead(null);
    setNotes([]);
    setActivities([]);
    if (!actor || id === null) {
      setDetailState({ loading: false, error: id === null
        ? 'The lead route identifier is invalid. Lead data was not requested.'
        : 'The active administrator identity is incomplete. Lead data was not requested.' });
      setNotesState({ loading: false, error: 'Notes were not requested.' });
      setActivitiesState({ loading: false, error: 'Activities were not requested.' });
      lease.finish();
      return () => lease.cancel();
    }
    setDetailState({ loading: true, error: null });
    setNotesState({ loading: true, error: null });
    setActivitiesState({ loading: true, error: null });
    const request = { expectedOwner: actor.owner, role: actor.role, leadId: id, signal: lease.signal };
    const requests = [
      crmService.loadLead(request).then((result) => {
        if (!lease.isCurrent()) return;
        setLead(result.lead);
        setForm(formFromLead(result.lead));
        setDetailState({ loading: false, error: null });
      }).catch((error) => {
        if (isAdminClosureCrmRequestCanceled(error) || !lease.isCurrent()) return;
        setLead(null);
        setDetailState({ loading: false, error: adminClosureCrmError() });
      }),
      crmService.loadNotes(request).then((result) => {
        if (!lease.isCurrent()) return;
        setNotes(result.notes);
        setNotesState({ loading: false, error: null });
      }).catch((error) => {
        if (isAdminClosureCrmRequestCanceled(error) || !lease.isCurrent()) return;
        setNotes([]);
        setNotesState({ loading: false, error: 'Notes could not be verified and are unavailable.' });
      }),
      crmService.loadActivities(request).then((result) => {
        if (!lease.isCurrent()) return;
        setActivities(result.activities);
        setActivitiesState({ loading: false, error: null });
      }).catch((error) => {
        if (isAdminClosureCrmRequestCanceled(error) || !lease.isCurrent()) return;
        setActivities([]);
        setActivitiesState({ loading: false, error: 'Activities could not be verified and are unavailable.' });
      }),
    ];
    Promise.allSettled(requests).finally(() => lease.finish());
    return () => lease.cancel();
  }, [id, identity, principalKey]);

  const applyPersistedLead = (nextLead, lease) => {
    if (!lease.isCurrent()) return;
    setLead(nextLead);
    setForm(formFromLead(nextLead));
  };

  const refreshNotes = async () => {
    if (!lead) return;
    const lease = identity.start();
    const actor = lease.principal;
    if (!actor) {
      lease.finish();
      return;
    }
    setNotesState({ loading: true, error: null });
    try {
      const result = await crmService.loadNotes({ expectedOwner: actor.owner, role: actor.role, leadId: lead.id, signal: lease.signal });
      if (!lease.isCurrent()) return;
      setNotes(result.notes);
      setNotesState({ loading: false, error: null });
    } catch (error) {
      if (isAdminClosureCrmRequestCanceled(error) || !lease.isCurrent()) return;
      setNotes([]);
      setNotesState({ loading: false, error: 'Notes could not be verified and are unavailable.' });
    } finally {
      lease.finish();
    }
  };
  const refreshActivities = async () => {
    if (!lead) return;
    const lease = identity.start();
    const actor = lease.principal;
    if (!actor) {
      lease.finish();
      return;
    }
    setActivitiesState({ loading: true, error: null });
    try {
      const result = await crmService.loadActivities({ expectedOwner: actor.owner, role: actor.role, leadId: lead.id, signal: lease.signal });
      if (!lease.isCurrent()) return;
      setActivities(result.activities);
      setActivitiesState({ loading: false, error: null });
    } catch (error) {
      if (isAdminClosureCrmRequestCanceled(error) || !lease.isCurrent()) return;
      setActivities([]);
      setActivitiesState({ loading: false, error: 'Activities could not be verified and are unavailable.' });
    } finally {
      lease.finish();
    }
  };

  const withMutation = async (action, onSuccess) => {
    if (!lead || saving) return;
    const lease = identity.start();
    if (!lease.principal) {
      lease.finish();
      return;
    }
    setSaving(true);
    try {
      const result = await action(lease);
      if (!lease.isCurrent()) return;
      await onSuccess(result, lease);
    } catch (error) {
      if (isAdminClosureCrmRequestCanceled(error) || !lease.isCurrent()) return;
      if (error?.response?.status === 409) toast.warning('This lead changed elsewhere. Reload it before saving again.');
      else toast.error(adminClosureCrmError());
    } finally {
      if (lease.isCurrent()) setSaving(false);
      lease.finish();
    }
  };

  const saveStatus = (status) => withMutation(
    (lease) => crmService.updateLead({ expectedOwner: lease.principal.owner, role: lease.principal.role, leadId: lead.id, payload: { status, expected_updated_at: lead.updated_at }, signal: lease.signal }),
    async (result, lease) => { applyPersistedLead(result.lead, lease); if (!lease.isCurrent()) return; toast.success(`Status saved as ${result.lead.status}.`); await refreshActivities(); },
  );

  const saveEdit = () => withMutation(
    (lease) => crmService.updateLead({
      expectedOwner: lease.principal.owner, role: lease.principal.role, leadId: lead.id,
      payload: { ...form, budget: form.budget === '' ? null : form.budget, notes: form.notes === '' ? null : form.notes, next_follow_up: form.next_follow_up === '' ? null : localToNaiveIso(form.next_follow_up), expected_updated_at: lead.updated_at },
      signal: lease.signal,
    }),
    async (result, lease) => { applyPersistedLead(result.lead, lease); if (!lease.isCurrent()) return; setShowEdit(false); toast.success('Lead changes were saved.'); await refreshActivities(); },
  );

  const addNote = () => withMutation(
    (lease) => crmService.addNote({ expectedOwner: lease.principal.owner, role: lease.principal.role, leadId: lead.id, content: newNote, signal: lease.signal }),
    async (result, lease) => { if (!lease.isCurrent()) return; setNewNote(''); setNotes((current) => [result.note, ...current]); toast.success('Note was saved.'); await refreshActivities(); },
  );

  const addFollowUp = () => withMutation(
    (lease) => crmService.addActivity({ expectedOwner: lease.principal.owner, role: lease.principal.role, leadId: lead.id, payload: { activity_type: 'follow_up', description: activityForm.description, scheduled_at: localToNaiveIso(activityForm.scheduled_at) }, signal: lease.signal }),
    async (result, lease) => { if (!lease.isCurrent()) return; setShowActivity(false); setActivityForm({ scheduled_at: '', description: '' }); setActivities((current) => [result.activity, ...current]); toast.success('Follow-up activity was saved.'); },
  );

  const markConverted = () => withMutation(
    (lease) => crmService.markConverted({ expectedOwner: lease.principal.owner, role: lease.principal.role, leadId: lead.id, signal: lease.signal }),
    async (result, lease) => { applyPersistedLead(result.lead, lease); if (!lease.isCurrent()) return; toast.success('Lead status was set to converted. No user account was created.'); await refreshActivities(); },
  );

  const deleteLead = () => {
    if (!window.confirm('Delete this lead record? This cannot be undone.')) return;
    withMutation(
      (lease) => crmService.deleteLead({ expectedOwner: lease.principal.owner, role: lease.principal.role, leadId: lead.id, signal: lease.signal }),
      async (_result, lease) => { if (!lease.isCurrent()) return; toast.success('Lead was deleted.'); navigate('/admin/crm'); },
    );
  };

  if (detailState.loading) {
    return <div className="flex min-h-64 items-center justify-center p-8" role="status"><div className="h-10 w-10 animate-spin rounded-full border-2 border-slate-600 border-t-cyan-300" aria-label="Loading lead" /></div>;
  }
  if (detailState.error || !lead) {
    return <section className="mx-auto max-w-2xl p-6 sm:p-10" aria-labelledby="lead-unavailable"><div role="alert" className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-6 text-rose-100"><ShieldAlert className="mb-3 text-rose-300" aria-hidden="true" /><h1 id="lead-unavailable" className="mep-heading text-xl font-bold">Lead details are unavailable</h1><p className="mt-2 text-sm">{detailState.error || adminClosureCrmError()}</p><button type="button" onClick={() => navigate('/admin/crm')} className="mt-5 inline-flex items-center gap-2 rounded-lg bg-slate-800 px-4 py-2 font-semibold text-white hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"><ArrowLeft size={17} aria-hidden="true" /> Back to CRM</button></div></section>;
  }

  return (
    <>
      <section className="space-y-6 p-4 sm:p-6 lg:p-8" aria-labelledby="lead-heading">
        <div className="flex flex-col gap-4 border-b border-slate-700 pb-6 sm:flex-row sm:items-center sm:justify-between"><button type="button" onClick={() => navigate('/admin/crm')} className="inline-flex items-center gap-2 self-start rounded-lg px-3 py-2 text-sm font-semibold text-slate-300 hover:bg-slate-700 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"><ArrowLeft size={17} aria-hidden="true" /> Back to CRM</button><div className="flex flex-wrap gap-2"><button type="button" onClick={() => setShowEdit(true)} disabled={saving} className="mep-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold disabled:opacity-50"><Edit3 size={16} aria-hidden="true" /> Edit supported fields</button>{principal?.role === 'supermaster' && <button type="button" onClick={deleteLead} disabled={saving} className="inline-flex items-center gap-2 rounded-lg border border-rose-400/50 px-4 py-2 text-sm font-semibold text-rose-200 hover:bg-rose-500/10 disabled:opacity-50"><Trash2 size={16} aria-hidden="true" /> Delete</button>}</div></div>

        <header className="rounded-xl border border-slate-700 bg-slate-800/75 p-5 sm:p-6"><div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between"><div className="flex min-w-0 items-center gap-4"><div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-cyan-500 to-blue-600 text-xl font-bold text-slate-950" aria-hidden="true">{lead.first_name.charAt(0).toUpperCase()}</div><div className="min-w-0"><p className="text-sm font-medium uppercase tracking-[0.14em] text-cyan-300">CRM lead</p><h1 id="lead-heading" className="mep-heading mt-1 break-words text-2xl font-bold text-white">{displayName(lead)}</h1><p className="mt-1 break-words text-slate-400">{lead.company ?? 'No company recorded'}</p></div></div><div className="flex items-center gap-4"><span className={`rounded-full border px-3 py-1.5 text-sm font-semibold capitalize ${statusColor(lead.status)}`}>{lead.status}</span><div className="text-right"><p className="text-xs uppercase tracking-wide text-slate-400">Score</p><p className="text-2xl font-bold text-white">{lead.score}</p></div></div></div></header>

        <div className="flex overflow-x-auto border-b border-slate-700" role="tablist" aria-label="Lead information"><button type="button" role="tab" aria-selected={activeTab === 'overview'} onClick={() => setActiveTab('overview')} className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${activeTab === 'overview' ? 'border-cyan-300 text-cyan-200' : 'border-transparent text-slate-400 hover:text-white'}`}>Overview</button><button type="button" role="tab" aria-selected={activeTab === 'notes'} onClick={() => setActiveTab('notes')} className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${activeTab === 'notes' ? 'border-cyan-300 text-cyan-200' : 'border-transparent text-slate-400 hover:text-white'}`}>Notes ({notesState.error ? 'unavailable' : notes.length})</button><button type="button" role="tab" aria-selected={activeTab === 'activity'} onClick={() => setActiveTab('activity')} className={`whitespace-nowrap border-b-2 px-4 py-3 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${activeTab === 'activity' ? 'border-cyan-300 text-cyan-200' : 'border-transparent text-slate-400 hover:text-white'}`}>Activity ({activitiesState.error ? 'unavailable' : activities.length})</button></div>

        {activeTab === 'overview' && <div className="grid gap-6 lg:grid-cols-3"><div className="space-y-6 lg:col-span-2"><section className="mep-panel rounded-xl border p-5"><h2 className="mep-heading text-lg font-bold text-white">Contact information</h2><dl className="mt-4 grid gap-4 sm:grid-cols-2"><div className="flex gap-3"><Mail className="mt-0.5 shrink-0 text-cyan-300" size={18} aria-hidden="true" /><div><dt className="text-xs uppercase tracking-wide text-slate-400">Email</dt><dd className="mt-1 break-all text-slate-100">{lead.email}</dd></div></div><div className="flex gap-3"><Phone className="mt-0.5 shrink-0 text-cyan-300" size={18} aria-hidden="true" /><div><dt className="text-xs uppercase tracking-wide text-slate-400">Phone</dt><dd className="mt-1 break-all text-slate-100">{lead.phone ?? 'Not recorded'}</dd></div></div><div className="flex gap-3 sm:col-span-2"><MapPin className="mt-0.5 shrink-0 text-cyan-300" size={18} aria-hidden="true" /><div><dt className="text-xs uppercase tracking-wide text-slate-400">Country</dt><dd className="mt-1 text-slate-100">{lead.country_code ?? 'Not recorded'}</dd></div></div></dl></section><section className="mep-panel rounded-xl border p-5"><h2 className="mep-heading text-lg font-bold text-white">Lead details</h2><dl className="mt-4 grid gap-4 sm:grid-cols-2"><div><dt className="text-xs uppercase tracking-wide text-slate-400">Source</dt><dd className="mt-1 capitalize text-white">{lead.source.replace('_', ' ')}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-400">Budget</dt><dd className="mt-1 text-white">{formatAdminClosureCrmBudget(lead.budget)}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-400">Assigned to</dt><dd className="mt-1 text-white">{lead.assigned_user?.name ?? 'Unassigned'}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-400">Next follow-up</dt><dd className="mt-1 text-white">{formatDate(lead.next_follow_up, true)}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-400">Created</dt><dd className="mt-1 text-white">{formatDate(lead.created_at, true)}</dd></div><div><dt className="text-xs uppercase tracking-wide text-slate-400">Last saved</dt><dd className="mt-1 text-white">{formatDate(lead.updated_at, true)}</dd></div></dl>{lead.notes && <div className="mt-5 border-t border-slate-700 pt-4"><h3 className="text-sm font-semibold text-slate-200">Record notes</h3><p className="mt-2 whitespace-pre-wrap break-words text-sm text-slate-300">{lead.notes}</p></div>}</section></div><aside className="space-y-6"><section className="mep-panel rounded-xl border p-5"><h2 className="mep-heading text-lg font-bold text-white">Actions</h2><div className="mt-4 space-y-2"><button type="button" onClick={() => { if (lead.email) window.location.href = `mailto:${lead.email}`; }} disabled={!lead.email} className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-600 px-3 py-2 text-sm font-semibold text-slate-100 hover:border-cyan-300 hover:bg-cyan-500/10 disabled:cursor-not-allowed disabled:opacity-50"><Send size={16} aria-hidden="true" /> Open email client</button><button type="button" onClick={() => setShowActivity(true)} disabled={saving} className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-600 px-3 py-2 text-sm font-semibold text-slate-100 hover:border-cyan-300 hover:bg-cyan-500/10 disabled:opacity-50"><Calendar size={16} aria-hidden="true" /> Add follow-up activity</button><button type="button" onClick={markConverted} disabled={saving || lead.status === 'converted'} className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-500/90 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"><CheckCircle size={16} aria-hidden="true" /> Mark converted</button><p className="pt-1 text-xs leading-5 text-slate-400">Marking converted changes only this lead status. It does not create a customer account or send an email.</p></div></section><section className="mep-panel rounded-xl border p-5"><h2 className="mep-heading text-lg font-bold text-white">Change status</h2><div className="mt-4 grid grid-cols-2 gap-2">{ADMIN_CLOSURE_CRM_STATUSES.map((status) => <button type="button" key={status} onClick={() => saveStatus(status)} disabled={saving || lead.status === status} className={`rounded-lg border px-2 py-2 text-sm font-semibold capitalize transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 ${statusColor(status)}`}>{status}</button>)}</div></section></aside></div>}

        {activeTab === 'notes' && <section className="mep-panel rounded-xl border p-5"><h2 className="mep-heading text-lg font-bold text-white">Notes</h2>{notesState.error ? <div role="alert" className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-100">{notesState.error}</div> : <><div className="mt-5"><label htmlFor="lead-note" className="text-sm font-semibold text-slate-200">Add a note</label><textarea id="lead-note" value={newNote} onChange={(event) => setNewNote(event.target.value)} rows={4} maxLength={10000} placeholder="Record an internal CRM note" className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none" /><button type="button" onClick={addNote} disabled={saving || !newNote.trim()} className="mep-primary mt-3 inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"><Plus size={16} aria-hidden="true" /> Save note</button></div>{notesState.loading ? <p className="mt-6 text-sm text-slate-400">Loading notes…</p> : notes.length === 0 ? <p className="mt-6 rounded-lg border border-dashed border-slate-600 p-5 text-center text-sm text-slate-400">No persisted notes are available for this lead.</p> : <ol className="mt-6 space-y-3">{notes.map((note) => <li key={note.id} className="rounded-lg border border-slate-700 bg-slate-900/70 p-4"><p className="whitespace-pre-wrap break-words text-slate-100">{note.content}</p><p className="mt-3 text-xs text-slate-400">{note.created_by?.name ?? 'Unknown scoped user'} · {formatDate(note.created_at, true)}</p></li>)}</ol>}</>}</section>}

        {activeTab === 'activity' && <section className="mep-panel rounded-xl border p-5"><h2 className="mep-heading text-lg font-bold text-white">Activity history</h2><p className="mt-1 text-sm text-slate-400">Only persisted internal CRM activity is shown; no provider email or reminder event is implied.</p>{activitiesState.error ? <div role="alert" className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-100">{activitiesState.error}</div> : activitiesState.loading ? <p className="mt-6 text-sm text-slate-400">Loading activities…</p> : activities.length === 0 ? <p className="mt-6 rounded-lg border border-dashed border-slate-600 p-5 text-center text-sm text-slate-400">No persisted activity is available for this lead.</p> : <ol className="mt-5 space-y-3">{activities.map((activity) => <li key={activity.id} className="flex gap-3 rounded-lg border border-slate-700 bg-slate-900/70 p-4"><Activity className="mt-0.5 shrink-0 text-cyan-300" size={18} aria-hidden="true" /><div className="min-w-0"><p className="font-semibold capitalize text-white">{activity.activity_type.replace('_', ' ')}</p>{activity.subject && <p className="mt-1 break-words text-sm text-slate-200">{activity.subject}</p>}{activity.description && <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-300">{activity.description}</p>}<p className="mt-3 text-xs text-slate-400">{activity.created_by?.name ?? 'Unknown scoped user'} · {formatDate(activity.created_at, true)}{activity.scheduled_at ? ` · Recorded for ${formatDate(activity.scheduled_at, true)}` : ''}</p></div></li>)}</ol>}</section>}
      </section>

      {showEdit && form && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4"><div ref={editDialogRef} role="dialog" aria-modal="true" aria-labelledby="edit-lead-title" className="mep-panel max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border p-5 shadow-2xl sm:p-7"><div className="flex items-start justify-between gap-4"><div><h2 id="edit-lead-title" className="mep-heading text-xl font-bold text-white">Edit supported lead fields</h2><p className="mt-1 text-sm text-slate-400">Contact identity fields are not editable through this CRM route. Saving uses the version currently shown on this lead.</p></div><button type="button" onClick={closeEditDialog} aria-label="Close edit lead dialog" disabled={saving} className="rounded-lg p-2 text-slate-400 hover:bg-slate-700 hover:text-white"><X size={20} /></button></div><div className="mt-6 grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium text-slate-200">Status<select data-autofocus value={form.status} onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none">{ADMIN_CLOSURE_CRM_STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}</select></label><label className="text-sm font-medium text-slate-200">Score (0–100)<input type="number" min="0" max="100" value={form.score} onChange={(event) => setForm((current) => ({ ...current, score: Number(event.target.value) }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none" /></label><label className="text-sm font-medium text-slate-200">Budget<input inputMode="decimal" value={form.budget} onChange={(event) => setForm((current) => ({ ...current, budget: event.target.value }))} placeholder="Exact decimal or empty" className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none" /></label><label className="text-sm font-medium text-slate-200">Next follow-up record<input type="datetime-local" value={form.next_follow_up ? form.next_follow_up.slice(0, 16) : ''} onChange={(event) => setForm((current) => ({ ...current, next_follow_up: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none" /></label><label className="sm:col-span-2 text-sm font-medium text-slate-200">Internal record notes<textarea value={form.notes} onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))} rows={4} maxLength={10000} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none" /></label></div><div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end"><button type="button" onClick={closeEditDialog} disabled={saving} className="rounded-lg border border-slate-600 px-4 py-2 font-semibold text-slate-100 hover:bg-slate-700 disabled:opacity-50">Cancel</button><button type="button" onClick={saveEdit} disabled={saving} className="mep-primary inline-flex items-center justify-center gap-2 px-4 py-2 font-semibold disabled:opacity-50"><Save size={16} aria-hidden="true" /> {saving ? 'Saving…' : 'Save changes'}</button></div></div></div>}

      {showActivity && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/75 p-4"><div ref={activityDialogRef} role="dialog" aria-modal="true" aria-labelledby="activity-title" className="mep-panel max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border p-5 shadow-2xl sm:p-7"><div className="flex items-start justify-between gap-4"><div><h2 id="activity-title" className="mep-heading text-xl font-bold text-white">Add follow-up activity</h2><p className="mt-1 text-sm text-slate-400">This records CRM activity only. It does not schedule a provider reminder.</p></div><button type="button" onClick={closeActivityDialog} aria-label="Close add activity dialog" disabled={saving} className="rounded-lg p-2 text-slate-400 hover:bg-slate-700 hover:text-white"><X size={20} /></button></div><label className="mt-5 block text-sm font-medium text-slate-200">Activity date and time<input data-autofocus required type="datetime-local" value={activityForm.scheduled_at} onChange={(event) => setActivityForm((current) => ({ ...current, scheduled_at: event.target.value }))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white focus:border-cyan-400 focus:outline-none" /></label><label className="mt-4 block text-sm font-medium text-slate-200">Description<textarea value={activityForm.description} onChange={(event) => setActivityForm((current) => ({ ...current, description: event.target.value }))} rows={3} maxLength={10000} placeholder="Internal follow-up context" className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-white placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none" /></label><div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end"><button type="button" onClick={closeActivityDialog} disabled={saving} className="rounded-lg border border-slate-600 px-4 py-2 font-semibold text-slate-100 hover:bg-slate-700 disabled:opacity-50">Cancel</button><button type="button" onClick={addFollowUp} disabled={saving || !activityForm.scheduled_at} className="mep-primary inline-flex items-center justify-center gap-2 px-4 py-2 font-semibold disabled:opacity-50"><MessageSquare size={16} aria-hidden="true" /> {saving ? 'Saving…' : 'Save activity'}</button></div></div></div>}
    </>
  );
}
