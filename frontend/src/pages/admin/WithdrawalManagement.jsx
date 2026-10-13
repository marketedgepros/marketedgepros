import { useCallback, useMemo, useState } from "react";
import { LayoutDashboard, RefreshCw, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import useAuthStore from "../../store/authStore.js";
import useFinancialRecordRead from "../../hooks/useFinancialRecordRead.js";
import {
  createFinancialRecordViewService,
  FINANCIAL_RECORD_PAGE_SIZE,
  FINANCIAL_WITHDRAWAL_STATUSES,
  financialRecordError,
} from "../../services/financialRecordViewService.js";
import {
  financialButton,
  financialDate,
  financialPanel,
  FinancialExactAmount,
  FinancialPagination,
  FinancialReadState,
  FinancialRecordBoundary,
  FinancialStatusPill,
} from "../../components/financial/FinancialRecordUI.jsx";

const statusLabel = (value) => value.charAt(0).toUpperCase() + value.slice(1);

export function AdminWithdrawalsView({
  view,
  status,
  onStatus,
  onPage,
  refreshing,
}) {
  if (!view || view.kind !== "admin-withdrawals") return null;
  const { withdrawals, pagination } = view;
  return (
    <>
      <FinancialRecordBoundary />
      <section
        aria-labelledby="admin-withdrawals-heading"
        className={`mt-6 ${financialPanel} overflow-hidden`}
      >
        <div className="flex flex-col gap-4 border-b border-white/10 p-5 sm:flex-row sm:items-end sm:justify-between sm:p-6">
          <div className="min-w-0">
            <h2
              id="admin-withdrawals-heading"
              className="mep-heading text-xl font-semibold text-white"
            >
              Scoped withdrawal records
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-400">
              Operational user IDs identify records only. No customer contact
              details, payment details, or workflow controls are displayed.
            </p>
          </div>
          <div className="min-w-[12rem]">
            <label
              htmlFor="admin-withdrawal-status"
              className="mb-1.5 block text-sm font-medium text-slate-200"
            >
              Recorded status
            </label>
            <select
              id="admin-withdrawal-status"
              value={status ?? ""}
              onChange={(event) => onStatus(event.target.value || null)}
              disabled={refreshing}
              className="w-full rounded-lg border border-white/15 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <option value="">All recorded statuses</option>
              {FINANCIAL_WITHDRAWAL_STATUSES.map((item) => (
                <option key={item} value={item}>
                  {statusLabel(item)}
                </option>
              ))}
            </select>
          </div>
        </div>
        {withdrawals.length === 0 ? (
          <div className="px-5 py-12 text-center sm:px-6">
            <h3 className="font-semibold text-slate-100">
              No scoped withdrawal records were returned for this page
            </h3>
            <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-400">
              This is a valid empty record page, not a proof that payments,
              approvals, or payouts are unavailable.
            </p>
          </div>
        ) : (
          <div
            role="region"
            aria-label="Scoped withdrawal records table"
            tabIndex="0"
            className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-cyan-200"
          >
            <table className="w-full min-w-[1040px] text-left text-sm">
              <caption className="sr-only">
                Scoped administrative withdrawal records
              </caption>
              <thead className="bg-slate-950/50 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th scope="col" className="px-5 py-3 font-medium sm:px-6">
                    Record ID
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    Operational user ID
                  </th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">
                    Recorded amount
                  </th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">
                    Recorded fee
                  </th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">
                    Recorded net amount
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    Legacy status
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium sm:px-6">
                    Recorded date
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {withdrawals.map((withdrawal) => (
                  <tr
                    key={withdrawal.id}
                    className="align-top transition-colors hover:bg-white/[0.025] motion-reduce:transition-none"
                  >
                    <td className="px-5 py-4 font-mono text-xs text-slate-300 sm:px-6">
                      #{withdrawal.id}
                    </td>
                    <td className="px-5 py-4 font-mono text-xs text-slate-300">
                      {withdrawal.user_id}
                    </td>
                    <td className="px-5 py-4">
                      <FinancialExactAmount
                        value={withdrawal.amount}
                        align="right"
                        label="Recorded withdrawal amount"
                      />
                    </td>
                    <td className="px-5 py-4">
                      <FinancialExactAmount
                        value={withdrawal.fee}
                        align="right"
                        label="Recorded withdrawal fee"
                      />
                    </td>
                    <td className="px-5 py-4">
                      <FinancialExactAmount
                        value={withdrawal.net_amount}
                        align="right"
                        label="Recorded withdrawal net amount"
                      />
                    </td>
                    <td className="px-5 py-4">
                      <FinancialStatusPill status={withdrawal.status} />
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-slate-300 sm:px-6">
                      {financialDate(withdrawal.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <div className="mt-5">
        <FinancialPagination
          pagination={pagination}
          onPage={onPage}
          disabled={refreshing}
          label="Administrative withdrawal pagination"
        />
      </div>
    </>
  );
}

export default function WithdrawalManagement() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const userId = useAuthStore((state) => state.user?.id);
  const tenantId = useAuthStore((state) => state.user?.tenant_id);
  const role = useAuthStore((state) => state.user?.role);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState(null);
  const queryKey = useMemo(
    () => JSON.stringify(["admin-withdrawals", page, status]),
    [page, status],
  );
  const load = useCallback(
    (expectedOwner, signal) =>
      createFinancialRecordViewService().adminWithdrawals({
        expectedOwner,
        role,
        page,
        perPage: FINANCIAL_RECORD_PAGE_SIZE,
        status,
        signal,
      }),
    [page, role, status],
  );
  const read = useFinancialRecordRead({
    isAuthenticated,
    userId,
    tenantId,
    role,
    queryKey,
    load,
  });
  const error = read.error
    ? typeof read.error === "string"
      ? read.error
      : financialRecordError()
    : null;
  const changeStatus = (next) => {
    setPage(1);
    setStatus(next);
  };

  return (
    <div className="min-h-full bg-slate-950 text-white">
      <header className="border-b border-cyan-300/10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-cyan-500/10 via-slate-950 to-slate-950">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">
            Administration
          </p>
          <div className="mt-3 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">
              <h1 className="mep-heading flex items-center gap-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                <ShieldCheck
                  className="h-8 w-8 shrink-0 text-cyan-200"
                  aria-hidden="true"
                />
                Withdrawal records
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
                Review only the server-authorized administrative scope. This
                screen has no approval, rejection, completion, export, or
                payment actions.
              </p>
            </div>
            <nav
              aria-label="Administrative withdrawal navigation"
              className="flex flex-wrap gap-2"
            >
              <Link to="/admin" className={financialButton}>
                <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
                Admin dashboard
              </Link>
            </nav>
          </div>
          <div className="mt-5">
            <button
              type="button"
              onClick={read.refresh}
              disabled={read.loading}
              className={financialButton}
              aria-label="Refresh administrative withdrawal records"
            >
              <RefreshCw
                className={`h-4 w-4 ${read.loading ? "animate-spin motion-reduce:animate-none" : ""}`}
                aria-hidden="true"
              />
              {read.loading ? "Refreshing records" : "Refresh records"}
            </button>
          </div>
        </div>
      </header>
      <div className="mx-auto max-w-7xl px-4 py-7 sm:px-6 lg:px-8">
        {read.loading || error ? (
          <FinancialReadState
            loading={read.loading}
            error={error}
            onRetry={read.refresh}
            recordLabel="administrative withdrawal records"
          />
        ) : (
          <AdminWithdrawalsView
            view={read.value}
            status={status}
            onStatus={changeStatus}
            onPage={setPage}
            refreshing={read.loading}
          />
        )}
      </div>
    </div>
  );
}
