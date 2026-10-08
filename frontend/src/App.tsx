import { type FormEvent, useEffect, useState } from "react";
import { HashRouter, NavLink, useLocation } from "react-router-dom";

import { type BackendStatus, getBackendStatus } from "./api/health";
import {
  listStatements,
  reprocessStatementFromSource,
  retryStatement,
  type Statement,
  uploadStatement,
} from "./api/statements";
import { TransactionsView } from "./components/TransactionsView";
import { copy } from "./copy";
import { ReportsPage } from "./pages/ReportsPage";
import "./styles.css";

const statusLabel: Record<BackendStatus, string> = {
  checking: "Checking foundation…",
  ready: "Foundation ready",
  unavailable: "Backend unavailable",
};

const stageLabel: Record<Statement["current_stage"], string> = {
  accept: "Accepting statement",
  extract_text: "Extracting text",
  extract_transactions: "Extracting transactions",
  validate: "Validating balances",
  revalidate: "Revalidating corrected values",
  classify: "Classifying transactions",
  review: "Preparing review",
  publish_state: "Review available",
};

function App() {
  return (
    <HashRouter>
      <AppContent />
    </HashRouter>
  );
}

function AppContent() {
  const location = useLocation();
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("checking");
  const [statements, setStatements] = useState<Statement[]>([]);
  const [accountReference, setAccountReference] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importStatus, setImportStatus] = useState<string | null>(null);
  const [transactionRefreshKey, setTransactionRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    void getBackendStatus().then((status) => {
      if (active) {
        setBackendStatus(status);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!statements.some((statement) => statement.status === "processing"))
      return;
    const timer = window.setInterval(() => {
      void listStatements()
        .then((items) => {
          const processingStatementFinished = items.some((item) => {
            const previous = statements.find(
              (statement) => statement.id === item.id,
            );
            return (
              previous?.status === "processing" && item.status !== "processing"
            );
          });
          if (processingStatementFinished) {
            setTransactionRefreshKey((current) => current + 1);
          }
          setStatements(items);
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [statements]);

  useEffect(() => {
    let active = true;
    void listStatements()
      .then((items) => {
        if (active) {
          setStatements((current) => [
            ...current,
            ...items.filter((item) =>
              current.every((existing) => existing.id !== item.id),
            ),
          ]);
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (file === null) return;
    if (!accountReference.trim()) {
      setImportStatus(null);
      setImportError(
        "Enter an account reference before importing a statement.",
      );
      return;
    }
    setUploading(true);
    setImportError(null);
    setImportStatus(
      "Uploading the PDF. Processing will start as soon as it is accepted.",
    );
    try {
      const { statement, duplicate } = await uploadStatement(
        accountReference,
        file,
      );
      setStatements((current) => [
        statement,
        ...current.filter((item) => item.id !== statement.id),
      ]);
      setTransactionRefreshKey((current) => current + 1);
      setImportStatus(
        duplicate
          ? duplicateImportMessage(statement)
          : importAcceptedMessage(statement),
      );
      setFile(null);
    } catch (error) {
      setImportStatus(null);
      setImportError(
        error instanceof Error ? error.message : "Statement import failed",
      );
    } finally {
      setUploading(false);
    }
  }

  async function handleRetry(statementId: string) {
    try {
      const retried = await retryStatement(statementId);
      setStatements((current) =>
        current.map((item) => (item.id === retried.id ? retried : item)),
      );
      setTransactionRefreshKey((current) => current + 1);
    } catch (error) {
      setImportError(
        error instanceof Error ? error.message : "Unable to retry statement",
      );
    }
  }

  async function handleReprocessFromSource(statementId: string) {
    try {
      const reprocessed = await reprocessStatementFromSource(statementId);
      setStatements((current) =>
        current.map((item) =>
          item.id === reprocessed.id ? reprocessed : item,
        ),
      );
      setTransactionRefreshKey((current) => current + 1);
    } catch (error) {
      setImportError(
        error instanceof Error
          ? error.message
          : "Unable to reprocess statement from PDF",
      );
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a
          className="brand"
          href="#main"
          aria-label={`${copy.productName} home`}
        >
          <span className="brand-mark" aria-hidden="true">
            B
          </span>
          <span>{copy.productName}</span>
        </a>
        <span className={`system-status system-status--${backendStatus}`}>
          <span className="status-dot" aria-hidden="true" />
          {statusLabel[backendStatus]}
        </span>
      </header>

      <nav className="primary-nav" aria-label="Primary navigation">
        <NavLink
          end
          className={({ isActive }) =>
            `nav-link ${isActive ? "nav-link--active" : ""}`
          }
          to="/"
        >
          Statements
        </NavLink>
        <NavLink
          className={({ isActive }) =>
            `nav-link ${isActive ? "nav-link--active" : ""}`
          }
          to="/transactions"
        >
          Transactions
        </NavLink>
        <NavLink
          className={({ isActive }) =>
            `nav-link ${isActive ? "nav-link--active" : ""}`
          }
          to="/reports"
        >
          Reports
        </NavLink>
        {copy.navigation.slice(3).map((item) => (
          <span
            className="nav-link nav-link--disabled"
            aria-disabled="true"
            key={item}
          >
            <span>{item}</span>
            <small>Planned</small>
          </span>
        ))}
      </nav>

      {location.pathname === "/reports" ? (
        <ReportsPage statements={statements} />
      ) : (
        <main id="main">
          <section className="hero">
            <div className="hero-copy">
              <p className="eyebrow">{copy.eyebrow}</p>
              <h1>{copy.welcomeTitle}</h1>
              <p className="lede">{copy.welcomeBody}</p>
              <p className="foundation-note">{copy.foundationNote}</p>
            </div>
            <div className="report-preview" aria-label="Monthly report preview">
              <div className="preview-heading">
                <span>Monthly report</span>
                <span className="preview-pill">EUR</span>
              </div>
              <div className="preview-total">
                <span>Net spending</span>
                <strong>—</strong>
              </div>
              <div className="preview-bars" aria-hidden="true">
                <span style={{ "--bar-size": "72%" } as React.CSSProperties} />
                <span style={{ "--bar-size": "48%" } as React.CSSProperties} />
                <span style={{ "--bar-size": "31%" } as React.CSSProperties} />
              </div>
              <p>
                Reports will appear after a supported statement has been
                reviewed.
              </p>
            </div>
          </section>

          <section
            className="statement-workspace"
            id="statements"
            aria-labelledby="import-title"
          >
            <div className="import-card">
              <p className="eyebrow">Statement intake</p>
              <h2 id="import-title">{copy.importTitle}</h2>
              <p>{copy.importBody}</p>
              <form noValidate onSubmit={(event) => void handleUpload(event)}>
                <label>
                  Account reference
                  <input
                    required
                    value={accountReference}
                    onChange={(event) =>
                      setAccountReference(event.target.value)
                    }
                    placeholder="BPI Main"
                  />
                </label>
                <label>
                  PDF statement
                  <input
                    required
                    type="file"
                    accept="application/pdf,.pdf"
                    onChange={(event) =>
                      setFile(event.target.files?.[0] ?? null)
                    }
                  />
                </label>
                <button type="submit" disabled={uploading || file === null}>
                  {uploading ? "Uploading PDF…" : "Import statement"}
                </button>
                <div
                  className="import-feedback"
                  aria-live="polite"
                  aria-atomic="true"
                >
                  {importStatus !== null && (
                    <p className="form-status" role="status">
                      {importStatus}
                    </p>
                  )}
                  {importError !== null && (
                    <p className="form-error">{importError}</p>
                  )}
                </div>
              </form>
            </div>
            <div className="statement-list" aria-live="polite">
              <div className="section-heading">
                <h2>Statements</h2>
                <span>{statements.length}</span>
              </div>
              {statements.length === 0 ? (
                <p className="empty-state">No statements imported yet.</p>
              ) : (
                statements.map((statement) => {
                  const failedAction = failedStatementAction(
                    statement.current_stage,
                  );
                  return (
                    <article className="statement-row" key={statement.id}>
                      <div>
                        <strong>{statement.original_filename}</strong>
                        <span>{statement.account_reference}</span>
                      </div>
                      <div
                        className={`statement-state statement-state--${statement.status}`}
                      >
                        <strong>{stageLabel[statement.current_stage]}</strong>
                        <span>{statement.status.replace("_", " ")}</span>
                        {statement.status === "failed" &&
                          (failedAction.reprocessFromSource ? (
                            <button
                              type="button"
                              onClick={() =>
                                void handleReprocessFromSource(statement.id)
                              }
                            >
                              {failedAction.label}
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => void handleRetry(statement.id)}
                            >
                              {failedAction.label}
                            </button>
                          ))}
                      </div>
                      {(statement.last_error_code !== null ||
                        statement.review_findings.length > 0) && (
                        <div className="statement-findings">
                          {statement.last_error_code !== null && (
                            <span>
                              Failure:{" "}
                              {statement.last_error_code.replaceAll("_", " ")}
                            </span>
                          )}
                          {statement.review_findings.map((finding, index) => (
                            <span key={`${statement.id}-finding-${index}`}>
                              {findingMessage(finding)}
                            </span>
                          ))}
                        </div>
                      )}
                    </article>
                  );
                })
              )}
            </div>
          </section>

          <TransactionsView
            statements={statements}
            refreshKey={transactionRefreshKey}
          />

          <section className="principles" aria-label="Application principles">
            <Principle
              number="01"
              title={copy.privacyTitle}
              body={copy.privacyBody}
            />
            <Principle
              number="02"
              title={copy.evidenceTitle}
              body={copy.evidenceBody}
            />
            <Principle
              number="03"
              title={copy.exactTitle}
              body={copy.exactBody}
            />
          </section>
        </main>
      )}
    </div>
  );
}

interface PrincipleProps {
  number: string;
  title: string;
  body: string;
}

function Principle({ number, title, body }: PrincipleProps) {
  return (
    <article className="principle">
      <span className="principle-number">{number}</span>
      <h2>{title}</h2>
      <p>{body}</p>
    </article>
  );
}

function findingMessage(finding: Record<string, unknown>): string {
  if (typeof finding.message === "string") return finding.message;
  if (typeof finding.code === "string")
    return finding.code.replaceAll("_", " ");
  return "Review required";
}

function importAcceptedMessage(statement: Statement): string {
  if (statement.status === "processing") {
    return "PDF accepted. Processing has started; the status below updates automatically.";
  }
  if (statement.status === "failed") {
    return "PDF was accepted but processing failed. Review the failure details below.";
  }
  return "PDF is already processed. Review its current status below.";
}

function duplicateImportMessage(statement: Statement): string {
  if (statement.status === "failed") {
    const action = failedStatementAction(statement.current_stage);
    return `This PDF is already imported and failed during ${stageLabel[statement.current_stage]}. Use ${action.label} below to run the fixed stage again.`;
  }
  return "This PDF is already imported. Showing its current status below.";
}

function failedStatementAction(stage: Statement["current_stage"]): {
  label: "Retry" | "Reprocess from PDF";
  reprocessFromSource: boolean;
} {
  if (stage === "extract_text" || stage === "extract_transactions") {
    return { label: "Reprocess from PDF", reprocessFromSource: true };
  }
  return { label: "Retry", reprocessFromSource: false };
}

export default App;
