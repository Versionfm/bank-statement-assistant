# MCP transport and deployment for the Financial Assistant

Research date: 2026-09-01

## Recommendation

Run the Financial Assistant's MCP adapter as a separate Python process/container using **Streamable HTTP**, while importing the same application service modules used by the FastAPI API. For the single-user MVP, place that container in the **same Pod** as the Financial Assistant backend and bind MCP to Pod-local loopback. Do not create an MCP Ingress or expose it to the browser.

This gives the MCP process an explicit lifecycle and a real production transport without opening another cluster-wide network endpoint. If independent rollout or scaling later becomes valuable, move the unchanged MCP container behind a private ClusterIP Service, add a NetworkPolicy that permits only the Financial Assistant workload, and add conformant service authentication. That later move does not require changing tools or domain modules.

Use one replica initially. Pin compatible MCP Python SDK client/server versions and target the current `2026-07-28` protocol behavior. Store conversations, financial records, Correction Proposals, and audit history in PostgreSQL; do not treat MCP connection or transport state as application state.

## stdio versus Streamable HTTP

| Concern | stdio | Streamable HTTP |
|---|---|---|
| Process model | The client launches and owns a child process. | The server runs independently and accepts requests at an HTTP endpoint. |
| Best fit | Desktop/local subprocess integrations and isolated tests. | A deployed process or container. |
| Lifecycle | Entering the client context starts the child; leaving closes input, waits, then terminates it if needed. | Kubernetes/ASGI owns server lifecycle; the client connects to a URL. |
| Security boundary | The launching process and explicitly passed environment; there is no HTTP authorization layer. | Host/Origin validation plus optional HTTP authorization; network exposure must be constrained. |
| Operational consequence here | Couples MCP availability and restarts to the assistant process and requires clean protocol-only stdout. | Works unchanged as same-Pod loopback now or a private Service later. |

The MCP specification defines stdio as newline-delimited JSON-RPC to a client-launched subprocess and reserves stdout for protocol messages. Streamable HTTP is a single POST endpoint served by an independent process. The Python SDK accordingly describes stdio as the local-subprocess option and Streamable HTTP as the deployed option. ([MCP stdio specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio), [MCP Streamable HTTP specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http), [Python SDK server transport guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/index.md))

The SDK also supports an in-memory `Client(server)` embedding API with no process, port, or wire. It is useful for unit/integration tests and is a valid fallback if the application later decides MCP does not need an independently deployed boundary. A URL selects Streamable HTTP; `StdioServerParameters` selects a spawned child. ([Python SDK client transports](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/transports.md))

## Lifecycle and session implications

MCP `2026-07-28` removed the initialization handshake and protocol-level sessions. Every request carries its protocol metadata, and each Streamable HTTP request is an independent POST. Therefore:

- the MCP server must not hold chat history or user financial state in a transport session;
- each tool call must be complete from its validated arguments, authenticated request context, and durable application data;
- a request may be handled by any replica if the service is scaled later;
- the assistant backend should reuse an HTTP client for connection pooling, but correctness must not depend on keeping one connection alive.

The Python SDK serves modern and legacy protocol eras. Modern requests do not use `Mcp-Session-Id`; legacy clients can still create in-memory sessions unless `stateless_http=True` is selected. Pinning both application components to a compatible SDK/protocol version avoids accidental legacy session behavior. ([MCP transport overview and compatibility](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/index.mdx), [current Streamable HTTP behavior](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http), [Python SDK deployment behavior](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/deploy.md))

Use the MCP server lifespan to open and close its database pool or application service container once per server process. If MCP is ever mounted inside the FastAPI ASGI app instead of running separately, the host application's lifespan must explicitly enter `mcp.session_manager.run()`; a mounted sub-application's lifespan does not run automatically. ([Python SDK lifespan](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/handlers/lifespan.md), [Python SDK ASGI integration](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/asgi.md))

Do not use MCP multi-round-trip state for the MVP Correction Proposal approval. If multi-round-trip tools are introduced and the MCP deployment is scaled, all replicas must share the request-state sealing keys and audience/server name or a retry can fail on another worker. ([Python SDK deployment guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/deploy.md#requeststate-across-workers))

## Security posture

The browser calls the Financial Assistant API, never MCP directly. For the same-Pod MVP:

- bind MCP only to `127.0.0.1` inside the Pod;
- create no MCP Service or Ingress;
- configure an exact Host allowlist for the loopback endpoint;
- allow no browser origins and configure no CORS;
- keep PostgreSQL credentials and authorization decisions out of tool arguments.

If MCP moves to its own Pod, use a private ClusterIP Service, exact Kubernetes service DNS names in `allowed_hosts`, no Ingress, and a NetworkPolicy allowing only the Financial Assistant workload. These k3s controls are deployment inferences; they supplement rather than replace application authentication.

The Streamable HTTP specification requires validation of a present `Origin`, recommends localhost binding for local servers, and recommends authentication. The Python SDK enables localhost Host/Origin protection by default; a deployed service name must be explicitly included through `TransportSecuritySettings`, otherwise requests are rejected. ([MCP Streamable HTTP security](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http#security-endpoint), [Python SDK Host and Origin allowlists](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/deploy.md#before-anything-else-the-host-allowlist))

MCP authorization is optional. If enabled for HTTP, it should follow the MCP OAuth 2.1 resource-server flow; tokens are sent and validated on every HTTP request. The Python SDK exposes this through `AuthSettings` plus a `TokenVerifier`. stdio and in-memory clients bypass that HTTP authorization layer. ([MCP authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization), [Python SDK authorization](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/authorization.md))

For the loopback-only MVP, deferring OAuth is reasonable only as an explicit single-Pod trust-boundary decision. Before MCP receives a ClusterIP reachable by other workloads, prefer conformant service authentication in addition to NetworkPolicy; do not invent a query-string secret or expose an unauthenticated endpoint to LAN/public ingress.

## Process boundary versus code boundary

The MCP adapter should be a separate process, but **not** a separate implementation of financial behavior. Its tool handlers should be thin adapters over shared Python application services:

```text
Financial Assistant -> MCP client -> thin MCP tool adapter
                                      |
                                      v
                           shared application services
                                      |
                                      v
                                  PostgreSQL
```

Share modules for transaction search, report computation, statement review, classification provenance, and Correction Proposal creation. Do not expose arbitrary SQL and do not reimplement report arithmetic inside MCP. Python SDK tools are ordinary typed functions, and the server lifespan can supply a shared database pool or service container to handlers. ([Python SDK tools](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/servers/tools.md), [Python SDK lifespan](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/handlers/lifespan.md))

## Read-only tools and Correction Proposals

Use these annotations:

| Tool | Annotations |
|---|---|
| `search_transactions` | `read_only_hint=True`, `open_world_hint=False` |
| `get_monthly_report` | `read_only_hint=True`, `open_world_hint=False` |
| `get_statement_review` | `read_only_hint=True`, `open_world_hint=False` |
| `get_classification_details` | `read_only_hint=True`, `open_world_hint=False` |
| `propose_correction` | `read_only_hint=False`, `destructive_hint=False`, `open_world_hint=False`; add `idempotent_hint=True` only when a server-enforced idempotency key makes retries safe |

Persisting a Correction Proposal is an additive mutation even though it does not alter a Transaction. Tool annotations are behavioral hints, not authorization or enforcement. Enforce read-only behavior in application services and database permissions, validate typed inputs and structured outputs, paginate result sets, and audit each call. The Python SDK generates input schemas from type hints, validates constrained arguments, supports output schemas, and explicitly warns that annotations are not security controls. ([Python SDK tool schemas and annotations](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/servers/tools.md), [MCP tool schemas and security guidance](https://modelcontextprotocol.io/specification/2026-07-28/server/tools))

`propose_correction` should create only an immutable, non-binding proposal containing the Transaction ID and expected revision, before/after values, reason, cited evidence, idempotency key, creation time, and model/prompt identity. It must never apply a Correction.

The chat UI displays the before/after diff. Explicit approval goes through the ordinary application API, which checks that the Transaction revision still matches, applies the Correction through the domain service, records the audit event, reruns validation, and updates live report projections. Rejection records the outcome without touching the Transaction. This application-level flow follows the MCP guidance that users should be able to deny tool invocations and that sensitive operations should display inputs and require confirmation. ([MCP tool user-interaction and security guidance](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#user-interaction-model))

## Decision summary

- Transport: **Streamable HTTP**.
- MVP placement: separate MCP container in the Financial Assistant Pod, loopback-only.
- Later placement: separate Deployment plus private ClusterIP only when independent rollout/scaling is useful.
- Protocol state: target `2026-07-28`; no chat or financial state in MCP sessions.
- Code: share application service modules; MCP remains a thin adapter.
- Tools: four genuinely read-only query tools plus one additive, non-binding proposal tool.
- Mutation: only the normal application API may apply a user-confirmed Correction.
