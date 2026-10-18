import { useCallback, useMemo, useState } from "react";
import useAuthStore from "../../store/authStore.js";
import { ROLES } from "../../constants/roles.js";
import {
  createAdminPaymentRecordViewService,
} from "../../services/adminPaymentRecordViewService.js";
import useAdminPaymentRead from "../../hooks/useAdminPaymentRead.js";
import {
  AdminPaymentBoundary,
  AdminPaymentPagination,
  AdminPaymentReadState,
  ApprovalAccessRestricted,
  ApprovalRequestsTable,
  adminPaymentButton,
} from "../../components/admin/AdminPaymentRecordUI.jsx";

const approvalService = createAdminPaymentRecordViewService();

export function PaymentApprovalsContent({ read, onPage }) {
  const requests = read.value?.requests || [];
  return (
    <div className="space-y-5 p-4 sm:p-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Read-only record view</p>
          <h1 className="mep-heading mt-2 text-2xl font-bold text-white sm:text-3xl">Pending legacy payment requests</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">
            Pending legacy requests are displayed without a settlement or review action.
          </p>
        </div>
        <button type="button" className={adminPaymentButton} onClick={read.refresh} disabled={read.loading}>
          Refresh records
        </button>
      </header>

      <AdminPaymentBoundary />

      <div className="rounded-2xl border border-cyan-300/20 bg-cyan-300/[0.05] px-4 py-3 text-sm text-cyan-100" role="status">
        Server filter: pending only. The server retains authority over platform-root scope and record visibility.
      </div>

      <AdminPaymentReadState
        loading={read.loading}
        error={read.error}
        onRetry={read.refresh}
        empty={!read.loading && !read.error && read.value && requests.length === 0}
        emptyTitle="No pending legacy requests"
        emptyMessage="The server returned no pending legacy requests for this page. This does not confirm that there are no settlement obligations."
      />

      {!read.loading && !read.error && read.value && requests.length > 0 && (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-2 px-1 text-sm text-slate-300" aria-live="polite">
            <p>Showing {requests.length} pending {requests.length === 1 ? "row" : "rows"} on this page.</p>
            <p>{read.value.pagination.total} total pending {read.value.pagination.total === 1 ? "request" : "requests"}.</p>
          </div>
          <ApprovalRequestsTable requests={requests} />
        </>
      )}
      {!read.loading && !read.error && read.value && (
        <AdminPaymentPagination pagination={read.value.pagination} onPage={onPage} disabled={read.loading} />
      )}
    </div>
  );
}

function SupermasterApprovalRead({ isAuthenticated, userId, tenantId, role }) {
  const [page, setPage] = useState(1);
  const queryKey = useMemo(() => JSON.stringify(["approval-requests", "pending", page]), [page]);
  const load = useCallback(
    (expectedOwner, signal) => approvalService.loadApprovalRequests({
      expectedOwner,
      role,
      signal,
      page,
    }),
    [page, role],
  );
  const read = useAdminPaymentRead({
    isAuthenticated,
    userId,
    tenantId,
    role,
    queryKey,
    load,
  });
  const onPage = useCallback((nextPage) => setPage(nextPage), []);
  return <PaymentApprovalsContent read={read} onPage={onPage} />;
}

export default function PaymentApprovals() {
  const { user, isAuthenticated } = useAuthStore();
  const role = user?.role;

  // A master must see the restriction without attempting the supermaster-only endpoint.
  if (role !== ROLES.SUPERMASTER) return <ApprovalAccessRestricted />;

  return (
    <SupermasterApprovalRead
      isAuthenticated={isAuthenticated}
      userId={user?.id}
      tenantId={user?.tenant_id}
      role={role}
    />
  );
}
