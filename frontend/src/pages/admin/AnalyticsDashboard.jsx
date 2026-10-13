import { useCallback, useMemo, useState } from "react";
import useAuthStore from "../../store/authStore.js";
import { ADMIN_INSIGHT_DAYS, loadAdminInsight } from "../../services/adminInsightViewService.js";
import useAdminInsightRead from "../../hooks/useAdminInsightRead.js";
import {
  AdminInsightBoundary,
  AdminInsightCountCards,
  AdminInsightDailyTable,
  AdminInsightDistribution,
  AdminInsightReadState,
  AdminInsightSectionTitle,
  adminInsightButton,
} from "../../components/admin/AdminInsightUI.jsx";
import { AdminInsightQuickLinks } from "./AdminDashboardConnected.jsx";

const dayLabels = { 7: "Last 7 UTC calendar days", 30: "Last 30 UTC calendar days", 90: "Last 90 UTC calendar days", 180: "Last 180 UTC calendar days", 365: "Last 365 UTC calendar days" };

export function AnalyticsDashboardInsightContent({ read, days, onDaysChange }) {
  const insight = read.value;
  const isEmpty = Boolean(insight && insight.counts.users === 0 && insight.counts.challenges === 0 && insight.counts.payments === 0);
  return (
    <div className="space-y-5 p-4 sm:p-6">
      <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Administrator record view</p>
          <h1 className="mep-heading mt-2 text-2xl font-bold text-white sm:text-3xl">Recorded activity by UTC day</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">Daily counts show record creation only. Recorded status distributions are current values within the selected bounded scope, not status-transition events.</p>
        </div>
        <button type="button" className={adminInsightButton} onClick={read.refresh} disabled={read.loading}>Refresh records</button>
      </header>
      <AdminInsightQuickLinks current="/admin/analytics" />
      <section className="mep-panel rounded-2xl border p-4 sm:p-5" aria-labelledby="analytics-scope-title">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div><h2 id="analytics-scope-title" className="mep-heading text-base font-semibold text-white">UTC calendar-day scope</h2><p className="mt-1 text-sm leading-6 text-slate-400">The server returns every day in this bounded UTC range, including recorded zero counts.</p></div>
          <div className="w-full sm:w-auto"><label htmlFor="admin-insight-days" className="mb-2 block text-sm font-medium text-slate-200">Days</label><select id="admin-insight-days" value={days} onChange={(event) => onDaysChange(Number(event.target.value))} className="w-full rounded-xl border border-white/15 bg-slate-950/50 px-3 py-2.5 text-sm text-white outline-none transition focus-visible:ring-2 focus-visible:ring-cyan-300 sm:min-w-64">{ADMIN_INSIGHT_DAYS.map((value) => <option key={value} value={value}>{dayLabels[value]}</option>)}</select></div>
        </div>
      </section>
      {insight && <AdminInsightBoundary asOf={insight.asOf} analytics />}
      <AdminInsightReadState
        loading={read.loading}
        error={read.error}
        onRetry={read.refresh}
        empty={isEmpty}
        emptyTitle="No records were created in this UTC range"
        emptyMessage="The server returned zero recorded users, challenges, and payments in the selected UTC calendar-day scope. This does not establish a financial, settlement, identity, or entitlement result."
      />
      {!read.loading && !read.error && insight && !isEmpty && <>
        <AdminInsightCountCards counts={insight.counts} />
        <section className="grid gap-5 lg:grid-cols-2" aria-label="Current recorded statuses in selected scope">
          <AdminInsightDistribution title="User roles" rows={insight.distributions.userRoles} description="Current recorded role values among records created in the selected scope." />
          <AdminInsightDistribution title="Recorded KYC statuses" rows={insight.distributions.userKyc} description="Current recorded KYC status only; it is not provider verification evidence." />
          <AdminInsightDistribution title="Challenge statuses" rows={insight.distributions.challengeStatus} description="Current recorded statuses, not challenge status-transition events." />
          <AdminInsightDistribution title="Payment statuses" rows={insight.distributions.paymentStatus} description="Current recorded statuses, not payment completion or settlement events." />
        </section>
        <section className="space-y-3" aria-labelledby="daily-record-creation-title">
          <AdminInsightSectionTitle id="daily-record-creation-title" icon="activity" title="Daily record creation" description="Each row is a UTC calendar day. Counts represent records created on that day; zero is shown only when returned by the server." />
          <AdminInsightDailyTable rows={insight.dailyActivity} />
        </section>
      </>}
    </div>
  );
}

export default function AnalyticsDashboard() {
  const { user, isAuthenticated } = useAuthStore();
  const [days, setDays] = useState(30);
  const role = user?.role;
  const load = useCallback((expectedOwner, signal) => loadAdminInsight({ kind: "analytics", expectedOwner, days, signal }), [days]);
  const queryDays = useMemo(() => days, [days]);
  const read = useAdminInsightRead({
    isAuthenticated,
    userId: user?.id,
    tenantId: user?.tenant_id,
    role,
    kind: "analytics",
    days: queryDays,
    load,
  });
  return <AnalyticsDashboardInsightContent read={read} days={days} onDaysChange={setDays} />;
}
