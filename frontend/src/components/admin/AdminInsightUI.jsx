import { AlertTriangle, BarChart3, Loader2, RefreshCw, ShieldAlert, Users } from "lucide-react";
import { Link } from "react-router-dom";

export const adminInsightPanel = "mep-panel min-w-0 rounded-2xl border p-4 sm:p-6";
export const adminInsightButton = "inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-400/40 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition-colors hover:bg-cyan-400/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-45";

const labels = {
  supermaster: "Super master", master: "Master", affiliate: "Affiliate", trader: "Trader", guest: "Guest",
  not_submitted: "Not submitted", pending: "Pending", approved: "Approved", rejected: "Rejected",
  incomplete: "Incomplete", verified: "Verified", unverified: "Unverified",
  active: "Active", completed: "Completed", passed: "Passed", failed: "Failed", funded: "Funded", cancelled: "Cancelled",
  refunded: "Refunded", challenge_purchase: "Challenge purchase", withdrawal: "Withdrawal", refund: "Refund",
};

export const adminInsightDisplay = (value, unavailable = "Unknown") => (
  value === null || value === undefined || value === "" ? unavailable : String(value)
);
export const adminInsightCode = (code) => (code === null ? "Unknown" : (labels[code] || "Unknown"));
export const adminInsightDate = (value) => adminInsightDisplay(value, "Not recorded");
export const adminInsightCount = (value) => Number(value).toLocaleString("en-US");

export function AdminInsightBoundary({ asOf, analytics = false }) {
  return (
    <div className="flex gap-3 rounded-2xl border border-amber-300/25 bg-amber-950/20 p-4 text-sm leading-6 text-amber-100" role="note">
      <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
      <div>
        <p><strong>Recorded legacy data only.</strong> Record verification is unavailable and settlement is disabled.</p>
        <p className="mt-1 text-amber-100/90">
          {analytics
            ? "Daily values count record creation in the selected UTC calendar days. Statuses are current recorded statuses in that bounded scope, not status-transition events."
            : "Counts and rows are server-scoped recorded data only; they do not establish identity, payment completion, funds availability, or entitlement."}
        </p>
        {asOf && <p className="mt-1 text-xs text-amber-100/80">Source snapshot: <time dateTime={asOf}>{asOf}</time></p>}
      </div>
    </div>
  );
}

export function AdminInsightReadState({ loading, error, onRetry, empty, emptyTitle, emptyMessage }) {
  if (loading) {
    return (
      <div className={`${adminInsightPanel} flex min-h-48 items-center justify-center`} role="status" aria-busy="true">
        <Loader2 className="mr-3 h-5 w-5 animate-spin motion-reduce:animate-none text-cyan-300" aria-hidden="true" />
        <p className="text-slate-200">Loading recorded insights…</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-2xl border border-red-300/30 bg-red-950/25 p-5 text-red-100" role="alert">
        <h2 className="mep-heading flex items-center gap-2 font-semibold"><AlertTriangle className="h-5 w-5" aria-hidden="true" />Recorded insights could not be loaded</h2>
        <p className="mt-2 text-sm leading-6">The service is unavailable or its response could not be validated. No count, status, date, amount, or empty result has been assumed.</p>
        <button type="button" onClick={onRetry} className={`${adminInsightButton} mt-4`}><RefreshCw className="h-4 w-4" aria-hidden="true" />Refresh records</button>
      </div>
    );
  }
  if (empty) {
    return (
      <section className={`${adminInsightPanel} py-10 text-center`} aria-labelledby="admin-insight-empty-title">
        <h2 id="admin-insight-empty-title" className="mep-heading text-lg font-semibold text-white">{emptyTitle}</h2>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-slate-300">{emptyMessage}</p>
      </section>
    );
  }
  return null;
}

const countCards = [
  { key: "users", title: "Users", href: "/admin/users", accent: "text-cyan-200" },
  { key: "challenges", title: "Challenges", href: "/admin/challenges", accent: "text-cyan-200" },
  { key: "payments", title: "Payments", href: "/admin/payments", accent: "text-cyan-200" },
];
export function AdminInsightCountCards({ counts }) {
  return (
    <section aria-label="Recorded counts" className="grid gap-4 sm:grid-cols-3">
      {countCards.map((card) => (
        <Link key={card.key} to={card.href} className={`${adminInsightPanel} group block transition-colors hover:border-cyan-300/35 hover:bg-slate-800/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-cyan-300`}>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">Recorded {card.title}</p>
          <p className={`mt-2 text-3xl font-bold ${card.accent}`}>{adminInsightCount(counts[card.key])}</p>
          <p className="mt-2 text-xs text-slate-400">Current count in this server-provided scope</p>
        </Link>
      ))}
    </section>
  );
}

export function AdminInsightDistribution({ title, rows, description }) {
  return (
    <section className={adminInsightPanel} aria-labelledby={`distribution-${title.replace(/\s+/g, "-").toLowerCase()}`}>
      <h2 id={`distribution-${title.replace(/\s+/g, "-").toLowerCase()}`} className="mep-heading text-base font-semibold text-white">{title}</h2>
      <p className="mt-1 text-sm leading-6 text-slate-400">{description}</p>
      {rows.length === 0 ? (
        <p className="mt-5 text-sm text-slate-400">No recorded categories in this scope.</p>
      ) : (
        <ul className="mt-5 space-y-3" aria-label={`${title} counts`}>
          {rows.map((row, index) => (
            <li key={`${row.code ?? "unknown"}-${index}`} className="flex items-center justify-between gap-4 border-b border-white/5 pb-3 text-sm last:border-0 last:pb-0">
              <span className="min-w-0 break-words text-slate-200">{adminInsightCode(row.code)}</span>
              <span className="shrink-0 font-mono font-semibold text-cyan-100">{adminInsightCount(row.count)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function TableShell({ children, label, caption }) {
  return <div className={`${adminInsightPanel} p-0`}><div className="max-w-full overflow-x-auto" tabIndex="0" aria-label={label}>{children || <table className="w-full"><caption className="sr-only">{caption}</caption></table>}</div></div>;
}
function Cell({ children, className = "" }) { return <td className={`max-w-56 break-words px-4 py-3 align-top text-sm text-slate-200 sm:px-5 ${className}`}>{children}</td>; }
function Pill({ children }) { return <span className="inline-flex max-w-full break-words rounded-full border border-cyan-300/30 bg-cyan-300/10 px-2.5 py-1 text-xs font-semibold text-cyan-100">{children}</span>; }
function CalendarCell({ value }) { return value === null ? <span className="text-slate-400">Not recorded</span> : <time dateTime={value} className="break-all text-slate-300">{value}</time>; }

export function AdminInsightRecentUsersTable({ users }) {
  return (
    <TableShell label="Recent recorded user table; scroll horizontally for all columns" caption="Recent recorded users">
      <table className="min-w-[760px] w-full border-collapse text-left"><caption className="sr-only">Recent recorded users</caption>
        <thead className="border-b border-white/10 bg-slate-950/35 text-xs uppercase tracking-wide text-slate-400"><tr><th scope="col" className="px-4 py-3 sm:px-5">User ID</th><th scope="col" className="px-4 py-3 sm:px-5">Role</th><th scope="col" className="px-4 py-3 sm:px-5">Active</th><th scope="col" className="px-4 py-3 sm:px-5">Recorded KYC</th><th scope="col" className="px-4 py-3 sm:px-5">Created</th></tr></thead>
        <tbody className="divide-y divide-white/10">{users.map((user) => <tr key={user.id} className="transition-colors hover:bg-cyan-300/[0.035]"><Cell className="font-mono text-cyan-100">{user.id}</Cell><Cell><Pill>{adminInsightCode(user.role)}</Pill></Cell><Cell>{user.is_active === null ? <span className="text-slate-400">Unknown</span> : <Pill>{user.is_active ? "Active" : "Inactive"}</Pill>}</Cell><Cell><Pill>{adminInsightCode(user.kyc_status)}</Pill></Cell><Cell><CalendarCell value={user.created_at} /></Cell></tr>)}</tbody>
      </table>
    </TableShell>
  );
}

export function AdminInsightRecentPaymentsTable({ payments }) {
  return (
    <TableShell label="Recent recorded payment table; scroll horizontally for all columns" caption="Recent recorded payments">
      <table className="min-w-[900px] w-full border-collapse text-left"><caption className="sr-only">Recent recorded payments</caption>
        <thead className="border-b border-white/10 bg-slate-950/35 text-xs uppercase tracking-wide text-slate-400"><tr><th scope="col" className="px-4 py-3 sm:px-5">Payment ID</th><th scope="col" className="px-4 py-3 sm:px-5">User ID</th><th scope="col" className="px-4 py-3 sm:px-5">Recorded amount</th><th scope="col" className="px-4 py-3 sm:px-5">Type</th><th scope="col" className="px-4 py-3 sm:px-5">Status</th><th scope="col" className="px-4 py-3 sm:px-5">Created</th></tr></thead>
        <tbody className="divide-y divide-white/10">{payments.map((payment) => <tr key={payment.id} className="transition-colors hover:bg-cyan-300/[0.035]"><Cell className="font-mono text-cyan-100">{payment.id}</Cell><Cell className="font-mono">{payment.user_id}</Cell><Cell><span className="font-mono text-sm text-slate-100">{adminInsightDisplay(payment.amount)} <span className="text-slate-400">{adminInsightDisplay(payment.currency, "Currency unavailable")}</span></span></Cell><Cell><Pill>{adminInsightCode(payment.payment_type)}</Pill></Cell><Cell><Pill>{adminInsightCode(payment.status)}</Pill></Cell><Cell><CalendarCell value={payment.created_at} /></Cell></tr>)}</tbody>
      </table>
    </TableShell>
  );
}

export function AdminInsightDailyTable({ rows }) {
  return (
    <TableShell label="UTC daily record-creation counts; scroll horizontally for all columns" caption="UTC daily record-creation counts">
      <table className="min-w-[620px] w-full border-collapse text-left"><caption className="sr-only">UTC daily record-creation counts</caption>
        <thead className="border-b border-white/10 bg-slate-950/35 text-xs uppercase tracking-wide text-slate-400"><tr><th scope="col" className="px-4 py-3 sm:px-5">UTC day</th><th scope="col" className="px-4 py-3 text-right sm:px-5">Users created</th><th scope="col" className="px-4 py-3 text-right sm:px-5">Challenges created</th><th scope="col" className="px-4 py-3 text-right sm:px-5">Payments created</th></tr></thead>
        <tbody className="divide-y divide-white/10">{rows.map((row) => <tr key={row.date} className="transition-colors hover:bg-cyan-300/[0.035]"><Cell><time dateTime={row.date}>{row.date}</time></Cell><Cell className="text-right font-mono">{adminInsightCount(row.users)}</Cell><Cell className="text-right font-mono">{adminInsightCount(row.challenges)}</Cell><Cell className="text-right font-mono">{adminInsightCount(row.payments)}</Cell></tr>)}</tbody>
      </table>
    </TableShell>
  );
}

export function AdminInsightSectionTitle({ id, icon = "users", title, description, action }) {
  const Icon = icon === "activity" ? BarChart3 : Users;
  return <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><h2 id={id} className="mep-heading flex items-center gap-2 text-xl font-bold text-white"><Icon className="h-5 w-5 text-cyan-300" aria-hidden="true" />{title}</h2><p className="mt-1 text-sm leading-6 text-slate-400">{description}</p></div>{action}</div>;
}
