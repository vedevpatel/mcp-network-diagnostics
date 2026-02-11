# Working Preferences

## Commit Messages

**Format:** Short imperative title (50 chars max), detail in body when needed.

**Style:**
- Use colon-separated scoping for features: `"Consumer dashboard: guest session, tenant scoping, per-identity baseline, rate limits, validation"`
- No emojis, no "chore:", no conventional-commits prefixes
- Multi-line body when the change spans multiple components, formatted as a list
- Example from this project:
  ```
  Fill test gaps: topology loader, IOS-XE/NX-OS parsers, Prometheus, remaining tools

  test_topology_loader.py — ${ENV_VAR} substitution (single, embedded,
    multiple, nested), missing-var EnvironmentError, missing file,
    bad YAML, thresholds/local_device round-trip.

  test_iosxe_parsers.py — memory (Processor Pool + statistics formats,
    garbage), cpu (standard + alt format, missing line)...
  ```

**Co-authorship:** Never append "written by claude code" when AI assists

## Code Style

**Docstrings:**
- Module-level: explain *why* the module exists, what problem it solves
- Function-level: terse, imperative. Focus on contract, not implementation.
- Example:
  ```python
  def find_alternate_paths(graph, primary, bottleneck_devices, cutoff=5):
      """
      Find alternate paths that avoid one or more bottleneck devices.

      Enumerates all simple paths from primary[0] to primary[-1], drops the
      primary path itself, scores each candidate by total latency, and tags
      each one with which bottleneck devices it successfully avoids.
      """
  ```

**Comments:**
- Section headers: `# ===========================================================================`
- Inline: only when logic isn't self-evident. No "obvious" comments.
- Rationale comments when the *why* is non-obvious:
  ```python
  # IOS-XR has no easy CPU metric; defaults to 50.0
  cpu_usage = 50.0
  ```

**Tests:**
- Deterministic: pin seeds, mock external dependencies, no flakiness
- Docstrings explain the test's purpose and any non-obvious setup
- Group related tests in classes
- Use descriptive test names: `test_alternate_paths_sorted_avoids_all_first`

**Naming:**
- Functions: snake_case, verb-first (`find_path`, `parse_cpu_usage`)
- Classes: PascalCase, noun-first (`IOSXRCollector`, `MetricCache`)
- Private helpers: leading underscore (`_fresh_collector`, `_interpolate`)

## Workflow

**Plan before code:**
- For non-trivial tasks, write out the approach first
- List files to read, understand dependencies, then code
- No guessing — read the source, trace the actual logic

**Testing:**
- Write tests in parallel with implementation when adding new surface area
- Run the full suite before committing
- 100% pass rate or don't commit

**No over-engineering:**
- Only add what's asked for
- Don't refactor surrounding code unless it's blocking
- No speculative features

**Minimize noise:**
- No emojis in code or commits unless explicitly requested
- No "improvements" that weren't asked for
- No documentation files (README, CONTRIBUTING, etc.) unless explicitly requested

## Preferences

- **Don't ask for permission** on straightforward tasks. Do the work, explain after.
- **Do ask** before destructive git operations (force push, reset --hard, rewriting history), or when requirements are ambiguous and multiple approaches exist.
- **Communication:** Terse, precise. No filler. Say what you're doing and why, not how you feel about it.
- **Errors:** When blocked, explain the blocker clearly and suggest a path forward. Don't retry the same failing approach.

## This Project Specifically

**Audience priority:**
1. **Consumers** — people using the web dashboard or calling the API to monitor their network
2. **Developers** — people integrating the MCP server into their AI workflow (Claude Desktop, custom clients)
3. **Network operators** — the underlying use case, but surfaced through the above UX layers

**Architecture:**
- **Web dashboard** (FastAPI + Jinja2) — primary consumer UX, tenant-isolated, guest sessions
- **MCP server** — stdio transport for Claude Desktop, streamable-http for remote API access
- **Security layer** — auth, rate limiting, SSRF protection, command injection blocking, session management
- **Storage** — SQLite + repositories for trends, configs, incidents, baselines (tenant-scoped)

**Collectors:**
- Simulated: zero dependencies, deterministic (with seed), injected anomalies on a schedule
- SSH: real Cisco devices (IOS-XR, IOS-XE, NX-OS)
- Prometheus: real metrics via PromQL

**Test strategy:**
- Use simulated collector for tool/pathfinder tests (seeded)
- Mock SSH connections for collector tests (Netmiko)
- Mock Prometheus client for metric tests
- Mock database for storage/repository tests

**Security:**
- This is a read-only diagnostic platform with SSH + HTTP transports
- SSH collector validates `show`-only commands (no exec/config)
- HTTP transport: API keys, rate limiting (per-tenant, per-identity), SSRF protection, audit logs
- Dashboard: session cookies, guest-mode with rate limits, tenant isolation

**Philosophy:**
- **Consumer-first:** If someone opens the dashboard tomorrow, it should "just work" with simulated data and be immediately useful
- **Developer-friendly:** MCP server works with zero config (`--collector simulated`), Claude Desktop integration is 5 lines of JSON
- **Production-ready:** Real networks shouldn't break the system — graceful degradation, clear error messages, no silent failures
- **Explicit over implicit:** Thresholds in YAML, not magic numbers. Tenant ID in URLs, not session state. Rate limits visible in responses.
