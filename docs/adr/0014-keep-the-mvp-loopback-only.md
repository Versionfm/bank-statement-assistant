# Keep the MVP loopback-only without user authentication

The single-user MVP will be reachable only from the k3s host through loopback access or port-forwarding, so it will not add a login system. PostgreSQL, vLLM, and MCP remain internal and no application endpoint may be exposed to the LAN or public network. Any future LAN access must first add authentication, HTTPS, CSRF protection, and a fresh security review rather than treating the local trust assumption as portable.
