import { useCallback } from "react";
import { Link, useLocation } from "react-router-dom";
import useAuthStore from "../../store/authStore.js";
import { loadAdminInsight } from "../../services/adminInsightViewService.js";
import useAdminInsightRead from "../../hooks/useAdminInsightRead.js";
import {
  AdminInsightBoundary,
  AdminInsightCountCards,
  AdminInsightDistribution,
  AdminInsightReadState,
  AdminInsightRecentPaymentsTable,
  AdminInsightRecentUsersTable,
  AdminInsightSectionTitle,
  adminInsightButton,
} from "../../components/admin/AdminInsightUI.jsx";

const quickLinks = [
  ["Dashboard", "/admin/dashboard"], ["Users", "/admin/users"], ["Challenges", "/admin/challenges"],
  ["KYC approval", "/admin/kyc-approval"], ["Payments", "/admin/payments"], ["Analytics", "/admin/analytics"],
];

export function AdminInsightQuickLinks({ current }) {
  return (
    <nav aria-label="Administrator record views" className="flex max-w-full flex-wrap gap-2">
      {quickLinks.map(([label, href]) => <Link key={href} to={href} aria-current={current === href ? "page" : undefined} className={`rounded-lg border px-3 py-2 text-sm font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 ${current === href ? "border-cyan-300/50 bg-cyan-300/15 text-cyan-100" : "border-white/10 text-slate-300 hover:border-cyan-300/30 hover:text-cyan-100"}`}>{label}</Link>)}
    </nav>
  );
}

export function AdminDashboardInsightContent({ read, currentPath = "/admin/dashboard" }) {
  const insight = read.value;
  const isEmpty = Boolean(insight && insight.counts.users === 0 && insight.counts.challenges === 0 && insight.counts.payments === 0);
  return (
    <div className="space-y-5 p-4 sm:p-6">
      <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Administrator record view</p>
          <h1 className="mep-heading mt-2 text-2xl font-bold text-white sm:text-3xl">Recorded platform overview</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">A server-scoped snapshot of record counts and recorded statuses. It contains no revenue, funding, conversion, ranking, or identity conclusion.</p>
        </div>
        <button type="button" className={adminInsightButton} onClick={read.refresh} disabled={read.loading}>Refresh records</button>
      </header>
      <AdminInsightQuickLinks current={currentPath} />
      {insight && <AdminInsightBoundary asOf={insight.asOf} />}
      <AdminInsightReadState
        loading={read.loading}
        error={read.error}
        onRetry={read.refresh}
        empty={isEmpty}
        emptyTitle="No recorded rows in this snapshot"
        emptyMessage="The server returned zero recorded users, challenges, and payments for this scope. This is a record count only, not a financial, settlement, identity, or entitlement conclusion."
      />
      {!read.loading && !read.error && insight && !isEmpty && <>
        <AdminInsightCountCards counts={insight.counts} />
        <section className="grid gap-5 lg:grid-cols-2" aria-label="Current recorded status counts">
          <AdminInsightDistribution title="User roles" rows={insight.distributions.userRoles} description="Current recorded role values in the snapshot." />
          <AdminInsightDistribution title="Recorded KYC statuses" rows={insight.distributions.userKyc} description="Recorded status values only; they do not prove identity verification." />
          <AdminInsightDistribution title="Challenge statuses" rows={insight.distributions.challengeStatus} description="Current recorded challenge status counts, not activity or funding events." />
          <AdminInsightDistribution title="Payment statuses" rows={insight.distributions.paymentStatus} description="Current recorded payment status counts; no money is summed or converted." />
        </section>
        <section className="space-y-3" aria-labelledby="recent-recorded-users">
          <AdminInsightSectionTitle id="recent-recorded-users" title="Recent recorded users" description="IDs and recorded fields only. Names, email, contact details, and hierarchy are intentionally excluded." />
          <AdminInsightRecentUsersTable users={insight.recentUsers} />
        </section>
        <section className="space-y-3" aria-labelledby="recent-recorded-payments">
          <AdminInsightSectionTitle id="recent-recorded-payments" title="Recent recorded payments" description="Amounts remain exact strings with their recorded currency. They are never summed, converted, or treated as settlement evidence." />
          <AdminInsightRecentPaymentsTable payments={insight.recentPayments} />
        </section>
      </>}
    </div>
  );
}

export default function AdminDashboardConnected() {
  const { user, isAuthenticated } = useAuthStore();
  const location = useLocation();
  const role = user?.role;
  const load = useCallback((expectedOwner, signal) => loadAdminInsight({
    kind: "dashboard", expectedOwner, days: null, signal,
  }), []);
  const read = useAdminInsightRead({
    isAuthenticated,
    userId: user?.id,
    tenantId: user?.tenant_id,
    role,
    kind: "dashboard",
    days: null,
    load,
  });
  return <AdminDashboardInsightContent read={read} currentPath={location.pathname === "/admin" ? "/admin/dashboard" : location.pathname} />;
}
