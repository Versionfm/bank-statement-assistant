import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { TransactionsView } from "./TransactionsView";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockTransactionsRequest() {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    ),
  );
}

test("exposes compact filters and serializes description and advanced filters", async () => {
  const fetchMock = mockTransactionsRequest();
  const user = userEvent.setup();
  render(<TransactionsView statements={[]} refreshKey={0} />);

  expect(
    screen.getByRole("button", { name: "Apply filters" }),
  ).toBeInTheDocument();
  await screen.findByText("No transactions match these filters.");
  await user.type(screen.getByLabelText("Description"), "mercado");
  await user.click(screen.getByText(/Filters/));
  await user.selectOptions(screen.getByLabelText("Movement kind"), "Transfer");
  await user.type(
    screen.getByRole("spinbutton", { name: "Amount from" }),
    "100",
  );
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "Apply filters" }));

  expect(
    screen.getByRole("button", { name: "Remove Transfer" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Amount ≥ 100")).toBeInTheDocument();
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([input]) => {
        const url = String(input);
        return (
          url.includes("description=mercado") &&
          url.includes("amount_min=100") &&
          url.includes("movement_kind=Transfer")
        );
      }),
    ).toBe(true);
  });
});

test("shows an inline error for an invalid amount range", async () => {
  mockTransactionsRequest();
  const user = userEvent.setup();
  render(<TransactionsView statements={[]} refreshKey={0} />);

  await user.click(screen.getByText("Filters"));
  await user.type(
    screen.getByRole("spinbutton", { name: "Amount from" }),
    "250",
  );
  await user.type(screen.getByRole("spinbutton", { name: "Amount to" }), "100");

  expect(
    screen.getAllByText(
      "The minimum amount must not be greater than the maximum.",
    ),
  ).not.toHaveLength(0);
});

test("accepts a pending classification from the resolution panel", async () => {
  const transaction = {
    id: "50e5591f-913e-471b-a501-541fd860af30",
    statement_id: "da7abe2b-aac6-42e5-ae61-669e3ca11ebb",
    statement_filename: "statement.pdf",
    statement_status: "needs_review",
    source_ordinal: 1,
    booking_date: "2025-09-01",
    description: "Grocery Store",
    signed_amount: "-12.34",
    currency: "EUR",
    confidence: 0.99,
    evidence_page_number: 1,
    evidence_line_start: 2,
    evidence_line_end: 2,
    evidence_quote: "01/09/2025 Grocery Store -12,34",
    reporting_category: "Groceries",
    movement_kind: "Expense",
    payment_channel: "Card",
    classification_status: "needs_review",
    classification_confidence: 0.5,
    classification_provenance: null,
    review_findings: [],
    classification_id: 7,
    classification_resolution: "pending",
    correction_revision: 0,
  };
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/history")) return new Response(JSON.stringify([]));
    if (init?.method === "POST") return new Response(JSON.stringify({ ...transaction, classification_resolution: "accepted" }), { status: 202 });
    return new Response(JSON.stringify({ items: [transaction], total: 1, limit: 50, offset: 0 }), { status: 200 });
  });
  const user = userEvent.setup();
  render(<TransactionsView statements={[]} refreshKey={0} />);

  await user.click(await screen.findByRole("button", { name: "Edit" }));
  await user.click(screen.getByRole("button", { name: "Accept classification" }));

  await waitFor(() => {
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true);
  });
});
