# Claude Function Executor Notes

> **Direction:** The function executor will continue to be used, but should be modelled after the MCP tool pattern. The `portfolio-mcp` server (`mcp_server.py` + `mcp_tools/`) is the guideline for how tools should be structured — clean input/output contracts, structured responses with `status` fields, and service-layer delegation rather than direct CLI calls.

---

- Harden auth and user context
  - Add a small helper get_user_id_or_error() and use it across all executors for consistent “Authentication required” responses.
  - Guard against missing/invalid user fields; avoid logging full user objects.

- Standardize error envelopes
  - Ensure every executor returns {success: false, error, type} with consistent keys; include a stable error_code where helpful.

- Prefer services over direct CLI calls where possible
  - For scenario runs, consider using PortfolioService.analyze_portfolio(PortfolioData.from_yaml(...), risk_limits_data?) to leverage caching and consistent result objects; still fine to keep current direct call if you prefer CLI-style text.

- Unify temporary file handling
  - Factor a small helper to create unique_name and return (scenario_file, risk_file) so naming/cleanup logic isn’t duplicated.
  - Redact absolute paths from logs; log only basename + user_id.

- Input validation improvements
  - Normalize holdings formats (percent vs decimal vs shares/dollars) into a canonical structure before writing YAML; return clear validation errors.

- Active portfolio state
  - self.active_portfolio_name can be per-user; ensure new instances per request or store active name keyed by user_id to avoid cross-user bleed if reused.

- Unknown function handling
  - Confirm unknown function errors return a friendly message and include available function names from ai_function_registry.get_all_function_names().

- Observability
  - Add a minimal audit log for create_scenario with user_id, scenario_name (no contents), and duration; include request_id/correlation_id if available.