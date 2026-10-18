import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Eye, KeyRound, List, Network, Pencil, Plus, RefreshCw, UserMinus, Users, X } from "lucide-react";
import useAuthStore from "../../store/authStore.js";
import { getCreatableRoles, getRoleConfig } from "../../constants/roles.js";
import {
  ADMIN_CLOSURE_USERS_CREATABLE_ROLES,
  ADMIN_CLOSURE_USERS_ROLES,
  createAdminClosureUsersService,
  isAdminClosureUsersRequestCanceled,
} from "../../services/adminClosureUsersService.js";
import useAdminClosureUsersRead from "../../hooks/useAdminClosureUsers.js";
import { useDialogFocus } from "../../hooks/useDialogFocus.js";

const usersService = createAdminClosureUsersService();
const panel = "rounded-2xl border border-white/10 bg-slate-900/80 shadow-xl shadow-slate-950/20";
const input = "w-full rounded-xl border border-white/15 bg-slate-950/60 px-3 py-2.5 text-sm text-white outline-none transition placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-60";
const button = "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-not-allowed disabled:opacity-55";

const blankCreate = (role = "trader") => ({
  first_name: "", last_name: "", email: "", password: "", phone: "", country_code: "", role,
});
const formatDate = (value) => (value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value)) : "Not recorded");
const text = (value, fallback = "Unknown") => value || fallback;
const roleLabel = (role) => role ? getRoleConfig(role).label : "Unknown role";
const statusLabel = (active) => active === true ? "Active" : active === false ? "Inactive" : "Unknown";
const statusClass = (active) => active === true ? "bg-emerald-400/15 text-emerald-200" : active === false ? "bg-rose-400/15 text-rose-200" : "bg-slate-700 text-slate-200";
const isAbort = (error) => isAdminClosureUsersRequestCanceled(error) || error?.name === "AbortError";
const errorMessage = (error, fallback) => {
  const source = error?.response?.data;
  return typeof source?.error === "string" ? source.error : typeof source?.message === "string" ? source.message : fallback;
};

function DialogFrame({ title, children, onClose, labelledBy }) {
  const dialogRef = useDialogFocus({ open: true, onClose });
  return (
    <div className="fixed inset-0 z-[1400] flex items-end bg-slate-950/80 p-0 sm:items-center sm:p-6" role="presentation">
      <section ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={labelledBy} className="mep-panel max-h-[94vh] w-full overflow-y-auto rounded-t-2xl border shadow-2xl sm:max-w-3xl sm:rounded-2xl">
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-white/10 bg-slate-900/95 px-5 py-4 backdrop-blur sm:px-6">
          <div><h2 id={labelledBy} className="mep-heading text-xl font-bold text-white">{title}</h2></div>
          <button type="button" onClick={onClose} data-autofocus className={`${button} -mr-2 p-2 text-slate-300 hover:bg-white/10 hover:text-white`} aria-label="Close dialog"><X size={20} /></button>
        </header>
        {children}
      </section>
    </div>
  );
}

function ReadState({ read, empty, emptyTitle, emptyMessage }) {
  if (read.loading) return <section className={`${panel} p-6 text-slate-200`} role="status" aria-busy="true">Loading server-scoped user records…</section>;
  if (read.error) return <section className={`${panel} border-rose-300/30 p-6 text-rose-100`} role="alert"><p className="font-semibold">User records could not be loaded.</p><p className="mt-1 text-sm text-rose-200">{typeof read.error === "string" ? read.error : "The request failed or the response could not be validated. No result was assumed."}</p><button type="button" onClick={read.refresh} className={`${button} mt-4 bg-cyan-300 text-slate-950 hover:bg-cyan-200`}>Retry</button></section>;
  if (empty) return <section className={`${panel} p-6`}><h2 className="mep-heading font-semibold text-white">{emptyTitle}</h2><p className="mt-2 text-sm leading-6 text-slate-300">{emptyMessage}</p></section>;
  return null;
}

function UserTable({ users, onView, onEdit, onDeactivate, canEdit }) {
  return (
    <div className={`${panel} overflow-hidden`}>
      <div className="overflow-x-auto">
        <table className="min-w-[920px] w-full text-left text-sm">
          <caption className="sr-only">Server-scoped users</caption>
          <thead className="border-b border-white/10 bg-slate-950/50 text-xs uppercase tracking-wider text-slate-300"><tr>
            <th className="px-5 py-3">User</th><th className="px-4 py-3">Role</th><th className="px-4 py-3">Account</th><th className="px-4 py-3">KYC</th><th className="px-4 py-3">Last login</th><th className="px-5 py-3 text-right">Actions</th>
          </tr></thead>
          <tbody className="divide-y divide-white/10">
            {users.map((user) => <tr key={user.id} className="align-top hover:bg-white/[0.03]">
              <td className="px-5 py-4"><p className="font-semibold text-white break-words">{text([user.first_name, user.last_name].filter(Boolean).join(" "))}</p><p className="mt-1 max-w-[20rem] break-all text-slate-400">{text(user.email, "Email unavailable")}</p></td>
              <td className="px-4 py-4"><span className="rounded-full bg-cyan-400/10 px-2.5 py-1 text-xs font-semibold text-cyan-100">{roleLabel(user.role)}</span></td>
              <td className="px-4 py-4"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusClass(user.is_active)}`}>{statusLabel(user.is_active)}</span></td>
              <td className="px-4 py-4 capitalize text-slate-300">{text(user.kyc_status?.replaceAll("_", " "))}</td>
              <td className="px-4 py-4 text-slate-300">{formatDate(user.last_login_at)}</td>
              <td className="px-5 py-4"><div className="flex justify-end gap-2">
                <button type="button" onClick={() => onView(user.id)} className={`${button} border border-cyan-300/30 text-cyan-100 hover:bg-cyan-300/10`}><Eye size={16} />View</button>
                <button type="button" onClick={() => onEdit(user.id)} disabled={!canEdit} className={`${button} border border-white/15 text-slate-100 hover:bg-white/10`}><Pencil size={16} />Edit</button>
                <button type="button" onClick={() => onDeactivate(user)} disabled={!canEdit || user.is_active !== true} className={`${button} border border-rose-300/30 text-rose-100 hover:bg-rose-400/10`}><UserMinus size={16} />Deactivate</button>
              </div></td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Tree({ users, onView }) {
  const renderNode = (node, depth = 0) => <li key={node.id} className="border-l border-cyan-300/20 pl-4" style={{ marginLeft: `${Math.min(depth, 5) * 8}px` }}>
    <button type="button" onClick={() => onView(node.id)} className="w-full rounded-xl border border-white/10 bg-slate-950/35 p-3 text-left hover:border-cyan-300/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">
      <span className="block break-words font-semibold text-white">{text([node.first_name, node.last_name].filter(Boolean).join(" "))}</span>
      <span className="mt-1 block text-sm text-slate-400">{roleLabel(node.role)} · {statusLabel(node.is_active)}</span>
    </button>
    {node.children.length > 0 && <ul className="mt-2 space-y-2">{node.children.map((child) => renderNode(child, depth + 1))}</ul>}
  </li>;
  return <section className={`${panel} p-4 sm:p-6`} aria-labelledby="users-hierarchy-heading"><h2 id="users-hierarchy-heading" className="mep-heading text-lg font-semibold text-white">Scoped hierarchy</h2><p className="mt-1 text-sm text-slate-400">Only the bounded hierarchy returned for the active account is shown.</p><ul className="mt-5 space-y-3">{users.map((node) => renderNode(node))}</ul></section>;
}

export function AdminClosureUsersContent({ read, viewMode, filters, onFilter, onPage, onViewMode, onView, onEdit, onDeactivate, onCreate, canCreate, canEdit }) {
  const isTree = viewMode === "tree";
  const rows = isTree ? read.value?.users || [] : read.value?.users || [];
  const pageCounts = !isTree ? {
    supermaster: rows.filter((row) => row.role === "supermaster").length,
    master: rows.filter((row) => row.role === "master").length,
    affiliate: rows.filter((row) => row.role === "affiliate").length,
    trader: rows.filter((row) => row.role === "trader").length,
  } : null;
  return <div className="space-y-5 p-4 sm:p-6">
    <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">Administration / scoped access</p><h1 className="mep-heading mt-2 text-2xl font-bold text-white sm:text-3xl">User management</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">Review only the hierarchy-scoped accounts returned by the server. Account creation, edits, deactivation, and password reset acknowledge the persisted server response only.</p></div>
      <div className="flex flex-wrap gap-2"><div className="mep-panel inline-flex rounded-xl border p-1" aria-label="User display mode"><button type="button" onClick={() => onViewMode("table")} aria-pressed={!isTree} className={`${button} ${!isTree ? "bg-cyan-300 text-slate-950" : "text-slate-200 hover:bg-white/10"}`}><List size={16} />Table</button><button type="button" onClick={() => onViewMode("tree")} aria-pressed={isTree} className={`${button} ${isTree ? "bg-cyan-300 text-slate-950" : "text-slate-200 hover:bg-white/10"}`}><Network size={16} />Hierarchy</button></div><button type="button" onClick={onCreate} disabled={!canCreate} className={`${button} bg-cyan-300 text-slate-950 hover:bg-cyan-200`}><Plus size={17} />Add user</button></div>
    </header>
    {!isTree && <>
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Users on current page">
        {[["Super Masters", pageCounts.supermaster], ["Masters", pageCounts.master], ["Affiliates", pageCounts.affiliate], ["Traders", pageCounts.trader]].map(([label, count]) => <div key={label} className={`${panel} p-4`}><p className="text-sm text-slate-300">{label}</p><p className="mt-2 text-2xl font-bold text-white">{count}</p><p className="mt-1 text-xs text-slate-500">On this page only</p></div>)}
      </section>
      <section className={`${panel} p-4 sm:p-5`} aria-labelledby="user-record-filters"><div className="flex items-center justify-between gap-3"><div><h2 id="user-record-filters" className="mep-heading font-semibold text-white">User filters</h2><p className="mt-1 text-sm text-slate-400">Filters are enforced by the server.</p></div><button type="button" onClick={read.refresh} disabled={read.loading} className={`${button} border border-white/15 text-slate-100 hover:bg-white/10`}><RefreshCw size={16} />Refresh</button></div><div className="mt-5 grid gap-4 md:grid-cols-3"><label className="text-sm font-medium text-slate-200">Search<input value={filters.search} onChange={(event) => onFilter("search", event.target.value)} placeholder="Name or email" className={`${input} mt-2`} /></label><label className="text-sm font-medium text-slate-200">Role<select value={filters.role || ""} onChange={(event) => onFilter("role", event.target.value || null)} className={`${input} mt-2`}><option value="">All roles</option>{ADMIN_CLOSURE_USERS_ROLES.map((role) => <option key={role} value={role}>{roleLabel(role)}</option>)}</select></label><label className="text-sm font-medium text-slate-200">Account status<select value={filters.status || ""} onChange={(event) => onFilter("status", event.target.value || null)} className={`${input} mt-2`}><option value="">All statuses</option><option value="active">Active</option><option value="inactive">Inactive</option></select></label></div></section>
      <ReadState read={read} empty={!read.loading && !read.error && read.value && rows.length === 0} emptyTitle="No user records" emptyMessage="The server returned no records for this page and selected filters. This does not establish the absence of accounts outside your permitted scope." />
      {!read.loading && !read.error && rows.length > 0 && <><p className="px-1 text-sm text-slate-300" aria-live="polite">Showing {rows.length} record{rows.length === 1 ? "" : "s"} on this page · {read.value.pagination.total} server-scoped record{read.value.pagination.total === 1 ? "" : "s"}.</p><UserTable users={rows} onView={onView} onEdit={onEdit} onDeactivate={onDeactivate} canEdit={canEdit} /></>}
      {!read.loading && !read.error && read.value && (read.value.pagination.pages > 0 ? <nav className={`${panel} flex flex-wrap items-center justify-between gap-3 p-4`} aria-label="User pagination"><p className="text-sm text-slate-300">Page {read.value.pagination.page} of {read.value.pagination.pages}</p><div className="flex gap-2"><button type="button" className={`${button} border border-white/15 text-white hover:bg-white/10`} disabled={read.value.pagination.page <= 1} onClick={() => onPage(read.value.pagination.page - 1)}>Previous</button><button type="button" className={`${button} border border-white/15 text-white hover:bg-white/10`} disabled={read.value.pagination.page >= read.value.pagination.pages} onClick={() => onPage(read.value.pagination.page + 1)}>Next</button></div></nav> : <p className="px-1 text-sm text-slate-400" role="status">No server pages are available for these filters.</p>)}
      </>}
    {isTree && <><ReadState read={read} empty={!read.loading && !read.error && read.value && rows.length === 0} emptyTitle="No hierarchy records" emptyMessage="The server returned no bounded hierarchy nodes for your active account." />{!read.loading && !read.error && rows.length > 0 && <Tree users={rows} onView={onView} />}</>}
  </div>;
}

function UserDetailsDialog({ userId, auth, onClose, onEdit, onReset, refreshToken, editAfterLoad = false }) {
  const load = useCallback((expectedOwner, signal) => usersService.loadDetails({ expectedOwner, userId, signal }), [userId]);
  const read = useAdminClosureUsersRead({ isAuthenticated: auth.isAuthenticated, userId: auth.userId, tenantId: auth.tenantId, role: auth.role, queryKey: JSON.stringify(["detail", userId, refreshToken]), load });
  const detail = read.value;
  useEffect(() => {
    if (editAfterLoad && detail?.user) onEdit(detail.user);
  }, [detail?.user, editAfterLoad, onEdit]);
  return <DialogFrame title="User details" labelledBy="user-details-title" onClose={onClose}><div className="space-y-5 p-5 sm:p-6"><ReadState read={read} empty={false} />{detail && <>
    <section className={`${panel} p-4`}><h3 className="font-semibold text-white">Account</h3><dl className="mt-4 grid gap-4 sm:grid-cols-2 text-sm"><div><dt className="text-slate-400">Name</dt><dd className="mt-1 break-words text-white">{text([detail.user.first_name, detail.user.last_name].filter(Boolean).join(" "))}</dd></div><div><dt className="text-slate-400">Email</dt><dd className="mt-1 break-all text-white">{text(detail.user.email, "Unavailable")}</dd></div><div><dt className="text-slate-400">Phone</dt><dd className="mt-1 text-white">{[detail.user.country_code, detail.user.phone].filter(Boolean).join(" ") || "Not recorded"}</dd></div><div><dt className="text-slate-400">Security status</dt><dd className="mt-1 text-white">Email {detail.user.is_verified === true ? "verified" : detail.user.is_verified === false ? "not verified" : "unknown"}; 2FA {detail.user.two_factor_enabled === true ? "enabled" : detail.user.two_factor_enabled === false ? "disabled" : "unknown"}</dd></div></dl></section>
    <section className={`${panel} p-4`}><h3 className="font-semibold text-white">Direct downline</h3><p className="mt-1 text-sm text-slate-400">{detail.downline.items.length} bounded direct record{detail.downline.items.length === 1 ? "" : "s"}{detail.downline.truncated ? "; more records were not returned." : "."}</p>{detail.downline.items.length > 0 && <ul className="mt-3 divide-y divide-white/10">{detail.downline.items.map((item) => <li key={item.id} className="py-2 text-sm text-slate-200 break-words">{text([item.first_name, item.last_name].filter(Boolean).join(" "))} · {roleLabel(item.role)} · {statusLabel(item.is_active)}</li>)}</ul>}</section>
    <section className={`${panel} p-4`}><h3 className="font-semibold text-white">Recorded challenges</h3><p className="mt-1 text-sm text-slate-400">No currency is inferred for challenge balances or profit. {detail.challenges.truncated ? "Additional rows were not returned." : ""}</p>{detail.challenges.items.length > 0 && <div className="mt-3 overflow-x-auto"><table className="min-w-[640px] w-full text-left text-sm"><thead className="text-slate-400"><tr><th className="pb-2">Program</th><th className="pb-2">Status</th><th className="pb-2">Initial balance</th><th className="pb-2">Current balance</th><th className="pb-2">Profit</th></tr></thead><tbody>{detail.challenges.items.map((item) => <tr key={item.id} className="border-t border-white/10 text-slate-100"><td className="py-2">{text(item.program_name)}</td><td className="py-2">{text(item.status)}</td><td className="py-2">{text(item.initial_balance)}</td><td className="py-2">{text(item.current_balance)}</td><td className="py-2">{text(item.total_profit)}</td></tr>)}</tbody></table></div>}</section>
    <section className={`${panel} p-4`}><h3 className="font-semibold text-white">Recorded payments</h3><p className="mt-1 text-sm text-slate-400">Legacy record values are not settlement evidence and are never aggregated across currencies. {detail.payments.truncated ? "Additional rows were not returned." : ""}</p>{detail.payments.items.length > 0 && <div className="mt-3 overflow-x-auto"><table className="min-w-[600px] w-full text-left text-sm"><thead className="text-slate-400"><tr><th className="pb-2">Amount</th><th className="pb-2">Currency</th><th className="pb-2">Purpose</th><th className="pb-2">Status</th><th className="pb-2">Recorded</th></tr></thead><tbody>{detail.payments.items.map((item) => <tr key={item.id} className="border-t border-white/10 text-slate-100"><td className="py-2">{text(item.amount)}</td><td className="py-2">{text(item.currency, "Currency unavailable")}</td><td className="py-2">{text(item.payment_type)}</td><td className="py-2">{text(item.status)}</td><td className="py-2">{formatDate(item.created_at)}</td></tr>)}</tbody></table></div>}</section>
    <div className="flex flex-wrap justify-end gap-2"><button type="button" onClick={() => onEdit(detail.user)} className={`${button} border border-white/15 text-white hover:bg-white/10`}><Pencil size={16} />Edit account</button><button type="button" onClick={() => onReset(detail.user.id)} className={`${button} bg-cyan-300 text-slate-950 hover:bg-cyan-200`}><KeyRound size={16} />Reset password</button></div>
  </>}</div></DialogFrame>;
}

function AccountDialog({ mode, user, roles, onClose, onSubmit, busy, error }) {
  const [values, setValues] = useState(mode === "create" ? blankCreate(roles[0]?.value || "trader") : {});
  useEffect(() => { if (mode === "edit" && user) setValues({ first_name: user.first_name || "", last_name: user.last_name || "", phone: user.phone || "", country_code: user.country_code || "", role: user.role || "guest", is_active: user.is_active === true }); }, [mode, user]);
  const update = (name, value) => setValues((previous) => ({ ...previous, [name]: value }));
  const isCreate = mode === "create";
  const roleOptions = isCreate ? roles : ADMIN_CLOSURE_USERS_ROLES.map((role) => ({ value: role, label: roleLabel(role) }));
  return <DialogFrame title={isCreate ? "Add user" : "Edit account"} labelledBy="user-account-dialog-title" onClose={onClose}><form className="space-y-5 p-5 sm:p-6" onSubmit={(event) => { event.preventDefault(); onSubmit(values); }}>
    {error && <p role="alert" className="rounded-xl border border-rose-300/30 bg-rose-400/10 p-3 text-sm text-rose-100">{error}</p>}
    <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium text-slate-200">First name<input required value={values.first_name || ""} onChange={(event) => update("first_name", event.target.value)} className={`${input} mt-2`} /></label><label className="text-sm font-medium text-slate-200">Last name<input required value={values.last_name || ""} onChange={(event) => update("last_name", event.target.value)} className={`${input} mt-2`} /></label></div>
    {isCreate && <><label className="block text-sm font-medium text-slate-200">Email<input required type="email" value={values.email || ""} onChange={(event) => update("email", event.target.value)} className={`${input} mt-2`} /></label><label className="block text-sm font-medium text-slate-200">Initial password<input required type="password" autoComplete="new-password" value={values.password || ""} onChange={(event) => update("password", event.target.value)} className={`${input} mt-2`} /><span className="mt-1 block text-xs font-normal text-slate-400">The server applies the password policy. Password text is not retained after submission.</span></label></>}
    {!isCreate && <p className="rounded-xl border border-white/10 bg-slate-950/40 p-3 text-sm text-slate-300">Email is an account identifier and is not editable in this supported action.</p>}
    <div className="grid gap-4 sm:grid-cols-[1fr_8rem]"><label className="text-sm font-medium text-slate-200">Phone<input value={values.phone || ""} onChange={(event) => update("phone", event.target.value)} className={`${input} mt-2`} /></label><label className="text-sm font-medium text-slate-200">Country code<input value={values.country_code || ""} maxLength={2} onChange={(event) => update("country_code", event.target.value)} placeholder="+1" className={`${input} mt-2`} /></label></div>
    <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium text-slate-200">Role<select value={values.role || ""} onChange={(event) => update("role", event.target.value)} className={`${input} mt-2`}>{roleOptions.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}</select></label>{!isCreate && <label className="mt-6 flex items-center gap-3 rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2.5 text-sm text-slate-100"><input type="checkbox" checked={values.is_active === true} onChange={(event) => update("is_active", event.target.checked)} className="h-4 w-4 accent-cyan-300" />Account active</label>}</div>
    <div className="flex flex-wrap justify-end gap-3 border-t border-white/10 pt-5"><button type="button" onClick={onClose} disabled={busy} className={`${button} border border-white/15 text-white hover:bg-white/10`}>Cancel</button><button type="submit" disabled={busy || roleOptions.length === 0} className={`${button} bg-cyan-300 text-slate-950 hover:bg-cyan-200`}>{busy ? "Saving…" : isCreate ? "Create user" : "Save account"}</button></div>
  </form></DialogFrame>;
}

function PasswordResetDialog({ userId, onClose, onSubmit, busy, error }) {
  const [password, setPassword] = useState("");
  return <DialogFrame title="Reset password" labelledBy="user-password-reset-title" onClose={onClose}><form className="space-y-5 p-5 sm:p-6" onSubmit={(event) => { event.preventDefault(); onSubmit(password); }}><p className="rounded-xl border border-amber-300/25 bg-amber-300/10 p-3 text-sm text-amber-50">This changes the password for user ID {userId} and invalidates existing tokens when the server confirms it. The password is never displayed or stored in this page state after submission.</p>{error && <p role="alert" className="rounded-xl border border-rose-300/30 bg-rose-400/10 p-3 text-sm text-rose-100">{error}</p>}<label className="block text-sm font-medium text-slate-200">New password<input required type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} className={`${input} mt-2`} /></label><div className="flex justify-end gap-3"><button type="button" onClick={onClose} disabled={busy} className={`${button} border border-white/15 text-white hover:bg-white/10`}>Cancel</button><button type="submit" disabled={busy} className={`${button} bg-cyan-300 text-slate-950 hover:bg-cyan-200`}>{busy ? "Resetting…" : "Confirm password reset"}</button></div></form></DialogFrame>;
}

export default function UserManagementConnected() {
  const { user, isAuthenticated } = useAuthStore();
  const auth = { isAuthenticated, userId: user?.id, tenantId: user?.tenant_id, role: user?.role };
  const [viewMode, setViewMode] = useState("table");
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ role: null, status: null, search: "" });
  const [dialog, setDialog] = useState(null);
  const [notice, setNotice] = useState(null);
  const [writeError, setWriteError] = useState(null);
  const [writing, setWriting] = useState(false);
  const writeAbortRef = useRef(null);
  const writeGenerationRef = useRef(0);
  const createRoles = useMemo(() => getCreatableRoles(auth.role).filter((role) => ADMIN_CLOSURE_USERS_CREATABLE_ROLES.includes(role.value)), [auth.role]);
  const canCreate = createRoles.length > 0;
  const canEdit = auth.isAuthenticated === true && ["supermaster", "master"].includes(auth.role);
  const queryKey = useMemo(() => JSON.stringify([viewMode, page, filters.role, filters.status, filters.search || null]), [filters.role, filters.search, filters.status, page, viewMode]);
  const load = useCallback((expectedOwner, signal) => viewMode === "tree"
    ? usersService.loadHierarchy({ expectedOwner, signal })
    : usersService.loadUsers({ expectedOwner, signal, page, role: filters.role, status: filters.status, search: filters.search || null }), [filters.role, filters.search, filters.status, page, viewMode]);
  const read = useAdminClosureUsersRead({ ...auth, queryKey, load });
  useEffect(() => () => { writeGenerationRef.current += 1; writeAbortRef.current?.abort(); }, [read.principalKey]);
  const executeWrite = useCallback(async (operation) => {
    if (!read.principal) { setWriteError("Your current admin identity is unavailable. No account action was sent."); return; }
    const generation = ++writeGenerationRef.current;
    writeAbortRef.current?.abort();
    const controller = new AbortController();
    writeAbortRef.current = controller;
    setWriting(true); setWriteError(null); setNotice(null);
    try {
      const result = await operation(read.principal.owner, controller.signal);
      if (controller.signal.aborted || generation !== writeGenerationRef.current) return;
      setNotice(result.message);
      setDialog(null);
      read.refresh();
    } catch (error) {
      if (!controller.signal.aborted && generation === writeGenerationRef.current && !isAbort(error)) setWriteError(errorMessage(error, "The account action was not confirmed by the server."));
    } finally {
      if (generation === writeGenerationRef.current) setWriting(false);
    }
  }, [read]);
  const onFilter = useCallback((name, value) => { setFilters((previous) => ({ ...previous, [name]: value })); setPage(1); }, []);
  const openDetails = useCallback((id) => { setWriteError(null); setDialog({ kind: "details", userId: id, refreshToken: Date.now() }); }, []);
  const deactivate = useCallback((target) => {
    if (typeof window !== "undefined" && !window.confirm(`Deactivate ${[target.first_name, target.last_name].filter(Boolean).join(" ") || "this account"}? The account will become inactive; it is not permanently deleted.`)) return;
    executeWrite((expectedOwner, signal) => usersService.deactivateUser({ expectedOwner, userId: target.id, signal }));
  }, [executeWrite]);
  return <>
    {notice && <div className="fixed bottom-4 right-4 z-[1500] max-w-sm rounded-xl border border-emerald-300/30 bg-emerald-950 p-4 text-sm text-emerald-100 shadow-xl" role="status">{notice}</div>}
    <AdminClosureUsersContent read={read} viewMode={viewMode} filters={filters} onFilter={onFilter} onPage={setPage} onViewMode={(mode) => { setViewMode(mode); setPage(1); }} onView={openDetails} onEdit={(id) => setDialog({ kind: "details", userId: id, refreshToken: Date.now(), editAfterLoad: true })} onDeactivate={deactivate} onCreate={() => { setWriteError(null); setDialog({ kind: "create" }); }} canCreate={canCreate} canEdit={canEdit} />
    {dialog?.kind === "details" && <UserDetailsDialog userId={dialog.userId} auth={auth} refreshToken={dialog.refreshToken} editAfterLoad={dialog.editAfterLoad} onClose={() => setDialog(null)} onEdit={(detailUser) => { setWriteError(null); setDialog({ kind: "edit", user: detailUser }); }} onReset={(userId) => { setWriteError(null); setDialog({ kind: "reset", userId }); }} />}
    {dialog?.kind === "create" && <AccountDialog mode="create" roles={createRoles} busy={writing} error={writeError} onClose={() => setDialog(null)} onSubmit={(values) => executeWrite((expectedOwner, signal) => usersService.createUser({ expectedOwner, values, signal }))} />}
    {dialog?.kind === "edit" && <AccountDialog mode="edit" user={dialog.user} roles={createRoles} busy={writing} error={writeError} onClose={() => setDialog(null)} onSubmit={(values) => executeWrite((expectedOwner, signal) => usersService.updateUser({ expectedOwner, userId: dialog.user.id, values, signal }))} />}
    {dialog?.kind === "reset" && <PasswordResetDialog userId={dialog.userId} busy={writing} error={writeError} onClose={() => setDialog(null)} onSubmit={(newPassword) => executeWrite((expectedOwner, signal) => usersService.resetPassword({ expectedOwner, userId: dialog.userId, newPassword, signal }))} />}
  </>;
}
