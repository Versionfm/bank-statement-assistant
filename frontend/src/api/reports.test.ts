import { afterEach, expect, test, vi } from "vitest";

import { listReportTransactions } from "./reports";

afterEach(() => vi.restoreAllMocks());

test("serializes report drill-down filters", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({ items: [], total: 0, limit: 25, offset: 25 }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    ),
  );

  await listReportTransactions({
    group: "transfer_direction",
    value: "out",
    monthFrom: "2026-09",
    monthTo: "2026-09",
    currency: "EUR",
    includeProvisional: false,
    limit: 25,
    offset: 25,
  });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/reports/transactions?group=transfer_direction&value=out&month_from=2026-09&month_to=2026-09&currency=EUR&include_provisional=false&limit=25&offset=25",
  );
});
