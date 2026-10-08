import { Fragment, useEffect, useMemo, useState } from "react";

import {
  acceptClassification,
  correctTransaction,
  listTransactions,
  listTransactionHistory,
  revertTransaction,
  type CorrectionRecord,
  type CorrectionRequest,
  type ClassificationStatus,
  type MoneyDirection,
  type MovementKind,
  type PaymentChannel,
  type ReportingCategory,
  type TransferScope,
  type Transaction,
  type TransactionSort,
} from "../api/transactions";
import type { Statement } from "../api/statements";

const pageSize = 50;

interface TransactionsViewProps {
  statements: Statement[];
  refreshKey: number;
}

interface TransactionFilterSnapshot {
  statementId: string;
  reviewOnly: boolean;
  description: string;
  dateFrom: string;
  dateTo: string;
  amountMin: string;
  amountMax: string;
  movementKind: MovementKind | "";
  moneyDirection: MoneyDirection | "";
  classificationStatus: ClassificationStatus | "";
  paymentChannel: PaymentChannel | "";
  reportingCategory: ReportingCategory | "";
  currency: string;
  sort: TransactionSort;
  direction: "asc" | "desc";
}

const emptyFilterSnapshot: TransactionFilterSnapshot = {
  statementId: "",
  reviewOnly: false,
  description: "",
  dateFrom: "",
  dateTo: "",
  amountMin: "",
  amountMax: "",
  movementKind: "",
  moneyDirection: "",
  classificationStatus: "",
  paymentChannel: "",
  reportingCategory: "",
  currency: "",
  sort: "booking_date",
  direction: "desc",
};

export function TransactionsView({
  statements,
  refreshKey,
}: TransactionsViewProps) {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [statementId, setStatementId] = useState("");
  const [reviewOnly, setReviewOnly] = useState(false);
  const [description, setDescription] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [amountMin, setAmountMin] = useState("");
  const [amountMax, setAmountMax] = useState("");
  const [movementKind, setMovementKind] = useState<MovementKind | "">("");
  const [moneyDirection, setMoneyDirection] = useState<MoneyDirection | "">("");
  const [classificationStatus, setClassificationStatus] = useState<
    ClassificationStatus | ""
  >("");
  const [paymentChannel, setPaymentChannel] = useState<PaymentChannel | "">("");
  const [reportingCategory, setReportingCategory] = useState<
    ReportingCategory | ""
  >("");
  const [currency, setCurrency] = useState("");
  const [sort, setSort] = useState<TransactionSort>("booking_date");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTransactionId, setSelectedTransactionId] = useState<
    string | null
  >(null);
  const [appliedFilters, setAppliedFilters] =
    useState<TransactionFilterSnapshot>(emptyFilterSnapshot);
  const amountError =
    amountMin !== "" &&
    amountMax !== "" &&
    Number(amountMin) > Number(amountMax)
      ? "The minimum amount must not be greater than the maximum."
      : null;
  const draftFilters: TransactionFilterSnapshot = {
    statementId,
    reviewOnly,
    description,
    dateFrom,
    dateTo,
    amountMin,
    amountMax,
    movementKind,
    moneyDirection,
    classificationStatus,
    paymentChannel,
    reportingCategory,
    currency,
    sort,
    direction,
  };
  const filtersDirty =
    JSON.stringify(draftFilters) !== JSON.stringify(appliedFilters);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      void listTransactions({
        statementId: appliedFilters.statementId || undefined,
        reviewOnly: appliedFilters.reviewOnly,
        description: appliedFilters.description,
        bookingDateFrom: appliedFilters.dateFrom || undefined,
        bookingDateTo: appliedFilters.dateTo || undefined,
        amountMin: appliedFilters.amountMin || undefined,
        amountMax: appliedFilters.amountMax || undefined,
        movementKind: appliedFilters.movementKind || undefined,
        moneyDirection: appliedFilters.moneyDirection || undefined,
        classificationStatus: appliedFilters.classificationStatus || undefined,
        paymentChannel: appliedFilters.paymentChannel || undefined,
        reportingCategory: appliedFilters.reportingCategory || undefined,
        currency: appliedFilters.currency || undefined,
        sort: appliedFilters.sort,
        direction: appliedFilters.direction,
        limit: pageSize,
        offset,
      })
        .then((page) => {
          if (!active) return;
          setTransactions(page.items);
          setTotal(page.total);
          setError(null);
        })
        .catch((requestError: unknown) => {
          if (!active) return;
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Unable to load transactions",
          );
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 300);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [appliedFilters, offset, refreshKey]);

  const hasPreviousPage = offset > 0;
  const hasNextPage = offset + transactions.length < total;
  const selectedStatement = useMemo(
    () => statements.find((statement) => statement.id === statementId),
    [statementId, statements],
  );
  const hasProvisionalResults =
    selectedStatement?.status === "needs_review" ||
    transactions.some(
      (transaction) => transaction.statement_status === "needs_review",
    );
  const activeFilterLabels = [
    statementId
      ? `Statement: ${selectedStatement?.original_filename ?? statementId}`
      : null,
    description.trim() ? `Description: ${description.trim()}` : null,
    dateFrom ? `From: ${dateFrom}` : null,
    dateTo ? `To: ${dateTo}` : null,
    amountMin ? `Amount ≥ ${amountMin}` : null,
    amountMax ? `Amount ≤ ${amountMax}` : null,
    movementKind || null,
    moneyDirection === "in"
      ? "Money in"
      : moneyDirection === "out"
        ? "Money out"
        : null,
    classificationStatus || null,
    paymentChannel || null,
    reportingCategory || null,
    currency || null,
    reviewOnly ? "Needs review" : null,
  ].filter((label): label is string => label !== null);

  function clearFilter(label: string) {
    if (label.startsWith("Statement:")) setStatementId("");
    else if (label.startsWith("Description:")) setDescription("");
    else if (label.startsWith("From:")) setDateFrom("");
    else if (label.startsWith("To:")) setDateTo("");
    else if (label.startsWith("Amount ≥")) setAmountMin("");
    else if (label.startsWith("Amount ≤")) setAmountMax("");
    else if (
      ["Expense", "Income", "Transfer", "Refund", "Fee"].includes(label)
    ) {
      setMovementKind("");
    } else if (label === "Money in" || label === "Money out") {
      setMoneyDirection("");
    } else if (["unclassified", "classified", "needs_review"].includes(label)) {
      setClassificationStatus("");
    } else if (
      [
        "MB WAY",
        "Card",
        "Bank Transfer",
        "Direct Debit",
        "Cash Withdrawal",
        "Other",
      ].includes(label)
    ) {
      setPaymentChannel("");
    } else if (label === "Needs review") setReviewOnly(false);
    else if (label === currency) setCurrency("");
    else setReportingCategory("");
    resetPage();
  }

  function applyFilters() {
    if (amountError !== null) return;
    setAppliedFilters(draftFilters);
    setOffset(0);
    setLoading(true);
    setError(null);
  }

  function resetPage() {
    setOffset(0);
  }

  function goToPage(nextOffset: number) {
    setOffset(nextOffset);
    setLoading(true);
    setError(null);
  }

  return (
    <section
      className="transactions-workspace"
      id="transactions"
      aria-labelledby="transactions-title"
    >
      <div className="section-heading transactions-heading">
        <div>
          <p className="eyebrow">Source-backed ledger</p>
          <h2 id="transactions-title">Transactions</h2>
        </div>
        <span>{total}</span>
      </div>
      <div
        className="transaction-quick-filters"
        aria-label="Quick transaction filters"
      >
        <label>
          Statement
          <select
            value={statementId}
            onChange={(event) => {
              setStatementId(event.target.value);
              resetPage();
            }}
          >
            <option value="">All statements</option>
            {statements.map((statement) => (
              <option key={statement.id} value={statement.id}>
                {statement.original_filename}
              </option>
            ))}
          </select>
        </label>
        <label className="description-filter">
          Description
          <input
            type="search"
            value={description}
            placeholder="Search description"
            onChange={(event) => {
              setDescription(event.target.value);
              resetPage();
            }}
          />
        </label>
        <label className="checkbox-label">
          <span>Review state</span>
          <span>
            <input
              type="checkbox"
              checked={reviewOnly}
              onChange={(event) => {
                setReviewOnly(event.target.checked);
                resetPage();
              }}
            />{" "}
            Needs review only
          </span>
        </label>
        <button
          type="button"
          className="apply-filters"
          disabled={!filtersDirty || amountError !== null}
          onClick={applyFilters}
        >
          Apply filters
        </button>
      </div>
      <details className="transaction-filter-details">
        <summary>
          Filters
          {activeFilterLabels.length > 0
            ? ` (${activeFilterLabels.length})`
            : ""}
        </summary>
        <div className="transaction-filter-panel">
          <label>
            From date
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => {
                setDateFrom(event.target.value);
                resetPage();
              }}
            />
          </label>
          <label>
            To date
            <input
              type="date"
              value={dateTo}
              onChange={(event) => {
                setDateTo(event.target.value);
                resetPage();
              }}
            />
          </label>
          <label>
            Amount from
            <input
              type="number"
              min="0"
              step="0.01"
              value={amountMin}
              onChange={(event) => {
                setAmountMin(event.target.value);
                resetPage();
              }}
            />
          </label>
          <label>
            Amount to
            <input
              type="number"
              min="0"
              step="0.01"
              value={amountMax}
              onChange={(event) => {
                setAmountMax(event.target.value);
                resetPage();
              }}
            />
          </label>
          <label>
            Movement kind
            <select
              value={movementKind}
              onChange={(event) => {
                setMovementKind(event.target.value as MovementKind | "");
                resetPage();
              }}
            >
              <option value="">Any movement</option>
              <option value="Expense">Expense</option>
              <option value="Income">Income</option>
              <option value="Transfer">Transfer</option>
              <option value="Refund">Refund</option>
              <option value="Fee">Fee</option>
            </select>
          </label>
          <label>
            Direction
            <select
              value={moneyDirection}
              onChange={(event) => {
                setMoneyDirection(event.target.value as MoneyDirection | "");
                resetPage();
              }}
            >
              <option value="">Money in or out</option>
              <option value="in">Money in</option>
              <option value="out">Money out</option>
            </select>
          </label>
          <label>
            Classification
            <select
              value={classificationStatus}
              onChange={(event) => {
                setClassificationStatus(
                  event.target.value as ClassificationStatus | "",
                );
                resetPage();
              }}
            >
              <option value="">Any status</option>
              <option value="unclassified">Unclassified</option>
              <option value="classified">Classified</option>
              <option value="needs_review">Needs review</option>
            </select>
          </label>
          <label>
            Payment channel
            <select
              value={paymentChannel}
              onChange={(event) => {
                setPaymentChannel(event.target.value as PaymentChannel | "");
                resetPage();
              }}
            >
              <option value="">Any channel</option>
              <option value="MB WAY">MB WAY</option>
              <option value="Card">Card</option>
              <option value="Bank Transfer">Bank transfer</option>
              <option value="Direct Debit">Direct debit</option>
              <option value="Cash Withdrawal">Cash withdrawal</option>
              <option value="Other">Other</option>
            </select>
          </label>
          <label>
            Reporting category
            <select
              value={reportingCategory}
              onChange={(event) => {
                setReportingCategory(
                  event.target.value as ReportingCategory | "",
                );
                resetPage();
              }}
            >
              <option value="">Any category</option>
              {[
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
              ].map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
          </label>
          <label>
            Currency
            <input
              maxLength={3}
              placeholder="Any"
              value={currency}
              onChange={(event) => {
                setCurrency(event.target.value.toUpperCase());
                resetPage();
              }}
            />
          </label>
          <label>
            Sort by
            <select
              value={sort}
              onChange={(event) => {
                setSort(event.target.value as TransactionSort);
                resetPage();
              }}
            >
              <option value="booking_date">Booking date</option>
              <option value="signed_amount">Amount</option>
              <option value="description">Description</option>
              <option value="source_ordinal">Source order</option>
            </select>
          </label>
          <label>
            Sort direction
            <select
              value={direction}
              onChange={(event) => {
                setDirection(event.target.value as "asc" | "desc");
                resetPage();
              }}
            >
              <option value="desc">Descending</option>
              <option value="asc">Ascending</option>
            </select>
          </label>
          {amountError && (
            <p className="form-error filter-error">{amountError}</p>
          )}
          {activeFilterLabels.length > 0 && (
            <button
              type="button"
              className="clear-filters"
              onClick={() => {
                setStatementId("");
                setDescription("");
                setDateFrom("");
                setDateTo("");
                setAmountMin("");
                setAmountMax("");
                setMovementKind("");
                setMoneyDirection("");
                setClassificationStatus("");
                setPaymentChannel("");
                setReportingCategory("");
                setCurrency("");
                setReviewOnly(false);
                setAppliedFilters(emptyFilterSnapshot);
                setLoading(true);
                setError(null);
                resetPage();
              }}
            >
              Clear all filters
            </button>
          )}
        </div>
      </details>
      {activeFilterLabels.length > 0 && (
        <div
          className="active-filter-chips"
          aria-label="Active transaction filters"
        >
          {activeFilterLabels.map((label) => (
            <span key={label}>
              {label}
              <button
                type="button"
                aria-label={`Remove ${label}`}
                onClick={() => clearFilter(label)}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {hasProvisionalResults && (
        <p className="provisional-banner">
          Provisional results: this statement needs review before its financial
          data is trusted.
        </p>
      )}
      {loading && <p className="empty-state">Loading transactions…</p>}
      {!loading && error !== null && <p className="form-error">{error}</p>}
      {!loading && error === null && transactions.length === 0 && (
        <p className="empty-state">No transactions match these filters.</p>
      )}
      {!loading && error === null && transactions.length > 0 && (
        <>
          <div className="transaction-table-wrap">
            <table className="transaction-table">
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Description</th>
                  <th scope="col">Amount</th>
                  <th scope="col">Classification</th>
                  <th scope="col">Statement</th>
                  <th scope="col">Edit</th>
                  <th scope="col">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((transaction) => (
                  <Fragment key={transaction.id}>
                    <TransactionRow
                      transaction={transaction}
                      onEdit={() =>
                        setSelectedTransactionId((current) =>
                          current === transaction.id ? null : transaction.id,
                        )
                      }
                      isEditing={selectedTransactionId === transaction.id}
                    />
                    {selectedTransactionId === transaction.id && (
                      <tr className="transaction-editor-row">
                        <td colSpan={7}>
                          <TransactionResolutionPanel
                            key={`${transaction.id}-${transaction.correction_revision}`}
                            transaction={transaction}
                            onClose={() => setSelectedTransactionId(null)}
                            onChanged={(updated) =>
                              setTransactions((current) =>
                                current.map((item) =>
                                  item.id === updated.id ? updated : item,
                                ),
                              )
                            }
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <div className="transaction-pagination">
            <span>
              Showing {offset + 1}–{offset + transactions.length} of {total}
            </span>
            <div>
              <button
                type="button"
                disabled={!hasPreviousPage}
                onClick={() => goToPage(Math.max(0, offset - pageSize))}
              >
                Previous
              </button>
              <button
                type="button"
                disabled={!hasNextPage}
                onClick={() => goToPage(offset + pageSize)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function TransactionRow({
  transaction,
  onEdit,
  isEditing,
}: {
  transaction: Transaction;
  onEdit: () => void;
  isEditing: boolean;
}) {
  const provisional = transaction.statement_status === "needs_review";
  const classificationResolved =
    transaction.classification_resolution !== "pending";
  return (
    <tr>
      <td>{formatPortugueseDate(transaction.booking_date)}</td>
      <td>
        <strong>{transaction.description}</strong>
        {transaction.review_findings.length > 0 && !classificationResolved && (
          <span className="transaction-review-label">Review required</span>
        )}
      </td>
      <td
        className={
          transaction.signed_amount.startsWith("-")
            ? "amount-debit"
            : "amount-credit"
        }
      >
        {formatPortugueseAmount(
          transaction.signed_amount,
          transaction.currency,
        )}
      </td>
      <td>
        {classificationResolved ||
        transaction.classification_status === "classified" ? (
          <span>
            {transaction.reporting_category ?? "Transfer"}
            <small className="transaction-status">
              {transaction.movement_kind} · {transaction.payment_channel}
            </small>
          </span>
        ) : (
          <span className="transaction-status">
            {transaction.classification_status === "needs_review"
              ? "Review required"
              : "Unclassified"}
          </span>
        )}
      </td>
      <td>
        <span>{transaction.statement_filename}</span>
        {provisional && <span className="transaction-status">Provisional</span>}
      </td>
      <td>
        <button
          type="button"
          className="transaction-edit"
          onClick={onEdit}
          aria-expanded={isEditing}
          aria-controls={`transaction-editor-${transaction.id}`}
        >
          {isEditing ? "Close" : "Edit"}
        </button>
      </td>
      <td>
        <details>
          <summary>View evidence</summary>
          <div className="evidence-detail">
            {transaction.evidence_page_number !== null && (
              <span>
                Page {transaction.evidence_page_number}
                {transaction.evidence_line_start !== null &&
                  transaction.evidence_line_end !== null &&
                  `, lines ${transaction.evidence_line_start}–${transaction.evidence_line_end}`}
              </span>
            )}
            {transaction.evidence_quote !== null ? (
              <blockquote>{transaction.evidence_quote}</blockquote>
            ) : (
              <span>Evidence requires review.</span>
            )}
            {transaction.review_findings.map((finding, index) => (
              <span key={`${transaction.id}-finding-${index}`}>
                {finding.message}
              </span>
            ))}
          </div>
        </details>
      </td>
    </tr>
  );
}

function TransactionResolutionPanel({
  transaction,
  onClose,
  onChanged,
}: {
  transaction: Transaction;
  onClose: () => void;
  onChanged: (transaction: Transaction) => void;
}) {
  const [description, setDescription] = useState(transaction.description);
  const [bookingDate, setBookingDate] = useState(transaction.booking_date);
  const [signedAmount, setSignedAmount] = useState(transaction.signed_amount);
  const [currency, setCurrency] = useState(transaction.currency);
  const [category, setCategory] = useState(
    transaction.reporting_category ?? "",
  );
  const [movementKind, setMovementKind] = useState(
    transaction.movement_kind ?? "",
  );
  const [paymentChannel, setPaymentChannel] = useState(
    transaction.payment_channel ?? "",
  );
  const [transferScope, setTransferScope] = useState<TransferScope | "">(
    transaction.transfer_scope ?? "",
  );
  const [counterparty, setCounterparty] = useState(
    transaction.counterparty ?? "",
  );
  const [note, setNote] = useState(transaction.note ?? "");
  const [reason, setReason] = useState("");
  const [history, setHistory] = useState<CorrectionRecord[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [panelError, setPanelError] = useState<string | null>(null);

  useEffect(() => {
    void listTransactionHistory(transaction.id)
      .then(setHistory)
      .catch((error: unknown) =>
        setPanelError(
          error instanceof Error ? error.message : "Unable to load history",
        ),
      );
  }, [transaction.id, transaction.correction_revision]);

  async function saveCorrection() {
    if (!reason.trim()) {
      setPanelError("Provide a reason for the correction.");
      return;
    }
    const changes: CorrectionRequest = {
      expected_revision: transaction.correction_revision,
      reason: reason.trim(),
      idempotency_key: makeIdempotencyKey(),
    };
    if (description !== transaction.description)
      changes.description = description;
    if (bookingDate !== transaction.booking_date)
      changes.booking_date = bookingDate;
    if (signedAmount !== transaction.signed_amount)
      changes.signed_amount = signedAmount;
    if (currency !== transaction.currency) changes.currency = currency;
    if (category !== (transaction.reporting_category ?? "")) {
      changes.reporting_category =
        category === "" ? null : (category as ReportingCategory);
    }
    if (movementKind !== (transaction.movement_kind ?? "")) {
      changes.movement_kind =
        movementKind === "" ? null : (movementKind as MovementKind);
    }
    if (paymentChannel !== (transaction.payment_channel ?? "")) {
      changes.payment_channel =
        paymentChannel === "" ? null : (paymentChannel as PaymentChannel);
    }
    if (transferScope !== (transaction.transfer_scope ?? "")) {
      changes.transfer_scope = transferScope === "" ? null : transferScope;
    }
    if (counterparty !== (transaction.counterparty ?? "")) {
      changes.counterparty = counterparty === "" ? null : counterparty;
    }
    if (note !== (transaction.note ?? ""))
      changes.note = note === "" ? null : note;
    if (changes.movement_kind === "Transfer") {
      changes.reporting_category = null;
    }
    if (Object.keys(changes).length === 3) {
      setPanelError("Change a value before saving.");
      return;
    }
    setSaving(true);
    setPanelError(null);
    try {
      const updated = await correctTransaction(transaction.id, changes);
      onChanged(updated);
      setReason("");
      setMessage("Correction saved. Statement review is running.");
    } catch (error) {
      setPanelError(
        error instanceof Error ? error.message : "Unable to save correction",
      );
    } finally {
      setSaving(false);
    }
  }

  async function accept() {
    if (
      transaction.classification_id === null ||
      transaction.classification_id === undefined
    ) {
      setPanelError("There is no classification result to accept.");
      return;
    }
    setSaving(true);
    setPanelError(null);
    try {
      const updated = await acceptClassification(transaction.id, {
        classification_id: transaction.classification_id,
        idempotency_key: makeIdempotencyKey(),
      });
      onChanged(updated);
      setMessage("Classification accepted. Statement review is running.");
    } catch (error) {
      setPanelError(
        error instanceof Error
          ? error.message
          : "Unable to accept classification",
      );
    } finally {
      setSaving(false);
    }
  }

  async function revertTo(revision: number) {
    if (!window.confirm(`Revert this transaction to revision ${revision}?`))
      return;
    setSaving(true);
    setPanelError(null);
    try {
      const updated = await revertTransaction(transaction.id, {
        expected_revision: transaction.correction_revision,
        target_revision: revision,
        reason: `Reverted to revision ${revision}`,
        idempotency_key: makeIdempotencyKey(),
      });
      onChanged(updated);
      setDescription(updated.description);
      setBookingDate(updated.booking_date);
      setSignedAmount(updated.signed_amount);
      setCurrency(updated.currency);
      setCategory(updated.reporting_category ?? "");
      setMovementKind(updated.movement_kind ?? "");
      setPaymentChannel(updated.payment_channel ?? "");
      setTransferScope(updated.transfer_scope ?? "");
      setCounterparty(updated.counterparty ?? "");
      setNote(updated.note ?? "");
      setMessage("Revision reverted. Statement review is running.");
    } catch (error) {
      setPanelError(
        error instanceof Error ? error.message : "Unable to revert revision",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className="transaction-resolution"
      id={`transaction-editor-${transaction.id}`}
      aria-labelledby="resolution-title"
    >
      <div className="transaction-resolution-heading">
        <div>
          <p className="eyebrow">Transaction resolution</p>
          <h3 id="resolution-title">{transaction.description}</h3>
        </div>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="transaction-resolution-grid">
        <span>
          Original description:{" "}
          {transaction.original_description ?? transaction.description}
        </span>
        <span>
          Original amount:{" "}
          {transaction.original_signed_amount ?? transaction.signed_amount}{" "}
          {transaction.original_currency ?? transaction.currency}
        </span>
        <span>Revision: {transaction.correction_revision}</span>
        <span>Resolution: {transaction.classification_resolution}</span>
      </div>
      <ClassificationResearch
        provenance={transaction.classification_provenance ?? null}
        sourceOrdinal={transaction.source_ordinal}
      />
      <label>
        Booking date
        <input
          type="date"
          value={bookingDate}
          onChange={(event) => setBookingDate(event.target.value)}
        />
      </label>
      <label>
        Signed amount
        <input
          value={signedAmount}
          onChange={(event) => setSignedAmount(event.target.value)}
          inputMode="decimal"
        />
      </label>
      <label>
        Currency
        <input
          maxLength={3}
          value={currency}
          onChange={(event) => setCurrency(event.target.value.toUpperCase())}
        />
      </label>
      <label>
        Description
        <input
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>
      <label>
        Counterparty
        <input
          value={counterparty}
          onChange={(event) => setCounterparty(event.target.value)}
        />
      </label>
      <label>
        Note
        <input value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
      <label>
        Reporting category
        <select
          value={category}
          onChange={(event) => setCategory(event.target.value)}
        >
          <option value="">No category / transfer</option>
          {[
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
          ].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </label>
      <label>
        Movement kind
        <select
          value={movementKind}
          onChange={(event) => {
            const value = event.target.value;
            setMovementKind(value);
            if (value === "Transfer") setCategory("");
            else setTransferScope("");
          }}
        >
          <option value="">Unclassified</option>
          <option value="Expense">Expense</option>
          <option value="Income">Income</option>
          <option value="Transfer">Transfer</option>
          <option value="Refund">Refund</option>
          <option value="Fee">Fee</option>
        </select>
      </label>
      <label>
        Payment channel
        <select
          value={paymentChannel}
          onChange={(event) => setPaymentChannel(event.target.value)}
        >
          <option value="">Unclassified</option>
          <option value="MB WAY">MB WAY</option>
          <option value="Card">Card</option>
          <option value="Bank Transfer">Bank Transfer</option>
          <option value="Direct Debit">Direct Debit</option>
          <option value="Cash Withdrawal">Cash Withdrawal</option>
          <option value="Other">Other</option>
        </select>
      </label>
      {movementKind === "Transfer" && (
        <label>
          Transfer treatment
          <select
            value={transferScope}
            onChange={(event) =>
              setTransferScope(event.target.value as TransferScope | "")
            }
          >
            <option value="">Unknown / review</option>
            <option value="own_account">Own account (internal)</option>
            <option value="external_party">
              External party (include in flow)
            </option>
          </select>
        </label>
      )}
      <label>
        Reason
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Why is this correction needed?"
        />
      </label>
      <div className="transaction-resolution-actions">
        {transaction.classification_status === "needs_review" &&
          transaction.classification_resolution === "pending" && (
            <button
              type="button"
              disabled={saving}
              onClick={() => void accept()}
            >
              {saving ? "Saving…" : "Accept classification"}
            </button>
          )}
        <button
          type="button"
          disabled={saving}
          onClick={() => void saveCorrection()}
        >
          {saving ? "Saving…" : "Save correction"}
        </button>
      </div>
      {message !== null && (
        <p className="form-status" role="status">
          {message}
        </p>
      )}
      {panelError !== null && <p className="form-error">{panelError}</p>}
      {history.length > 0 && (
        <div className="transaction-history">
          <h4>Correction history</h4>
          {transaction.correction_revision > 0 && (
            <button
              type="button"
              disabled={saving}
              onClick={() => void revertTo(0)}
            >
              Revert to original values
            </button>
          )}
          {history.map((entry) => (
            <div key={entry.id} className="transaction-history-entry">
              <strong>Revision {entry.revision}</strong>
              <span>{entry.reason}</span>
              <span className="transaction-history-values">
                Before:{" "}
                {formatHistoryValues(
                  entry.previous_revision === 0
                    ? {
                        booking_date:
                          transaction.original_booking_date ??
                          transaction.booking_date,
                        description:
                          transaction.original_description ??
                          transaction.description,
                        signed_amount:
                          transaction.original_signed_amount ??
                          transaction.signed_amount,
                        currency:
                          transaction.original_currency ?? transaction.currency,
                        reporting_category:
                          transaction.original_reporting_category ?? null,
                        movement_kind:
                          transaction.original_movement_kind ?? null,
                        payment_channel:
                          transaction.original_payment_channel ?? null,
                        counterparty: transaction.original_counterparty ?? null,
                        note: transaction.original_note ?? null,
                        transfer_scope:
                          transaction.original_transfer_scope ?? null,
                      }
                    : (history.find(
                        (candidate) =>
                          candidate.revision === entry.previous_revision,
                      )?.values ?? entry.values),
                )}
              </span>
              <span className="transaction-history-values">
                After: {formatHistoryValues(entry.values)}
              </span>
              <button
                type="button"
                disabled={
                  saving || entry.revision === transaction.correction_revision
                }
                onClick={() => void revertTo(entry.revision)}
              >
                Revert
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ClassificationResearch({
  provenance,
  sourceOrdinal,
}: {
  provenance: Record<string, unknown> | null;
  sourceOrdinal: number;
}) {
  const research = provenance?.research;
  if (!Array.isArray(research)) return null;
  const item = research.find(
    (candidate): candidate is Record<string, unknown> =>
      typeof candidate === "object" &&
      candidate !== null &&
      candidate.source_ordinal === sourceOrdinal,
  );
  if (!item) return null;
  const sources = Array.isArray(item.sources) ? item.sources : [];
  return (
    <div className="classification-research" aria-label="Merchant research">
      <strong>Merchant research</strong>
      <span>
        {String(item.status)} · {item.cache_hit ? "cached" : "fresh"}
      </span>
      {sources.map((source, index) => {
        if (typeof source !== "object" || source === null) return null;
        const value = source as Record<string, unknown>;
        if (typeof value.url !== "string" || typeof value.title !== "string") {
          return null;
        }
        return (
          <a
            href={value.url}
            key={`${value.url}-${index}`}
            target="_blank"
            rel="noreferrer"
          >
            {value.title}
          </a>
        );
      })}
    </div>
  );
}

function makeIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `bsa-${Date.now()}`;
}

function formatPortugueseDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function formatPortugueseAmount(value: string, currency: string): string {
  const [wholePart, fractionPart] = value.split(".");
  const sign = wholePart.startsWith("-") ? "-" : "";
  const absoluteWhole = wholePart.replace(/^[+-]/, "");
  const groupedWhole = absoluteWhole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${sign}${groupedWhole},${fractionPart ?? "00"} ${currency}`;
}

function formatHistoryValues(values: CorrectionRecord["values"]): string {
  const classification =
    [
      values.movement_kind,
      values.reporting_category,
      values.payment_channel,
      values.counterparty,
      values.note,
    ]
      .filter(Boolean)
      .join(" / ") || "Unclassified";
  return `${values.booking_date} · ${values.signed_amount} ${values.currency} · ${values.description} · ${classification}`;
}
