import type { components } from "./generated";

export type Statement = components["schemas"]["StatementResponse"];

export interface UploadStatementResult {
  statement: Statement;
  duplicate: boolean;
}

export async function listStatements(): Promise<Statement[]> {
  const response = await fetch("/api/statements");
  if (!response.ok) {
    throw new Error("Unable to load statements");
  }
  return (await response.json()) as Statement[];
}

export async function uploadStatement(
  accountReference: string,
  file: File,
): Promise<UploadStatementResult> {
  const form = new FormData();
  form.set("account_reference", accountReference);
  form.set("file", file);
  const response = await fetch("/api/statements", {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(body?.detail ?? "Statement import failed");
  }
  return {
    statement: (await response.json()) as Statement,
    duplicate: response.status === 200,
  };
}

export async function retryStatement(statementId: string): Promise<Statement> {
  const response = await fetch(`/api/statements/${statementId}/retry`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error("Unable to retry statement");
  }
  return (await response.json()) as Statement;
}

export async function reprocessStatementFromSource(
  statementId: string,
): Promise<Statement> {
  const response = await fetch(`/api/statements/${statementId}/reprocess`, {
    method: "POST",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(body?.detail ?? "Unable to reprocess statement from PDF");
  }
  return (await response.json()) as Statement;
}
