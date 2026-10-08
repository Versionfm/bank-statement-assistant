import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import App from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("shows the application shell when the backend is ready", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    return new Response(
      JSON.stringify(
        url.endsWith("/ready")
          ? { status: "ok" }
          : url.startsWith("/api/transactions")
            ? { items: [], total: 0, limit: 50, offset: 0 }
            : [],
      ),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  });

  render(<App />);

  expect(
    screen.getByRole("link", { name: "Bank Statement Assistant home" }),
  ).toBeInTheDocument();
  expect(await screen.findByText("Foundation ready")).toBeInTheDocument();
  expect(globalThis.fetch).toHaveBeenCalledWith("/api/health/ready");
  expect(screen.getAllByText("Planned")).toHaveLength(2);
  expect(screen.getByRole("link", { name: "Statements" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Reports" })).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Import a statement" }),
  ).toBeInTheDocument();
});

test("keeps the shell usable when the backend is unavailable", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(
    new Error("connection refused"),
  );

  render(<App />);

  expect(await screen.findByText("Backend unavailable")).toBeInTheDocument();
});

test("uploads a PDF and shows its durable processing state", async () => {
  const statement = {
    id: "50e5591f-913e-471b-a501-541fd860af30",
    account_reference: "BPI Main",
    original_filename: "august.pdf",
    page_count: 2,
    status: "processing",
    current_stage: "extract_text",
    extraction_result: null,
    validation_result: null,
    review_findings: [],
    last_error_code: null,
    created_at: null,
  };
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/ready")) {
        return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
      }
      if (init?.method === "POST") {
        return new Response(JSON.stringify(statement), { status: 201 });
      }
      return new Response(
        url.startsWith("/api/transactions")
          ? JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 })
          : JSON.stringify([]),
        { status: 200 },
      );
    });
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("Account reference"), "BPI Main");
  await user.upload(
    screen.getByLabelText("PDF statement"),
    new File(["%PDF statement"], "august.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByRole("button", { name: "Import statement" }));

  expect((await screen.findAllByText("august.pdf")).length).toBeGreaterThan(0);
  expect(screen.getByText("Extracting text")).toBeInTheDocument();
  expect(
    screen.getByText(
      "PDF accepted. Processing has started; the status below updates automatically.",
    ),
  ).toBeInTheDocument();
  const uploadCall = fetchMock.mock.calls.find(
    ([, init]) => init?.method === "POST",
  );
  expect(uploadCall?.[0]).toBe("/api/statements");
  expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData);
});

test("confirms when an uploaded PDF is already being processed", async () => {
  const statement = {
    id: "50e5591f-913e-471b-a501-541fd860af30",
    account_reference: "BPI Main",
    original_filename: "august.pdf",
    page_count: 2,
    status: "processing",
    current_stage: "extract_text",
    extraction_result: null,
    validation_result: null,
    review_findings: [],
    last_error_code: null,
    created_at: null,
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/ready")) {
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    }
    if (init?.method === "POST") {
      return new Response(JSON.stringify(statement), { status: 200 });
    }
    return new Response(
      url.startsWith("/api/transactions")
        ? JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 })
        : JSON.stringify([statement]),
      { status: 200 },
    );
  });
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("Account reference"), "BPI Main");
  await user.upload(
    screen.getByLabelText("PDF statement"),
    new File(["%PDF statement"], "august.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByRole("button", { name: "Import statement" }));

  expect(
    await screen.findByText(
      "This PDF is already imported. Showing its current status below.",
    ),
  ).toBeInTheDocument();
});

test("explains how to recover when a duplicate PDF previously failed", async () => {
  const statement = {
    id: "50e5591f-913e-471b-a501-541fd860af30",
    account_reference: "BPI Main",
    original_filename: "failed.pdf",
    page_count: 2,
    status: "failed",
    current_stage: "classify",
    extraction_result: null,
    validation_result: null,
    review_findings: [],
    last_error_code: "classify_invalid_response",
    created_at: null,
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/ready")) {
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    }
    if (init?.method === "POST") {
      return new Response(JSON.stringify(statement), { status: 200 });
    }
    return new Response(
      url.startsWith("/api/transactions")
        ? JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 })
        : JSON.stringify([statement]),
      { status: 200 },
    );
  });
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText("Account reference"), "BPI Main");
  await user.upload(
    screen.getByLabelText("PDF statement"),
    new File(["%PDF statement"], "failed.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByRole("button", { name: "Import statement" }));

  expect(
    await screen.findByText(
      "This PDF is already imported and failed during Classifying transactions. Use Retry below to run the fixed stage again.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("shows precise failure and review details", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/ready")) {
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    }
    const payload = url.startsWith("/api/transactions")
      ? { items: [], total: 0, limit: 50, offset: 0 }
      : [
          {
            id: "50e5591f-913e-471b-a501-541fd860af30",
            account_reference: "BPI Main",
            original_filename: "failed.pdf",
            page_count: 1,
            status: "failed",
            current_stage: "validate",
            extraction_result: null,
            validation_result: null,
            review_findings: [
              {
                code: "balance_mismatch",
                message: "Balances do not reconcile.",
              },
            ],
            last_error_code: "validate_failed",
            created_at: null,
          },
        ];
    return new Response(JSON.stringify(payload), { status: 200 });
  });

  render(<App />);

  expect(
    await screen.findByText("Failure: validate failed"),
  ).toBeInTheDocument();
  expect(screen.getByText("Balances do not reconcile.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("offers source reprocessing when transaction extraction failed", async () => {
  const failedStatement = {
    id: "50e5591f-913e-471b-a501-541fd860af30",
    account_reference: "BPI Main",
    original_filename: "failed-bpi.pdf",
    page_count: 3,
    status: "failed",
    current_stage: "extract_transactions",
    extraction_result: null,
    validation_result: null,
    review_findings: [],
    last_error_code: "extract_transactions_failed",
    created_at: null,
  };
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/ready")) {
        return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
      }
      if (url.endsWith("/reprocess")) {
        return new Response(
          JSON.stringify({
            ...failedStatement,
            status: "processing",
            current_stage: "extract_text",
            last_error_code: null,
          }),
          { status: 202 },
        );
      }
      if (init?.method === "POST") {
        return new Response(JSON.stringify(failedStatement), { status: 200 });
      }
      return new Response(
        url.startsWith("/api/transactions")
          ? JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 })
          : JSON.stringify([failedStatement]),
        { status: 200 },
      );
    });

  render(<App />);

  expect(
    await screen.findByRole("button", { name: "Reprocess from PDF" }),
  ).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Reprocess from PDF" }),
  );

  expect(
    fetchMock.mock.calls.some(
      ([input, init]) =>
        String(input).endsWith("/reprocess") && init?.method === "POST",
    ),
  ).toBe(true);
  expect(await screen.findByText("Extracting text")).toBeInTheDocument();
});

test("shows provisional transactions with their source evidence", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/ready")) {
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    }
    if (url.startsWith("/api/transactions")) {
      return new Response(
        JSON.stringify({
          items: [
            {
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
              review_findings: [
                { code: "balance_mismatch", message: "Review required." },
              ],
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        }),
        { status: 200 },
      );
    }
    return new Response(JSON.stringify([]), { status: 200 });
  });

  render(<App />);

  expect(await screen.findByText("Grocery Store")).toBeInTheDocument();
  expect(screen.getByText(/Provisional results/)).toBeInTheDocument();
  expect(
    screen.getByText("01/09/2025 Grocery Store -12,34"),
  ).toBeInTheDocument();
  expect(screen.getByText("Review required.")).toBeInTheDocument();
});
