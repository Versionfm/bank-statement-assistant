import { afterEach, expect, test, vi } from "vitest";

import { listTransactions } from "./transactions";

afterEach(() => vi.restoreAllMocks());

test("serializes transaction filters for the deterministic API", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    ),
  );

  await listTransactions({
    description: " mercado ",
    amountMin: "100.00",
    amountMax: "250.50",
    movementKind: "Transfer",
    moneyDirection: "out",
    classificationStatus: "classified",
    paymentChannel: "Bank Transfer",
    reportingCategory: "Groceries",
    currency: "eur",
  });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/transactions?description=mercado&amount_min=100.00&amount_max=250.50&movement_kind=Transfer&money_direction=out&classification_status=classified&payment_channel=Bank+Transfer&reporting_category=Groceries&currency=EUR&sort=booking_date&direction=desc&limit=50&offset=0",
  );
});
