import type { components } from "./generated";

export type Transaction = components["schemas"]["TransactionResponse"];
export type TransactionPage = components["schemas"]["TransactionPageResponse"];
export type CorrectionRecord =
  components["schemas"]["CorrectionRecordResponse"];
export type CorrectionRequest =
  components["schemas"]["TransactionCorrectionRequest"];
export type TransactionSort =
  "booking_date" | "signed_amount" | "description" | "source_ordinal";
export type MovementKind = "Expense" | "Income" | "Transfer" | "Refund" | "Fee";
export type MoneyDirection = "in" | "out";
export type ClassificationStatus =
  "unclassified" | "classified" | "needs_review";
export type PaymentChannel =
  | "MB WAY"
  | "Card"
  | "Bank Transfer"
  | "Direct Debit"
  | "Cash Withdrawal"
  | "Other";
export type ReportingCategory =
  | "Groceries"
  | "Restaurants & Cafes"
  | "Housing"
  | "Utilities"
  | "Transport"
  | "Health"
  | "Insurance"
  | "Subscriptions"
  | "Shopping"
  | "Leisure"
  | "Travel"
  | "Education"
  | "Gifts & Donations"
  | "Taxes"
  | "Other Expense"
  | "Salary"
  | "Interest"
  | "Other Income"
  | "Bank Fees";
export type TransferScope = "own_account" | "external_party" | "unknown";

export interface TransactionFilters {
  statementId?: string;
  reviewOnly?: boolean;
  bookingDateFrom?: string;
  bookingDateTo?: string;
  description?: string;
  amountMin?: string;
  amountMax?: string;
  movementKind?: MovementKind;
  moneyDirection?: MoneyDirection;
  classificationStatus?: ClassificationStatus;
  paymentChannel?: PaymentChannel;
  transferScope?: TransferScope;
  reportingCategory?: ReportingCategory;
  currency?: string;
  sort?: TransactionSort;
  direction?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export async function listTransactions(
  filters: TransactionFilters = {},
): Promise<TransactionPage> {
  const params = new URLSearchParams();
  if (filters.statementId) params.set("statement_id", filters.statementId);
  if (filters.reviewOnly) params.set("review_only", "true");
  if (filters.bookingDateFrom) {
    params.set("booking_date_from", filters.bookingDateFrom);
  }
  if (filters.bookingDateTo)
    params.set("booking_date_to", filters.bookingDateTo);
  if (filters.description?.trim()) {
    params.set("description", filters.description.trim());
  }
  if (filters.amountMin?.trim())
    params.set("amount_min", filters.amountMin.trim());
  if (filters.amountMax?.trim())
    params.set("amount_max", filters.amountMax.trim());
  if (filters.movementKind) params.set("movement_kind", filters.movementKind);
  if (filters.moneyDirection)
    params.set("money_direction", filters.moneyDirection);
  if (filters.classificationStatus) {
    params.set("classification_status", filters.classificationStatus);
  }
  if (filters.paymentChannel)
    params.set("payment_channel", filters.paymentChannel);
  if (filters.transferScope)
    params.set("transfer_scope", filters.transferScope);
  if (filters.reportingCategory) {
    params.set("reporting_category", filters.reportingCategory);
  }
  if (filters.currency?.trim())
    params.set("currency", filters.currency.trim().toUpperCase());
  params.set("sort", filters.sort ?? "booking_date");
  params.set("direction", filters.direction ?? "desc");
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  const response = await fetch(`/api/transactions?${params.toString()}`);
  if (!response.ok) {
    throw new Error("Unable to load transactions");
  }
  return (await response.json()) as TransactionPage;
}

export async function getTransaction(
  transactionId: string,
): Promise<Transaction> {
  const response = await fetch(`/api/transactions/${transactionId}`);
  if (!response.ok) {
    throw new Error("Unable to load transaction");
  }
  return (await response.json()) as Transaction;
}

export async function correctTransaction(
  transactionId: string,
  correction: CorrectionRequest,
): Promise<Transaction> {
  const response = await fetch(
    `/api/transactions/${transactionId}/corrections`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(correction),
    },
  );
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Unable to save correction"));
  }
  return (await response.json()) as Transaction;
}

export async function listTransactionHistory(
  transactionId: string,
): Promise<CorrectionRecord[]> {
  const response = await fetch(`/api/transactions/${transactionId}/history`);
  if (!response.ok) throw new Error("Unable to load correction history");
  return (await response.json()) as CorrectionRecord[];
}

export async function revertTransaction(
  transactionId: string,
  request: components["schemas"]["TransactionRevertRequest"],
): Promise<Transaction> {
  const response = await fetch(`/api/transactions/${transactionId}/revert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(
      await errorMessage(response, "Unable to revert correction"),
    );
  }
  return (await response.json()) as Transaction;
}

export async function acceptClassification(
  transactionId: string,
  request: components["schemas"]["ClassificationAcceptanceRequest"],
): Promise<Transaction> {
  const response = await fetch(
    `/api/transactions/${transactionId}/classification/accept`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    throw new Error(
      await errorMessage(response, "Unable to accept classification"),
    );
  }
  return (await response.json()) as Transaction;
}

async function errorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}
