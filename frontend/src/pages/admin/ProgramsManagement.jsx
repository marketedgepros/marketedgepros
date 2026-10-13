import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Edit2, Eye, LoaderCircle, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import useAuthStore from '../../store/authStore.js';
import useDialogFocus from '../../hooks/useDialogFocus.js';
import {
  AdminProgramsContractError,
  adminProgramsPrincipalFromAuth,
  deleteAdminProgram,
  isAdminProgramsRequestCanceled,
  loadAdminPrograms,
  saveAdminProgram,
} from '../../services/adminClosureProgramsService.js';

const emptyDraft = () => ({
  name: '',
  type: '',
  description: '',
  accountSize: '',
  profitTarget: '',
  maxDailyLoss: '',
  maxTotalLoss: '',
  price: '',
  profitSplit: '',
  profitSplitPercentage: '',
  minimumPayoutAmount: '',
  payoutMode: '',
  rules: '{}',
  isActive: true,
});

export const programDraft = (program) => ({
  name: program.name,
  type: program.type,
  description: program.description ?? '',
  accountSize: program.accountSize,
  profitTarget: program.profitTarget ?? '',
  maxDailyLoss: program.maxDailyLoss ?? '',
  maxTotalLoss: program.maxTotalLoss ?? '',
  price: program.price,
  profitSplit: program.profitSplit ?? '',
  profitSplitPercentage: program.profitSplitPercentage ?? '',
  minimumPayoutAmount: program.minimumPayoutAmount ?? '',
  payoutMode: program.payoutMode ?? '',
  rules: JSON.stringify(program.rules, null, 2),
  isActive: program.isActive,
});

/** Never apply a completed read/write after its principal generation has changed. */
export const isCurrentProgramsOperation = (generation, currentGeneration, signal) => (
  generation === currentGeneration && !signal?.aborted
);

const errorMessage = (error, fallback) => {
  if (error instanceof AdminProgramsContractError) return error.message;
  const message = error?.response?.data?.error || error?.response?.data?.message || error?.message;
  return typeof message === 'string' && message ? message : fallback;
};

const displayOptional = (value) => (value === null ? 'Not recorded' : value);

function ProgramReadState({ state, error, onRetry }) {
  if (state === 'loading') {
    return (
      <div className="mep-panel rounded-xl border p-8 text-center" role="status" aria-live="polite" aria-busy="true">
        <LoaderCircle className="mx-auto h-7 w-7 animate-spin text-cyan-300" aria-hidden="true" />
        <p className="mt-3 text-sm text-slate-200">Loading the persisted program catalog…</p>
      </div>
    );
  }
  if (state === 'error') {
    return (
      <div className="rounded-xl border border-rose-400/50 bg-rose-950/30 p-6 text-rose-100" role="alert">
        <h2 className="mep-heading font-semibold">Program catalog unavailable</h2>
        <p className="mt-1 break-words text-sm text-rose-100/90">{error}</p>
        <button type="button" onClick={onRetry} className="mt-4 rounded-md border border-rose-300/60 px-3 py-2 text-sm font-medium hover:bg-rose-900/40 focus:outline-none focus:ring-2 focus:ring-cyan-300">
          Retry catalog request
        </button>
      </div>
    );
  }
  return null;
}

function ProgramFields({ draft, onChange, readOnly, requireStorageFields }) {
  const textField = (name, label, { required = false, hint = null, mono = false } = {}) => (
    <div key={name}>
      <label className="mb-1 block text-sm font-medium text-slate-100" htmlFor={`program-${name}`}>
        {label}{required ? <span className="text-cyan-300"> (required)</span> : null}
      </label>
      <input
        id={`program-${name}`}
        name={name}
        type="text"
        value={draft[name]}
        onChange={onChange}
        readOnly={readOnly}
        required={required}
        aria-describedby={hint ? `program-${name}-hint` : undefined}
        className={`w-full rounded-md border border-slate-600 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/40 ${mono ? 'font-mono' : ''} ${readOnly ? 'cursor-default text-slate-300' : ''}`}
      />
      {hint ? <p id={`program-${name}-hint`} className="mt-1 text-xs text-slate-400">{hint}</p> : null}
    </div>
  );

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {textField('name', 'Program name', { required: true })}
      {textField('type', 'Stored type', { required: true, hint: 'An ASCII label stored by the catalog; no phase type is assumed.' })}
      <div className="md:col-span-2">
        <label className="mb-1 block text-sm font-medium text-slate-100" htmlFor="program-description">Description</label>
        <textarea
          id="program-description"
          name="description"
          value={draft.description}
          onChange={onChange}
          readOnly={readOnly}
          rows="3"
          className="w-full rounded-md border border-slate-600 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/40"
        />
      </div>
      {textField('accountSize', 'Account size', { required: true, mono: true, hint: 'Exact positive decimal, for example 10000.00.' })}
      {textField('price', 'Price', { required: true, mono: true, hint: 'Exact positive decimal. Currency policy is not edited here.' })}
      {textField('profitTarget', 'Profit target', { required: requireStorageFields, mono: true, hint: 'Exact decimal from 0.00 to 100.00; required by the current storage schema on create.' })}
      {textField('maxDailyLoss', 'Maximum daily loss', { required: requireStorageFields, mono: true, hint: 'Exact decimal from 0.00 to 100.00; required by the current storage schema on create.' })}
      {textField('maxTotalLoss', 'Maximum total loss', { required: requireStorageFields, mono: true, hint: 'Exact decimal from 0.00 to 100.00; required by the current storage schema on create.' })}
      {textField('profitSplit', 'Profit split', { required: requireStorageFields, mono: true, hint: 'Exact decimal from 0.00 to 100.00; required by the current storage schema on create.' })}
      {textField('profitSplitPercentage', 'Profit split percentage alias', { mono: true, hint: 'Optional persisted compatibility field, 0.00 to 100.00.' })}
      {textField('minimumPayoutAmount', 'Minimum payout amount', { mono: true, hint: 'Optional exact non-negative decimal.' })}
      {textField('payoutMode', 'Payout mode', { hint: 'Optional persisted ASCII label; no mode is inferred.' })}
      <div className="md:col-span-2">
        <label className="mb-1 block text-sm font-medium text-slate-100" htmlFor="program-rules">Rules JSON object</label>
        <textarea
          id="program-rules"
          name="rules"
          value={draft.rules}
          onChange={onChange}
          readOnly={readOnly}
          spellCheck="false"
          rows="8"
          aria-describedby="program-rules-hint"
          className="min-h-36 w-full rounded-md border border-slate-600 bg-slate-950 px-3 py-2 font-mono text-sm text-slate-100 outline-none focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/40"
        />
        <p id="program-rules-hint" className="mt-1 text-xs text-slate-400">Must remain a JSON object. Existing rule vocabulary is preserved rather than interpreted.</p>
      </div>
      <label className="flex items-center gap-3 rounded-md border border-slate-700 bg-slate-950/60 px-3 py-3 text-sm text-slate-100 md:col-span-2">
        <input
          type="checkbox"
          name="isActive"
          checked={draft.isActive}
          onChange={onChange}
          disabled={readOnly}
          className="h-4 w-4 rounded border-slate-500 text-cyan-500 focus:ring-cyan-300"
        />
        Catalog active
      </label>
    </div>
  );
}

function ProgramEditor({ editor, pending, error, onClose, onSave, onChange }) {
  const dialogRef = useDialogFocus({ open: Boolean(editor), onClose });
  if (!editor) return null;
  const isView = editor.mode === 'view';
  const title = isView ? 'Program record' : editor.program ? 'Edit persisted program' : 'Create persisted program';
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/85 p-4" role="presentation">
      <section ref={dialogRef} className="mep-panel max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-xl border shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="program-editor-title">
        <header className="flex items-center justify-between border-b border-slate-700 px-5 py-4">
          <div>
            <h2 id="program-editor-title" className="mep-heading text-xl font-semibold text-white">{title}</h2>
            <p className="mt-1 text-sm text-slate-400">Changes are submitted only after all stored fields validate.</p>
          </div>
          <button type="button" onClick={onClose} disabled={pending} className="rounded-md p-2 text-slate-300 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-cyan-300" aria-label="Close program dialog">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>
        <form onSubmit={onSave} className="p-5">
          <ProgramFields draft={editor.draft} onChange={onChange} readOnly={isView || pending} requireStorageFields={false} />
          {error ? <p className="mt-4 rounded-md border border-rose-400/50 bg-rose-950/30 p-3 text-sm text-rose-100" role="alert">{error}</p> : null}
          <footer className="mt-6 flex flex-wrap justify-end gap-3 border-t border-slate-700 pt-4">
            <button type="button" onClick={onClose} disabled={pending} data-autofocus className="rounded-md border border-slate-600 px-4 py-2 text-sm font-medium text-slate-100 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-cyan-300">
              {isView ? 'Close' : 'Cancel'}
            </button>
            {!isView ? (
              <button type="submit" disabled={pending} className="mep-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-cyan-200">
                {pending ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                {editor.program ? 'Save persisted changes' : 'Create program'}
              </button>
            ) : null}
          </footer>
        </form>
      </section>
    </div>
  );
}

function DeleteProgramDialog({ program, pending, error, onClose, onConfirm }) {
  const dialogRef = useDialogFocus({ open: Boolean(program), onClose });
  if (!program) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/85 p-4" role="presentation">
      <section ref={dialogRef} className="mep-panel w-full max-w-lg rounded-xl border border-rose-300/30 p-6 shadow-2xl" role="alertdialog" aria-modal="true" aria-labelledby="delete-program-title" aria-describedby="delete-program-description">
        <h2 id="delete-program-title" className="mep-heading text-xl font-semibold text-white">Delete program record?</h2>
        <p id="delete-program-description" className="mt-2 break-words text-sm text-slate-300">
          Delete <strong>{program.name}</strong> only if the server confirms it. The server can reject deletion when an active challenge exists.
        </p>
        {error ? <p className="mt-4 rounded-md border border-rose-400/50 bg-rose-950/30 p-3 text-sm text-rose-100" role="alert">{error}</p> : null}
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onClose} disabled={pending} data-autofocus className="rounded-md border border-slate-600 px-4 py-2 text-sm font-medium text-slate-100 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-cyan-300">Cancel</button>
          <button type="button" onClick={onConfirm} disabled={pending} className="inline-flex items-center gap-2 rounded-md bg-rose-500 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-400 disabled:cursor-not-allowed disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-rose-200">
            {pending ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            Confirm server deletion
          </button>
        </div>
      </section>
    </div>
  );
}

export default function ProgramsManagement() {
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isAuthLoading = useAuthStore((state) => state.isLoading);
  const principal = useMemo(() => adminProgramsPrincipalFromAuth(user, isAuthenticated), [user, isAuthenticated]);
  const expectedOwner = principal?.owner ?? null;
  const principalKey = principal?.key ?? 'no-principal';
  const [readState, setReadState] = useState('loading');
  const [readError, setReadError] = useState(null);
  const [programs, setPrograms] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, perPage: 20, total: 0, pages: 0 });
  const [refreshKey, setRefreshKey] = useState(0);
  const [editor, setEditor] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [mutationPending, setMutationPending] = useState(false);
  const [mutationError, setMutationError] = useState(null);
  const [notice, setNotice] = useState(null);
  const generationRef = useRef(0);
  const writeControllerRef = useRef(null);

  const retry = useCallback(() => setRefreshKey((value) => value + 1), []);
  const refetchCurrentRange = useCallback(() => {
    setPrograms([]);
    setReadState('loading');
    setReadError(null);
    setRefreshKey((value) => value + 1);
  }, []);
  const refetchAfterDelete = useCallback(() => {
    setPrograms([]);
    setReadState('loading');
    setReadError(null);
    setPagination((current) => {
      const total = Math.max(0, current.total - 1);
      const pages = total === 0 ? 0 : Math.ceil(total / current.perPage);
      return { ...current, total, pages, page: Math.min(current.page, Math.max(1, pages)) };
    });
    setRefreshKey((value) => value + 1);
  }, []);

  useEffect(() => {
    setNotice(null);
  }, [principalKey, isAuthLoading]);

  useEffect(() => {
    generationRef.current += 1;
    const generation = generationRef.current;
    writeControllerRef.current?.abort();
    writeControllerRef.current = null;
    setPrograms([]);
    setEditor(null);
    setDeleteTarget(null);
    setMutationPending(false);
    setMutationError(null);

    if (isAuthLoading) {
      setReadState('loading');
      setReadError(null);
      return undefined;
    }
    if (!expectedOwner) {
      setReadState('error');
      setReadError('A verified supermaster or master session with a tenant is required to load program records.');
      return undefined;
    }

    const controller = new AbortController();
    setReadState('loading');
    setReadError(null);
    loadAdminPrograms(undefined, {
      signal: controller.signal,
      expectedOwner,
      page: pagination.page,
      perPage: pagination.perPage,
    }).then((view) => {
      if (!isCurrentProgramsOperation(generation, generationRef.current, controller.signal)) return;
      setPrograms(view.programs);
      setPagination(view.pagination);
      setReadState('ready');
    }).catch((error) => {
      if (!isCurrentProgramsOperation(generation, generationRef.current, controller.signal) || isAdminProgramsRequestCanceled(error)) return;
      setPrograms([]);
      setReadState('error');
      setReadError(errorMessage(error, 'The program catalog request failed.'));
    });
    return () => controller.abort();
  }, [expectedOwner, isAuthLoading, pagination.page, pagination.perPage, principalKey, refreshKey]);

  const openEditor = (mode, program = null) => {
    if (!expectedOwner || mutationPending) return;
    setNotice(null);
    setMutationError(null);
    setEditor({ mode, program, draft: program ? programDraft(program) : emptyDraft() });
  };

  const onDraftChange = (event) => {
    const { name, value, type, checked } = event.target;
    setEditor((current) => current ? {
      ...current,
      draft: { ...current.draft, [name]: type === 'checkbox' ? checked : value },
    } : current);
  };

  const closeDialog = () => {
    if (!mutationPending) {
      setEditor(null);
      setDeleteTarget(null);
      setMutationError(null);
    }
  };

  const save = async (event) => {
    event.preventDefault();
    if (!expectedOwner || !editor || editor.mode === 'view' || mutationPending) return;
    const generation = generationRef.current;
    const controller = new AbortController();
    writeControllerRef.current?.abort();
    writeControllerRef.current = controller;
    setMutationPending(true);
    setMutationError(null);
    setNotice(null);
    try {
      const saved = await saveAdminProgram(undefined, {
        programId: editor.program?.id ?? null,
        draft: editor.draft,
        signal: controller.signal,
        expectedOwner,
      });
      if (!isCurrentProgramsOperation(generation, generationRef.current, controller.signal)) return;
      if (editor.program) {
        setPrograms((rows) => rows.map((row) => row.id === saved.program.id ? saved.program : row));
      } else {
        refetchCurrentRange();
      }
      setEditor(null);
      setNotice(editor.program ? 'Saved the server-confirmed program record.' : 'Created the server-confirmed program record.');
    } catch (error) {
      if (!isCurrentProgramsOperation(generation, generationRef.current, controller.signal) || isAdminProgramsRequestCanceled(error)) return;
      setMutationError(errorMessage(error, 'Program changes were not saved.'));
    } finally {
      if (isCurrentProgramsOperation(generation, generationRef.current, controller.signal)) setMutationPending(false);
      if (writeControllerRef.current === controller) writeControllerRef.current = null;
    }
  };

  const confirmDelete = async () => {
    if (!expectedOwner || !deleteTarget || mutationPending) return;
    const generation = generationRef.current;
    const controller = new AbortController();
    writeControllerRef.current?.abort();
    writeControllerRef.current = controller;
    setMutationPending(true);
    setMutationError(null);
    setNotice(null);
    try {
      const deleted = await deleteAdminProgram(undefined, {
        programId: deleteTarget.id,
        signal: controller.signal,
        expectedOwner,
      });
      if (!isCurrentProgramsOperation(generation, generationRef.current, controller.signal)) return;
      refetchAfterDelete();
      setDeleteTarget(null);
      setNotice('Deleted the server-confirmed program record.');
    } catch (error) {
      if (!isCurrentProgramsOperation(generation, generationRef.current, controller.signal) || isAdminProgramsRequestCanceled(error)) return;
      setMutationError(errorMessage(error, 'Program deletion was not confirmed.'));
    } finally {
      if (isCurrentProgramsOperation(generation, generationRef.current, controller.signal)) setMutationPending(false);
      if (writeControllerRef.current === controller) writeControllerRef.current = null;
    }
  };

  const changePage = (nextPage) => {
    if (nextPage >= 1 && (pagination.pages === 0 || nextPage <= pagination.pages) && nextPage !== pagination.page) {
      setPagination((current) => ({ ...current, page: nextPage }));
    }
  };

  return (
    <div className="space-y-6 text-slate-100">
      <header className="flex flex-col gap-4 border-b border-cyan-300/15 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Administration / Catalog</p>
          <h1 className="mep-heading mt-2 text-3xl font-bold text-white">Programs management</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">Review and edit persisted program schema fields. Prices and constraints are exact stored decimals; this screen does not execute payments, provider actions, or quote settlement.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={retry} disabled={readState === 'loading' || mutationPending} className="inline-flex items-center gap-2 rounded-md border border-cyan-300/50 px-4 py-2 text-sm font-semibold text-cyan-100 hover:bg-cyan-300/10 disabled:cursor-not-allowed disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-cyan-300">
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh records
          </button>
          <button type="button" onClick={() => openEditor('create')} disabled={!expectedOwner || mutationPending} className="mep-primary inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-cyan-200">
            <Plus className="h-4 w-4" aria-hidden="true" /> Create program
          </button>
        </div>
      </header>

      {notice ? <p className="rounded-md border border-emerald-300/40 bg-emerald-950/25 p-3 text-sm text-emerald-100" role="status">{notice}</p> : null}
      <ProgramReadState state={readState} error={readError} onRetry={retry} />

      {readState === 'ready' && programs.length === 0 ? (
        <section className="mep-panel rounded-xl border p-8 text-center" aria-labelledby="empty-programs-title">
          <h2 id="empty-programs-title" className="mep-heading text-lg font-semibold text-white">No persisted program records</h2>
          <p className="mt-2 text-sm text-slate-300">The scoped catalog returned no records. Create a program only when its stored terms are available.</p>
        </section>
      ) : null}

      {readState === 'ready' && programs.length > 0 ? (
        <section className="mep-panel overflow-hidden rounded-xl border" aria-labelledby="program-list-title">
          <div className="flex flex-col gap-2 border-b border-slate-700 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 id="program-list-title" className="mep-heading font-semibold text-white">Persisted program catalog</h2>
              <p className="text-sm text-slate-400">{pagination.total} scoped record{pagination.total === 1 ? '' : 's'} · ordered by stored ID</p>
            </div>
            <span className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-xs font-medium text-cyan-100">Exact decimal fields</span>
          </div>
          <div className="overflow-x-auto" tabIndex="0" aria-label="Program catalog table">
            <table className="min-w-[1100px] w-full text-left text-sm">
              <thead className="bg-slate-950/70 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th scope="col" className="px-4 py-3">ID</th>
                  <th scope="col" className="px-4 py-3">Program</th>
                  <th scope="col" className="px-4 py-3">Type</th>
                  <th scope="col" className="px-4 py-3">Account size</th>
                  <th scope="col" className="px-4 py-3">Price</th>
                  <th scope="col" className="px-4 py-3">Constraints</th>
                  <th scope="col" className="px-4 py-3">Catalog state</th>
                  <th scope="col" className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {programs.map((program) => (
                  <tr key={program.id} className="align-top hover:bg-slate-800/45">
                    <td className="px-4 py-4 font-mono text-cyan-200">{program.id}</td>
                    <td className="max-w-xs px-4 py-4"><p className="break-words font-medium text-white">{program.name}</p><p className="mt-1 break-words text-xs text-slate-400">Tenant {program.tenantId}</p></td>
                    <td className="max-w-48 px-4 py-4 font-mono text-slate-200 break-words">{program.type}</td>
                    <td className="px-4 py-4 font-mono text-slate-100">{program.accountSize}</td>
                    <td className="px-4 py-4 font-mono font-semibold text-cyan-200">{program.price}</td>
                    <td className="max-w-xs px-4 py-4 text-xs leading-5 text-slate-300">
                      <span className="block">Target: {displayOptional(program.profitTarget)}</span>
                      <span className="block">Daily loss: {displayOptional(program.maxDailyLoss)}</span>
                      <span className="block">Total loss: {displayOptional(program.maxTotalLoss)}</span>
                    </td>
                    <td className="px-4 py-4"><span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${program.isActive ? 'bg-emerald-400/15 text-emerald-200' : 'bg-slate-700 text-slate-200'}`}>{program.isActive ? 'Active' : 'Inactive'}</span></td>
                    <td className="px-4 py-4">
                      <div className="flex justify-end gap-1">
                        <button type="button" onClick={() => openEditor('view', program)} disabled={mutationPending} className="rounded-md p-2 text-slate-200 hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-cyan-300" aria-label={`View ${program.name}`}><Eye className="h-4 w-4" aria-hidden="true" /></button>
                        <button type="button" onClick={() => openEditor('edit', program)} disabled={mutationPending} className="rounded-md p-2 text-cyan-200 hover:bg-cyan-300/10 focus:outline-none focus:ring-2 focus:ring-cyan-300" aria-label={`Edit ${program.name}`}><Edit2 className="h-4 w-4" aria-hidden="true" /></button>
                        <button type="button" onClick={() => { setNotice(null); setMutationError(null); setDeleteTarget(program); }} disabled={mutationPending} className="rounded-md p-2 text-rose-200 hover:bg-rose-400/10 focus:outline-none focus:ring-2 focus:ring-rose-200" aria-label={`Delete ${program.name}`}><Trash2 className="h-4 w-4" aria-hidden="true" /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <footer className="flex items-center justify-between border-t border-slate-700 px-5 py-3 text-sm text-slate-300">
            <span>Page {pagination.page} of {pagination.pages || 1}</span>
            <div className="flex gap-2">
              <button type="button" onClick={() => changePage(pagination.page - 1)} disabled={pagination.page <= 1 || mutationPending} className="rounded-md border border-slate-600 px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-cyan-300">Previous</button>
              <button type="button" onClick={() => changePage(pagination.page + 1)} disabled={pagination.pages === 0 || pagination.page >= pagination.pages || mutationPending} className="rounded-md border border-slate-600 px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-cyan-300">Next</button>
            </div>
          </footer>
        </section>
      ) : null}

      <ProgramEditor editor={editor} pending={mutationPending} error={mutationError} onClose={closeDialog} onSave={save} onChange={onDraftChange} />
      <DeleteProgramDialog program={deleteTarget} pending={mutationPending} error={mutationError} onClose={closeDialog} onConfirm={confirmDelete} />
    </div>
  );
}
