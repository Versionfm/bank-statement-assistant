import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  getReport,
  listReportTransactions,
  type MonthlyReport,
  type ReportFilters,
  type ReportGroup,
  type ReportResponse,
  type ReportTransactionPage,
} from "../api/reports";
import type { Statement } from "../api/statements";

interface ReportsPageProps {
  statements: Statement[];
}

const COLORS = ["#48c7ad", "#f0a35b", "#ef6f61", "#8e9df5", "#c7d96b"];
const CATEGORIES = [
  "Groceries",
  "Restaurants & Cafes",
  "Housing",
  "Utilities",
  "Transport",
  "Health",
  "Insurance",
  "Subscriptions",
  "Shopping",
  "Leisure",
  "Travel",
  "Education",
  "Gifts & Donations",
  "Taxes",
  "Other Expense",
  "Salary",
  "Interest",
  "Other Income",
  "Bank Fees",
];

export function ReportsPage({ statements }: ReportsPageProps) {
  const [filters, setFilters] = useState<ReportFilters>({ currency: "EUR" });
  const [draft, setDraft] = useState(filters);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [selectedMonth, setSelectedMonth] = useState<MonthlyReport | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [drilldown, setDrilldown] = useState<{
    group: ReportGroup;
    value: string;
    page: ReportTransactionPage | null;
    loading: boolean;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    let active = true;
    void getReport(filters)
      .then((value) => {
        if (active) {
          setReport(value);
          setSelectedMonth((current) =>
            current
              ? (value.months.find((item) => item.month === current.month) ??
                value.months[0] ??
                null)
              : (value.months[0] ?? null),
          );
          setError(null);
        }
      })
      .catch((reason: unknown) => {
        if (active)
          setError(
            reason instanceof Error ? reason.message : "Unable to load reports",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [filters]);

  const trend = useMemo(
    () =>
      [...(report?.months ?? [])].reverse().map((month) => ({
        month: month.month,
        income: Number(month.totals.income),
        spending: Number(month.totals.net_spending),
      })),
    [report],
  );
  const categories =
    selectedMonth?.category_breakdown.slice(0, 5).map((item) => ({
      name: item.label,
      value: Number(item.amount),
    })) ?? [];

  function applyFilters(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setFilters({ ...draft });
  }

  async function openDrilldown(group: ReportGroup, value: string, offset = 0) {
    setDrilldown((current) => ({
      group,
      value,
      page: offset === 0 ? null : (current?.page ?? null),
      loading: true,
      error: null,
    }));
    try {
      const page = await listReportTransactions({
        ...filters,
        monthFrom: selectedMonth?.month ?? filters.monthFrom,
        monthTo: selectedMonth?.month ?? filters.monthTo,
        group,
        value,
        offset,
      });
      setDrilldown({ group, value, page, loading: false, error: null });
    } catch (reason: unknown) {
      setDrilldown({
        group,
        value,
        page: null,
        loading: false,
        error:
          reason instanceof Error
            ? reason.message
            : "Unable to load transactions",
      });
    }
  }

  return (
    <main className="reports-page" id="main">
      <section className="reports-heading">
        <div>
          <p className="eyebrow">Financial intelligence</p>
          <h1>Reports</h1>
          <p className="reports-lede">
            A live view of finalized effective values, organized by booking
            month.
          </p>
        </div>
        <span className="report-currency">{filters.currency ?? "EUR"}</span>
      </section>

      <form className="report-filters" onSubmit={applyFilters}>
        <label>
          From month
          <input
            type="month"
            value={draft.monthFrom ?? ""}
            onChange={(event) =>
              setDraft({ ...draft, monthFrom: event.target.value || undefined })
            }
          />
        </label>
        <label>
          To month
          <input
            type="month"
            value={draft.monthTo ?? ""}
            onChange={(event) =>
              setDraft({ ...draft, monthTo: event.target.value || undefined })
            }
          />
        </label>
        <label>
          Statement
          <select
            value={draft.statementId ?? ""}
            onChange={(event) =>
              setDraft({
                ...draft,
                statementId: event.target.value || undefined,
              })
            }
          >
            <option value="">All statements</option>
            {statements.map((statement) => (
              <option key={statement.id} value={statement.id}>
                {statement.original_filename}
              </option>
            ))}
          </select>
        </label>
        <label>
          Category
          <select
            value={draft.reportingCategory ?? ""}
            onChange={(event) =>
              setDraft({
                ...draft,
                reportingCategory: event.target.value || undefined,
              })
            }
          >
            <option value="">All categories</option>
            {CATEGORIES.map((category) => (
              <option key={category}>{category}</option>
            ))}
          </select>
        </label>
        <label>
          Reporting currency
          <input
            maxLength={3}
            value={draft.currency ?? "EUR"}
            onChange={(event) =>
              setDraft({ ...draft, currency: event.target.value.toUpperCase() })
            }
          />
        </label>
        <label className="report-filter-check">
          <input
            type="checkbox"
            checked={draft.includeProvisional !== false}
            onChange={(event) =>
              setDraft({ ...draft, includeProvisional: event.target.checked })
            }
          />{" "}
          Include provisional
        </label>
        <button type="submit">Apply filters</button>
      </form>

      {loading && (
        <p className="report-status" role="status">
          Calculating report…
        </p>
      )}
      {error && (
        <p className="report-error" role="alert">
          {error}
        </p>
      )}
      {report && (
        <>
          <section className="report-kpis" aria-label="Global report">
            <Kpi
              label="Income"
              value={report.overview.totals.income}
              tone="income"
              currency={filters.currency ?? "EUR"}
            />
            <Kpi
              label="Gross spending"
              value={report.overview.totals.gross_spending}
              tone="spending"
              currency={filters.currency ?? "EUR"}
            />
            <Kpi
              label="Refunds"
              value={report.overview.totals.refunds}
              tone="income"
              currency={filters.currency ?? "EUR"}
            />
            <Kpi
              label="Net spending"
              value={report.overview.totals.net_spending}
              tone="spending"
              currency={filters.currency ?? "EUR"}
            />
            <Kpi
              label="Net cash flow"
              value={report.overview.totals.net_cash_flow}
              tone="flow"
              currency={filters.currency ?? "EUR"}
            />
            <Kpi
              label="Transfer in"
              value={report.overview.totals.transfer_in}
              tone="income"
              currency={filters.currency ?? "EUR"}
            />
            <Kpi
              label="Transfer out"
              value={report.overview.totals.transfer_out}
              tone="spending"
              currency={filters.currency ?? "EUR"}
            />
            <Kpi
              label="Net account flow"
              value={report.overview.totals.net_account_flow}
              tone="flow"
              currency={filters.currency ?? "EUR"}
            />
            <Kpi
              label="Period change"
              value={report.overview.previous_period_change ?? "—"}
              tone="neutral"
              currency={filters.currency ?? "EUR"}
            />
          </section>
          {report.months.some((month) => month.quality.is_provisional) && (
            <p className="report-warning" role="status">
              Provisional data included:{" "}
              {report.months.reduce(
                (total, month) => total + month.quality.provisional_count,
                0,
              )}{" "}
              transactions are not fully finalized.
            </p>
          )}
          <section className="report-chart-grid" aria-label="Global trends">
            <article className="report-panel report-panel--wide">
              <div className="panel-heading">
                <h2>Cash flow trend</h2>
                <span>{filters.currency ?? "EUR"}</span>
              </div>
              <div className="chart-frame">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={trend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#31484d" />
                    <XAxis dataKey="month" stroke="#9eb0ae" />
                    <YAxis stroke="#9eb0ae" />
                    <Tooltip
                      contentStyle={{
                        background: "#172b31",
                        border: "1px solid #406067",
                      }}
                    />
                    <Bar
                      dataKey="income"
                      fill="#48c7ad"
                      radius={[5, 5, 0, 0]}
                    />
                    <Bar
                      dataKey="spending"
                      fill="#ef6f61"
                      radius={[5, 5, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </article>
            <article className="report-panel">
              <div className="panel-heading">
                <h2>Top categories</h2>
                <span>{selectedMonth?.month ?? "Select a month"}</span>
              </div>
              {categories.length > 0 ? (
                <div className="chart-frame chart-frame--donut">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={categories}
                        dataKey="value"
                        nameKey="name"
                        innerRadius={55}
                        outerRadius={86}
                        paddingAngle={3}
                      >
                        {categories.map((item, index) => (
                          <Cell
                            key={item.name}
                            fill={COLORS[index % COLORS.length]}
                          />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{
                          background: "#172b31",
                          border: "1px solid #406067",
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="panel-empty">
                  Open a monthly report to see category mix.
                </p>
              )}
            </article>
          </section>
          <section className="monthly-section">
            <div className="section-heading section-heading--report">
              <div>
                <p className="eyebrow">Timeline</p>
                <h2>Monthly reports</h2>
              </div>
              <span>{report.months.length} months</span>
            </div>
            <div className="monthly-grid">
              {report.months.map((month) => (
                <button
                  className={`month-card ${selectedMonth?.month === month.month ? "month-card--selected" : ""}`}
                  key={month.month}
                  type="button"
                  onClick={() => setSelectedMonth(month)}
                >
                  <span>{formatMonth(month.month)}</span>
                  <strong>
                    {filters.currency ?? "EUR"} {month.totals.net_spending}
                  </strong>
                  <small>
                    Cash flow {filters.currency ?? "EUR"}{" "}
                    {month.totals.net_cash_flow}
                  </small>
                  <em>
                    {month.quality.unresolved_count > 0
                      ? `${month.quality.unresolved_count} need review`
                      : "Finalized"}
                  </em>
                </button>
              ))}
            </div>
          </section>
          {selectedMonth && (
            <MonthlyDetail
              month={selectedMonth}
              onClose={() => setSelectedMonth(null)}
              currency={filters.currency ?? "EUR"}
              onDrilldown={openDrilldown}
            />
          )}
          {drilldown && (
            <ReportDrilldown
              drilldown={drilldown}
              onClose={() => setDrilldown(null)}
              onPage={(offset) =>
                void openDrilldown(drilldown.group, drilldown.value, offset)
              }
            />
          )}
          {report.non_eur.length > 0 && (
            <section className="non-eur-panel">
              <h2>Non-EUR activity</h2>
              <p className="non-eur-note">
                Excluded from {filters.currency ?? "EUR"} totals and shown
                separately.
              </p>
              <ul className="largest-list">
                {report.non_eur_transactions.slice(0, 10).map((item) => (
                  <li key={item.id}>
                    <span>
                      {item.description} · {item.currency}
                    </span>
                    <strong>
                      {item.currency} {item.amount}
                    </strong>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </main>
  );
}

function Kpi({
  label,
  value,
  tone,
  currency,
}: {
  label: string;
  value: string;
  tone: string;
  currency: string;
}) {
  return (
    <article className={`report-kpi report-kpi--${tone}`}>
      <span>{label}</span>
      <strong>
        {currency} {value}
      </strong>
    </article>
  );
}

function MonthlyDetail({
  month,
  onClose,
  currency,
  onDrilldown,
}: {
  month: MonthlyReport;
  onClose: () => void;
  currency: string;
  onDrilldown: (group: ReportGroup, value: string) => void;
}) {
  return (
    <section className="monthly-detail" aria-labelledby="monthly-detail-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Expanded report</p>
          <h2 id="monthly-detail-title">{formatMonth(month.month)}</h2>
        </div>
        <button className="secondary-button" type="button" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="detail-columns">
        <div>
          <h3>Largest transactions</h3>
          <ul className="largest-list">
            {month.largest_transactions.slice(0, 5).map((item) => (
              <li key={item.id}>
                <span>{item.description}</span>
                <strong>
                  {currency} {item.amount}
                </strong>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Category breakdown</h3>
          <ul className="largest-list">
            {month.category_breakdown.map((item) => (
              <li key={item.label}>
                <button
                  className="breakdown-link"
                  type="button"
                  onClick={() => onDrilldown("category", item.label)}
                >
                  <span>{item.label}</span>
                  <strong>
                    {currency} {item.amount}
                  </strong>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Counterparties</h3>
          <ul className="largest-list">
            {month.counterparty_breakdown.map((item) => (
              <li key={item.label}>
                <button
                  className="breakdown-link"
                  type="button"
                  onClick={() => onDrilldown("counterparty", item.label)}
                >
                  <span>{item.label}</span>
                  <strong>
                    {currency} {item.amount}
                  </strong>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Payment channels</h3>
          <ul className="largest-list">
            {month.payment_channel_breakdown.map((item) => (
              <li key={item.label}>
                <button
                  className="breakdown-link"
                  type="button"
                  onClick={() => onDrilldown("payment_channel", item.label)}
                >
                  <span>{item.label}</span>
                  <strong>
                    {currency} {item.amount}
                  </strong>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Quality</h3>
          <p className="quality-callout">
            {month.quality.unresolved_count} unresolved · {currency}{" "}
            {month.quality.unresolved_amount}
          </p>
          <p>
            {month.transfers.count} transfers · {currency}{" "}
            {month.transfers.total} excluded from spending.
          </p>
          <button
            className="breakdown-link"
            type="button"
            onClick={() => onDrilldown("transfer_direction", "in")}
          >
            <span>Transfer in</span>
            <strong>
              {currency} {month.transfers.incoming}
            </strong>
          </button>
          <button
            className="breakdown-link"
            type="button"
            onClick={() => onDrilldown("transfer_direction", "out")}
          >
            <span>Transfer out</span>
            <strong>
              {currency} {month.transfers.outgoing}
            </strong>
          </button>
          <button
            className="breakdown-link"
            type="button"
            onClick={() => onDrilldown("transfer_scope", "own_account")}
          >
            <span>Own account</span>
            <strong>
              {currency} {month.transfers.own_account_total}
            </strong>
          </button>
          <button
            className="breakdown-link"
            type="button"
            onClick={() => onDrilldown("transfer_scope", "external_party")}
          >
            <span>External party</span>
            <strong>
              {currency} {month.transfers.external_total}
            </strong>
          </button>
          <button
            className="breakdown-link"
            type="button"
            onClick={() => onDrilldown("transfer_scope", "unknown")}
          >
            <span>Unknown / review</span>
            <strong>
              {currency} {month.transfers.unknown_total}
            </strong>
          </button>
        </div>
      </div>
    </section>
  );
}

function ReportDrilldown({
  drilldown,
  onClose,
  onPage,
}: {
  drilldown: DrilldownState;
  onClose: () => void;
  onPage: (offset: number) => void;
}) {
  return (
    <section className="report-drilldown" aria-labelledby="drilldown-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Transaction detail</p>
          <h2 id="drilldown-title">{drilldown.value}</h2>
        </div>
        <button className="secondary-button" type="button" onClick={onClose}>
          Close
        </button>
      </div>
      {drilldown.loading && (
        <p className="report-status" role="status">
          Loading transactions…
        </p>
      )}
      {drilldown.error && (
        <p className="report-error" role="alert">
          {drilldown.error}
        </p>
      )}
      {drilldown.page && (
        <>
          <p className="non-eur-note">
            {drilldown.page.total} matching transactions
          </p>
          <ul className="largest-list">
            {drilldown.page.items.map((item) => (
              <li key={item.id}>
                <span>
                  {item.booking_date} · {item.description}
                  {item.transfer_scope ? ` · ${item.transfer_scope}` : ""}
                </span>
                <strong>
                  {item.currency} {item.signed_amount}
                </strong>
              </li>
            ))}
          </ul>
          {drilldown.page.total > drilldown.page.limit && (
            <div className="drilldown-pagination">
              <button
                className="secondary-button"
                type="button"
                disabled={drilldown.page.offset === 0 || drilldown.loading}
                onClick={() =>
                  onPage(drilldown.page!.offset - drilldown.page!.limit)
                }
              >
                Previous
              </button>
              <span>
                {drilldown.page.offset + 1}–
                {Math.min(
                  drilldown.page.offset + drilldown.page.items.length,
                  drilldown.page.total,
                )}
              </span>
              <button
                className="secondary-button"
                type="button"
                disabled={
                  drilldown.page.offset + drilldown.page.items.length >=
                    drilldown.page.total || drilldown.loading
                }
                onClick={() =>
                  onPage(drilldown.page!.offset + drilldown.page!.limit)
                }
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

type DrilldownState = {
  group: ReportGroup;
  value: string;
  page: ReportTransactionPage | null;
  loading: boolean;
  error: string | null;
};

function formatMonth(value: string) {
  const [year, month] = value.split("-");
  return new Date(Number(year), Number(month) - 1).toLocaleDateString(
    undefined,
    { month: "long", year: "numeric" },
  );
}
