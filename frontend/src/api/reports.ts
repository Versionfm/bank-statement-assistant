export interface ReportTotals {
  income: string;
  gross_spending: string;
  refunds: string;
  net_spending: string;
  net_cash_flow: string;
  transfer_in: string;
  transfer_out: string;
  net_account_flow: string;
}

export interface BreakdownItem {
  label: string;
  amount: string;
  transaction_count: number;
}

export interface MonthlyReport {
  month: string;
  totals: ReportTotals;
  category_breakdown: BreakdownItem[];
  counterparty_breakdown: BreakdownItem[];
  payment_channel_breakdown: BreakdownItem[];
  largest_transactions: Array<{
    id: string;
    booking_date: string;
    description: string;
    amount: string;
    currency: string;
    counterparty: string | null;
    reporting_category: string | null;
  }>;
  transfers: {
    count: number;
    total: string;
    incoming: string;
    outgoing: string;
    own_account_total: string;
    external_total: string;
    unknown_total: string;
  };
  quality: {
    is_provisional: boolean;
    provisional_count: number;
    unresolved_count: number;
    unresolved_amount: string;
  };
}

export interface ReportResponse {
  overview: { totals: ReportTotals; previous_period_change: string | null };
  months: MonthlyReport[];
  non_eur: Array<{
    currency: string;
    amount: string;
    transaction_count: number;
  }>;
  non_eur_transactions: MonthlyReport["largest_transactions"];
}

export interface ReportFilters {
  monthFrom?: string;
  monthTo?: string;
  statementId?: string;
  currency?: string;
  reportingCategory?: string;
  movementKind?: string;
  paymentChannel?: string;
  counterparty?: string;
  includeProvisional?: boolean;
}

export type ReportGroup =
  | "category"
  | "counterparty"
  | "payment_channel"
  | "movement_kind"
  | "transfer_direction"
  | "transfer_scope";

export interface ReportTransactionPage {
  items: Array<{
    id: string;
    booking_date: string;
    description: string;
    signed_amount: string;
    currency: string;
    reporting_category: string | null;
    movement_kind: string | null;
    payment_channel: string | null;
    counterparty: string | null;
    transfer_scope: string | null;
  }>;
  total: number;
  limit: number;
  offset: number;
}

export async function getReport(
  filters: ReportFilters = {},
): Promise<ReportResponse> {
  const params = new URLSearchParams();
  if (filters.monthFrom) params.set("month_from", filters.monthFrom);
  if (filters.monthTo) params.set("month_to", filters.monthTo);
  if (filters.statementId) params.set("statement_id", filters.statementId);
  if (filters.currency) params.set("currency", filters.currency.toUpperCase());
  if (filters.reportingCategory)
    params.set("reporting_category", filters.reportingCategory);
  if (filters.movementKind) params.set("movement_kind", filters.movementKind);
  if (filters.paymentChannel)
    params.set("payment_channel", filters.paymentChannel);
  if (filters.counterparty?.trim())
    params.set("counterparty", filters.counterparty.trim());
  if (filters.includeProvisional === false)
    params.set("include_provisional", "false");
  const response = await fetch(`/api/reports?${params.toString()}`);
  if (!response.ok) throw new Error("Unable to load reports");
  return (await response.json()) as ReportResponse;
}

export async function listReportTransactions(
  filters: ReportFilters & {
    group: ReportGroup;
    value: string;
    limit?: number;
    offset?: number;
  },
): Promise<ReportTransactionPage> {
  const params = new URLSearchParams({
    group: filters.group,
    value: filters.value,
  });
  if (filters.monthFrom) params.set("month_from", filters.monthFrom);
  if (filters.monthTo) params.set("month_to", filters.monthTo);
  if (filters.statementId) params.set("statement_id", filters.statementId);
  if (filters.currency) params.set("currency", filters.currency.toUpperCase());
  if (filters.reportingCategory)
    params.set("reporting_category", filters.reportingCategory);
  if (filters.movementKind) params.set("movement_kind", filters.movementKind);
  if (filters.paymentChannel)
    params.set("payment_channel", filters.paymentChannel);
  if (filters.counterparty?.trim())
    params.set("counterparty", filters.counterparty.trim());
  if (filters.includeProvisional === false)
    params.set("include_provisional", "false");
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  const response = await fetch(
    `/api/reports/transactions?${params.toString()}`,
  );
  if (!response.ok) throw new Error("Unable to load report transactions");
  return (await response.json()) as ReportTransactionPage;
}
