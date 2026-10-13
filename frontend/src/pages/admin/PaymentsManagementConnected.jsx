import { useCallback, useMemo, useState } from "react";
import useAuthStore from "../../store/authStore.js";
import ProgramPurchaseRecords from "../../components/payments/ProgramPurchaseRecords.jsx";
import {
  createAdminPaymentRecordViewService,
} from "../../services/adminPaymentRecordViewService.js";
import useAdminPaymentRead from "../../hooks/useAdminPaymentRead.js";
import {
  AdminPaymentBoundary,
  AdminPaymentPagination,
  AdminPaymentReadState,
  PaymentRecordsTable,
  adminPaymentButton,
  adminPaymentPanel,
} from "../../components/admin/AdminPaymentRecordUI.jsx";

const paymentService = createAdminPaymentRecordViewService();

export function PaymentsManagementContent({ read, status, type, onStatusChange, onTypeChange, onPage, purchaseRecords = null }) {
  const payments = read.value?.payments || [];
  return (
    <div className="space-y-5 p-4 sm:p-6">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">Read-only record view</p>
        <h1 className="mep-heading mt-2 text-2xl font-bold text-white sm:text-3xl">Recorded payment records</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">
          Browse server-scoped legacy payment records. Values are not converted, aggregated, or treated as settlement evidence.
        </p>
      </header>

      <AdminPaymentBoundary />

      <section className={adminPaymentPanel} aria-labelledby="payment-record-filters-heading">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 id="payment-record-filters-heading" className="mep-heading text-base font-semibold text-white">Record filters</h2>
            <p className="mt-1 text-sm text-slate-400">Filters are applied by the server to this page of records.</p>
          </div>
          <button type="button" className={adminPaymentButton} onClick={read.refresh} disabled={read.loading}>
            Refresh records
          </button>
        </div>
        <div className="mt-5 grid max-w-2xl gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="payment-record-status" className="mb-2 block text-sm font-medium text-slate-200">Status</label>
            <select
              id="payment-record-status"
              value={status || ""}
              onChange={(event) => onStatusChange(event.target.value || null)}
              className="w-full rounded-xl border border-white/15 bg-slate-950/50 px-3 py-2.5 text-sm text-white outline-none transition focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              <option value="">All statuses</option>
              <option value="pending">Pending</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="refunded">Refunded</option>
            </select>
          </div>
          <div>
            <label htmlFor="payment-record-purpose" className="mb-2 block text-sm font-medium text-slate-200">Purpose</label>
            <select
              id="payment-record-purpose"
              value={type || ""}
              onChange={(event) => onTypeChange(event.target.value || null)}
              className="w-full rounded-xl border border-white/15 bg-slate-950/50 px-3 py-2.5 text-sm text-white outline-none transition focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              <option value="">All purposes</option>
              <option value="challenge_purchase">Challenge purchase</option>
              <option value="withdrawal">Withdrawal</option>
              <option value="refund">Refund</option>
            </select>
          </div>
        </div>
      </section>

      <AdminPaymentReadState
        loading={read.loading}
        error={read.error}
        onRetry={read.refresh}
        empty={!read.loading && !read.error && read.value && payments.length === 0}
        emptyTitle="No recorded payment records"
        emptyMessage="The server returned no recorded payment records for this page and selected filters. This is not a financial conclusion."
      />

      {!read.loading && !read.error && read.value && payments.length > 0 && (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-2 px-1 text-sm text-slate-300" aria-live="polite">
            <p>Showing {payments.length} recorded {payments.length === 1 ? "row" : "rows"} on this page.</p>
            <p>{read.value.pagination.total} total server-scoped {read.value.pagination.total === 1 ? "record" : "records"}.</p>
          </div>
          <PaymentRecordsTable payments={payments} />
        </>
      )}
      {!read.loading && !read.error && read.value && (
        <AdminPaymentPagination pagination={read.value.pagination} onPage={onPage} disabled={read.loading} />
      )}
      {purchaseRecords}
    </div>
  );
}

export default function PaymentsManagementConnected() {
  const { user, isAuthenticated } = useAuthStore();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState(null);
  const [type, setType] = useState(null);
  const userId = user?.id;
  const tenantId = user?.tenant_id;
  const role = user?.role;
  const queryKey = useMemo(() => JSON.stringify(["payments", page, status, type]), [page, status, type]);
  const load = useCallback(
    (expectedOwner, signal) => paymentService.loadPayments({
      expectedOwner,
      role,
      signal,
      page,
      status,
      type,
    }),
    [page, role, status, type],
  );
  const read = useAdminPaymentRead({
    isAuthenticated,
    userId,
    tenantId,
    role,
    queryKey,
    load,
  });
  const onStatusChange = useCallback((nextStatus) => {
    setStatus(nextStatus);
    setPage(1);
  }, []);
  const onTypeChange = useCallback((nextType) => {
    setType(nextType);
    setPage(1);
  }, []);
  const onPage = useCallback((nextPage) => setPage(nextPage), []);

  return (
    <PaymentsManagementContent
      read={read}
      status={status}
      type={type}
      onStatusChange={onStatusChange}
      onTypeChange={onTypeChange}
      onPage={onPage}
      purchaseRecords={<ProgramPurchaseRecords principal={isAuthenticated ? user : null} ownOnly={false} />}
    />
  );
}
