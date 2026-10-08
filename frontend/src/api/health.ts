import type { components } from "./generated";

export type BackendStatus = "checking" | "ready" | "unavailable";
type HealthResponse = components["schemas"]["HealthResponse"];

export async function getBackendStatus(): Promise<BackendStatus> {
  try {
    const response = await fetch("/api/health/ready");
    if (!response.ok) {
      return "unavailable";
    }
    const body: unknown = await response.json();
    return hasOkStatus(body) ? "ready" : "unavailable";
  } catch {
    return "unavailable";
  }
}

function hasOkStatus(
  value: unknown,
): value is HealthResponse & { status: "ok" } {
  return (
    typeof value === "object" &&
    value !== null &&
    "status" in value &&
    value.status === "ok"
  );
}
