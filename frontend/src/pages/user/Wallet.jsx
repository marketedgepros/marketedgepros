import { useCallback, useMemo, useState } from "react";
import { ArrowRight, FileText, RefreshCw, WalletCards } from "lucide-react";
import { Link } from "react-router-dom";
import useAuthStore from "../../store/authStore.js";
import useFinancialRecordRead from "../../hooks/useFinancialRecordRead.js";
import {
  createFinancialRecordViewService,
  FINANCIAL_BALANCE_TYPES,
  FINANCIAL_RECORD_PAGE_SIZE,
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
  WalletMissingState,
} from "../../components/financial/FinancialRecordUI.jsx";

const balanceLabels = {
  main: "Main balance",
  commission: "Commission balance",
  bonus: "Bonus balance",
};

function WalletNavigation({ role }) {
  return (
    <nav aria-label="Wallet navigation" className="flex flex-wrap gap-2">
      <Link to="/dashboard" className={financialButton}>
        Dashboard
      </Link>
      <Link to="/documents" className={financialButton}>
        <FileText className="h-4 w-4" aria-hidden="true" />
        Documents
      </Link>
      <Link to="/support/my-tickets" className={financialButton}>
        Support
      </Link>
      {role === "trader" && (
        <Link to="/trader/withdrawals" className={financialButton}>
          View withdrawals <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      )}
    </nav>
  );
}

function BalanceCard({ title, value, timestamp }) {
  return (
    <article className={`${financialPanel} p-5`}>
      <p className="text-sm font-medium text-slate-300">{title}</p>
      <FinancialExactAmount value={value} label={title} />
      <p className="mt-3 text-xs leading-5 text-slate-400">
        Recorded legacy balance only; not available for trading or payment.
      </p>
      {timestamp && (
        <p className="mt-2 text-xs text-slate-500">
          Last recorded change: {financialDate(timestamp)}
        </p>
      )}
    </article>
  );
}

export function WalletView({
  view,
  page,
  balanceType,
  onPage,
  onBalanceType,
  onRefresh,
  refreshing,
  role,
}) {
  if (view?.kind === "wallet-missing") return <WalletMissingState />;
  if (!view || view.kind !== "wallet") return null;
  const { wallet } = view.balance;
  const { transactions, pagination } = view.transactions;
  return (
    <>
      <FinancialRecordBoundary />
      <section
        aria-label="Recorded wallet balances"
        className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
      >
        <BalanceCard
          title="Main balance"
          value={wallet.main_balance}
          timestamp={wallet.last_transaction_at}
        />
        <BalanceCard
          title="Commission balance"
          value={wallet.commission_balance}
          timestamp={wallet.last_transaction_at}
        />
        <BalanceCard
          title="Bonus balance"
          value={wallet.bonus_balance}
          timestamp={wallet.last_transaction_at}
        />
      </section>
      <section
        aria-labelledby="wallet-transactions-heading"
        className={`mt-6 ${financialPanel} overflow-hidden`}
      >
        <div className="flex flex-col gap-4 border-b border-white/10 p-5 sm:flex-row sm:items-end sm:justify-between sm:p-6">
          <div className="min-w-0">
            <h2
              id="wallet-transactions-heading"
              className="mep-heading text-xl font-semibold text-white"
            >
              Recorded wallet transactions
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-400">
              A bounded legacy record page. Transaction amounts are exact
              strings; no currency or availability is inferred.
            </p>
          </div>
          <div className="min-w-[12rem]">
            <label
              htmlFor="wallet-balance-type"
              className="mb-1.5 block text-sm font-medium text-slate-200"
            >
              Balance type
            </label>
            <select
              id="wallet-balance-type"
              value={balanceType ?? ""}
              onChange={(event) => onBalanceType(event.target.value || null)}
              disabled={refreshing}
              className="w-full rounded-lg border border-white/15 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <option value="">All balance types</option>
              {FINANCIAL_BALANCE_TYPES.map((type) => (
                <option key={type} value={type}>
                  {balanceLabels[type]}
                </option>
              ))}
            </select>
          </div>
        </div>
        {transactions.length === 0 ? (
          <div className="px-5 py-12 text-center sm:px-6">
            <h3 className="font-semibold text-slate-100">
              No wallet transactions were returned for this page
            </h3>
            <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-400">
              This valid empty page does not replace a missing wallet, zero
              balance, or payment decision.
            </p>
          </div>
        ) : (
          <div
            role="region"
            aria-label="Recorded wallet transactions table"
            tabIndex="0"
            className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-cyan-200"
          >
            <table className="w-full min-w-[860px] text-left text-sm">
              <caption className="sr-only">
                Recorded wallet transactions for the signed-in account
              </caption>
              <thead className="bg-slate-950/50 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th scope="col" className="px-5 py-3 font-medium sm:px-6">
                    Record ID
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    Type
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium">
                    Balance type
                  </th>
                  <th scope="col" className="px-5 py-3 text-right font-medium">
                    Recorded amount
                  </th>
                  <th scope="col" className="px-5 py-3 font-medium sm:px-6">
                    Recorded date
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {transactions.map((transaction) => (
                  <tr
                    key={transaction.id}
                    className="align-top transition-colors hover:bg-white/[0.025] motion-reduce:transition-none"
                  >
                    <td className="px-5 py-4 font-mono text-xs text-slate-300 sm:px-6">
                      #{transaction.id}
                    </td>
                    <td className="max-w-[12rem] break-words px-5 py-4 text-slate-200">
                      {transaction.type}
                    </td>
                    <td className="px-5 py-4 text-slate-300">
                      {balanceLabels[transaction.balance_type]}
                    </td>
                    <td className="px-5 py-4 sm:px-6">
                      <FinancialExactAmount
                        value={transaction.amount}
                        align="right"
                        label="Recorded transaction amount"
                      />
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-slate-300">
                      {financialDate(transaction.created_at)}
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
          label="Wallet transaction pagination"
        />
      </div>
    </>
  );
}

export default function Wallet() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const userId = useAuthStore((state) => state.user?.id);
  const tenantId = useAuthStore((state) => state.user?.tenant_id);
  const role = useAuthStore((state) => state.user?.role);
  const [page, setPage] = useState(1);
  const [balanceType, setBalanceType] = useState(null);
  const queryKey = useMemo(
    () => JSON.stringify(["wallet", page, balanceType]),
    [balanceType, page],
  );
  const load = useCallback(
    (expectedOwner, signal) =>
      createFinancialRecordViewService().wallet({
        expectedOwner,
        role,
        page,
        perPage: FINANCIAL_RECORD_PAGE_SIZE,
        balanceType,
        signal,
      }),
    [balanceType, page, role],
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
  const changeFilter = (next) => {
    setPage(1);
    setBalanceType(next);
  };

  return (
    <div className="min-h-full bg-slate-950 text-white">
      <header className="border-b border-cyan-300/10 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-cyan-500/10 via-slate-950 to-slate-950">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">
            Account records
          </p>
          <div className="mt-3 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">
              <h1 className="mep-heading flex items-center gap-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                <WalletCards
                  className="h-8 w-8 shrink-0 text-cyan-200"
                  aria-hidden="true"
                />
                Wallet records
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
                Review legacy wallet records without treating them as verified
                money, a trading balance, or a payment source.
              </p>
            </div>
            <WalletNavigation role={role} />
          </div>
          <div className="mt-5">
            <button
              type="button"
              onClick={read.refresh}
              disabled={read.loading}
              className={financialButton}
              aria-label="Refresh wallet records"
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
            recordLabel="wallet records"
          />
        ) : (
          <WalletView
            view={read.value}
            page={page}
            balanceType={balanceType}
            onPage={setPage}
            onBalanceType={changeFilter}
            onRefresh={read.refresh}
            refreshing={read.loading}
            role={role}
          />
        )}
      </div>
    </div>
  );
}
