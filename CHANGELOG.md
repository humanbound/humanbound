# Changelog

All notable changes to `humanbound` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.6.0] — 2026-07-08

### Added
- **`TestConfig` is now part of the public SDK namespace**
  (`from humanbound import TestConfig`). It was the only missing piece for
  driving a full test run through the stable API: construct a `TestConfig`,
  pass it to `LocalRunner.start()`, poll `get_status()`, and read
  `get_posture()` / `get_result()` — no `humanbound_cli.*` imports needed.
- Package metadata: `Programming Language :: Python :: 3.13` and
  `Topic :: Scientific/Engineering :: Artificial Intelligence` classifiers, and a
  `Discord` entry in `[project.urls]` so PyPI shows the community link in the sidebar.

### Fixed
- **`import humanbound` crashed on a core-only install** (`pip install
  humanbound` without extras) with `ModuleNotFoundError: No module named
  'httpx'` — `httpx` was used at module level by the engine's bot adapter but
  only declared in the `[engine]` extra. `httpx` (and `certifi`, previously
  present only transitively) are now core dependencies. Affected at least
  2.2.0–2.5.0.

### Changed
- **README refresh** (new positioning + PyPI rendering fixes): leads with
  adversarial agent testing and the test-to-guardrail loop, adds real
  `bot-config.json` / `scope.yaml` examples and a runnable SDK example, and
  replaces the stale "What's shipping in 2.0" section with release highlights.
  All repo-relative links are now absolute GitHub URLs (they returned 404 on
  pypi.org) and the logo no longer relies on the `<picture>` block that PyPI's
  HTML sanitizer strips.
- Package summary now reads "Open-source adversarial testing engine, SDK, and
  CLI for AI agents."

## [2.5.0] — 2026-07-06

### Changed
- **`thread_init` is now optional in agent configs.** Stateless agents that need no session
  step can omit `thread_init` — or leave its endpoint empty, or set it to `null`. `hb test`
  and the local engine skip session creation when it isn't configured, mirroring the
  already-optional `thread_auth`; only `chat_completion` is required. Configs that do provide
  a `thread_init` endpoint are unchanged and still validated.

## [2.4.0] — 2026-07-03

### Added
- **`hb connect --vendor <id>`** discovers hosted-platform agents (currently `openai`) from a
  vendor credential and onboards the one you pick — the credential is read from the vendor's
  env var (e.g. `OPENAI_API_KEY`) or a hidden prompt, never from the command line. The picked
  agent becomes the project's integration. Requires being logged in.

### Changed
- The offline local engine (`hb test --local`) now fails fast with a clear error when given a
  hosted-platform connector config, instead of an opaque per-conversation failure. Connectors
  work via `hb connect` (SaaS); the offline engine remains classic HTTP/SSE/WebSocket only.

### Fixed
- `humanbound.__version__` now reads the installed package metadata instead of a hardcoded
  string that had been stuck at `2.0.1` since that release.

### Documentation
- Documented that `hb connect --endpoint` also accepts a hosted-platform connector block
  (`{ "connector": { "provider": "openai_assistants", "config": { … } } }`), not only the
  classic HTTP shape.

## [2.3.0] — 2026-06-29

### Added
- **`hb assessments terminate [id]`** stops a running assessment (defaults to
  the current/latest), and **`hb assessments show`** now defaults to the latest
  assessment when no id is given. `hb assessments` is now the single command for
  viewing and managing assessments.

### Deprecated
- **`hb campaigns`** is deprecated in favor of `hb assessments` (they are the
  same records). It is hidden from help and prints a deprecation notice; it
  still works.

## [2.2.1] — 2026-06-19

### Changed
- **`hb assessments` list is more informative:** added Posture (grade + score)
  and Drift columns, renamed the findings column to "New Findings" (explicitly
  the new findings detected in the run), renamed "Scope" to "Domain" (the field
  the API actually returns, previously shown blank), and render Started/
  Completed as dates instead of raw epoch numbers.
- **`hb assessments show` card is richer** instead of mirroring the list row:
  it now shows the posture trajectory (before → after) with a trend read,
  drift, coverage breadth (test groups + levels), the domain, and a
  human-readable run duration.

### Fixed
- **`hb campaigns` no longer errors and `hb campaigns terminate` now finds a
  running campaign.** The command read response fields that didn't match the
  campaign API response; it now aligns with the actual response shape so the
  plan renders and terminate locates the campaign.

## [2.2.0] — 2026-06-12

### Added
- **`hb experiments show <id> --config`** prints the configuration the
  experiment ran with (bot integration, scope, context) as reusable JSON.
- **`hb test --endpoint` accepts a full experiment configuration.** When the
  JSON contains an `integration` block (as printed by `--config`), the loader
  unwraps it automatically, so `hb experiments show <id> --config > bot-config.json`
  followed by `hb test --endpoint ./bot-config.json` works directly.
- "Where Findings Come From" docs section: how judge verdicts become insights
  and how insights reconcile into findings, with an insights-vs-findings table.

### Changed
- **Per-experiment analysis is now consistently called "insights"** (per the
  glossary), never "findings": `hb test` prints "Top Insights" with a
  not-tracked-across-runs clarifier, `hb experiments show` reports
  "Top Insights (showing 3 of N)" with an `hb report` pointer instead of
  "N findings" silently sliced to 3, and the HTML report section is "Insights".
- Insight explanations print in full instead of being truncated at 80 characters.
- The open-findings line in `hb test` output is labeled "Open Findings (project)"
  to make clear it is project-level lifecycle state, not this run's results.

### Fixed
- **Platform-mode insights no longer render severity as `UNKNOWN`.** The
  platform sends numeric 0-100 severity scores; the CLI now normalizes them
  to labels using the canonical boundaries (>=75 critical, >=50 high,
  >=25 medium, >=1 low, 0 info). The local presenter shares the same helper,
  eliminating off-by-one drift at the 75/50/25 boundaries.
- **`hb test --fail-on critical|high|medium|low` now actually trips in
  platform mode.** Numeric severities never matched the string comparison, so
  the CI gate silently passed regardless of findings; only `--fail-on any`
  worked. Severities are normalized before the comparison.

## [2.1.0] — 2026-06-09

### Added
- **Server-Sent Events (SSE) as a third chat-completion transport.** Set
  `"streaming": "sse"` in the agent config; the engine reads `data:`-line
  frames until `{"type":"end"}` or connection close.
- **Permissive content extraction.** The engine now walks the response JSON
  recursively for any known content key — customers can send native vendor
  shapes (OpenAI, Anthropic, RAG-style) without wrapping their bot's
  response. Extended set of recognized keys: `content`, `text`, `response`,
  `resp`, `answer`, `ans`, `message`, `reply`, `output`.

### Changed
- **Breaking: `streaming` in agent config is now an enum.** Use `null`
  (REST, default), `"websocket"`, or `"sse"`. Configs with the legacy
  boolean form (`"streaming": true` / `false`) are no longer accepted by
  the engine — migrate `false` to `null` (or omit the field) and `true`
  to `"websocket"`.

### Fixed
- **WebSocket streaming filter** previously always returned `False` due to a
  dict-vs-list comparison bug, causing the engine to rely on the fallback
  extractor for every chunk.

## [2.0.5] — 2026-06-05

### Fixed
- **`humanbound_cli.engine.llm.openai` no longer requires the optional OpenAI SDK
  just to import.** The `from openai import OpenAI` is deferred into `LLMStreamer`
  (its only consumer); the requests-based `LLMPinger` never needed it, so routing
  to the OpenAI pinger works without the `[engine]` extra installed.
- **`hb test` defers `test_category` / `testing_level` / `lang` to the backend when
  a caller leaves them unset.** `TestConfig` now defaults these to `None`, the
  platform runner omits unset keys from the request (so the backend applies its
  defaults), and local mode coalesces them to local defaults. Normal `hb test`
  usage — which always resolves concrete values — is unchanged.

### Added
- Presenter posture output now includes a `domain` field (`security` / `quality`,
  derived from the test category).
- **Three new flags on `hb connect`:**
  - **`--no-test`** skips the auto-test step after project creation. The
    project is still created and the risk dashboard still renders; the
    "Next" hints surface the `hb test` command to run later.
  - **`--test-category`** chooses which test family the auto-test step
    launches (default: `humanbound/adversarial/owasp_agentic`). Mirrors the
    same flag on `hb test` — pass the full category path (e.g.
    `humanbound/adversarial/owasp_single_turn`). Ignored when `--no-test`
    is set (warn-and-continue).
  - **`--scope ./scope.yaml`** loads a pre-made scope file (YAML or JSON)
    as input. Sent to `POST /scan` as a `text` source only — no agent
    probing. The backend analyzer returns its own scope; the CLI diffs it
    against your file and prompts to accept additive `permitted` /
    `restricted` intents before project creation. `--yes` auto-accepts.
    `--prompt`/`--repo`/`--openapi` are ignored when `--scope` is set;
    `--endpoint` is still honoured for `default_integration` but never
    sent as a scan source.

## [2.0.4] — 2026-06-02

### Added
- **Anonymous usage telemetry in the `hb` CLI (PostHog).** Measures the
  install → first test → login → platform usage funnel. Seven events
  (`install`, `init`, `test_start`, `test_complete`, `posture_view`,
  `findings_view`, `gated_command_hit`) with technical properties only —
  version, OS, command, durations, counts. **No** prompts, findings text,
  file paths, API URLs, hostnames, usernames, or env-var values are sent.
  Telemetry is **on by default** with a first-run notice on stderr;
  disable with `hb telemetry disable`, `HB_TELEMETRY_DISABLED=1`, or the
  community-standard `DO_NOT_TRACK=1`. Auto-disabled in CI, editable dev
  installs, and non-TTY contexts. Identity is an anonymous machine UUID
  (`~/.humanbound/telemetry.json`, mode 0600); after `hb login` it is
  aliased to the user's opaque Auth0 `sub` — email is never sent. Data
  goes to PostHog EU Cloud (Frankfurt), 24-month retention. See
  `PRIVACY.md` for the full disclosure (#27).
- **Schema.org JSON-LD on every docs page.** New MkDocs hook
  (`docs/hooks/schema.py`) emits Organization (referencing the marketing
  site's canonical `@id` for cross-domain entity continuity), WebSite,
  BreadcrumbList, TechArticle, and FAQPage (when a page declares `faq:`
  in frontmatter). Rendered via the existing `extrahead` template
  override, no plugin dependencies. `dateModified` is read from per-file
  git history (CI now uses `fetch-depth: 0` to make this work). Improves
  extractability by AI agents (ChatGPT, Perplexity, Claude) for
  Agent-Led Growth (#28).

### Removed
- **`hb sentinel` and `hb upload-logs` commands.** Both were deprecated
  and are superseded by `hb webhooks` and `hb logs upload` respectively.
  The command modules and their registrations are gone (#22).
- **The cloud-platform path in `hb connect` and its Microsoft connector.**
  The unreachable platform branch and `humanbound_cli/connectors/microsoft.py`
  were removed; `hb connect` now exposes only agent flags. The now-unused
  `msal` dependency is dropped (#22).

## [2.0.3] — 2026-05-11

### Changed
- Slimmed the experiment stats schema. The HTML report's defense-rate
  KPI is now computed from pass/fail counts at render time.

### Fixed
- **`hb connect` no longer creates orphaned projects when `--context`
  exceeds 1,500 chars.** The length check previously ran after
  `POST /scan` and `POST /projects`, so an over-long context returned an
  error to the caller but left a project registered on the backend. Each
  retry created another orphan — particularly problematic for the
  MCP-driven auto-retry path. The validation now runs alongside the other
  input guards, before any API call.
- **`hb logout` now revokes the backend session, not just local credentials.**
  Previously `HumanboundClient.logout()` only cleared the in-memory token
  state and the local token file, so the API session (and any concurrent
  platform or CLI session for the same user) stayed valid. Logout now calls
  `GET /logout` with the current API token before clearing local state.
  The call is best-effort so offline logout still works (#13).

### Removed
- **`compat/humanbound-cli/` and its CI publish jobs.** The transitional
  `humanbound-cli` PyPI stub was discontinued at 1.2.2 (released alongside
  `humanbound` 2.0.2). The compat source and the `build-stub`/`publish-stub`
  jobs in `.github/workflows/release.yml` are removed; future tags publish
  only `humanbound`. Existing `humanbound-cli` installs on PyPI continue to
  resolve to 1.2.2, which depends on `humanbound>=2.0.2,<3.0`.

## [2.0.2] — 2026-04-27

### Fixed
- **`hb logs --html` no longer crashes with `FileNotFoundError`.** The 2.0.1
  wheel published to PyPI was missing
  `humanbound_cli/templates/report_base.html`, so HTML report export
  (`hb logs <experiment-id> --html out.html`) failed on every install. Root
  cause: `*.html` was matched by `.gitignore`, so the template was never
  committed; CI checked out a tree without the file and built a wheel without
  it. `.gitignore` now carries `!humanbound_cli/templates/*.html` to keep
  bundled report templates tracked, and the template is committed.

### Deprecated
- **`humanbound-cli` is discontinued.** The transitional stub bumps to 1.2.2
  with a relaxed pin (`humanbound>=2.0.2,<3.0`) so existing
  `pip install humanbound-cli` invocations pull in this bug-fix release. This
  is the final stub release; no further `humanbound-cli` versions will be
  published. The `compat/humanbound-cli/` directory and its CI publish jobs
  will be removed in a follow-up after 2.0.2 ships. Migrate to
  `pip install humanbound`.

## [2.0.1] — 2026-04-22

### Fixed
- **`hb connect`** no longer raises `NameError` for authenticated users. The
  v1.0.0 open-core refactor removed `commands/init.py` but left dangling
  references inside `_connect_agent` to six helpers
  (`_SCAN_PHASES`, `_scan_with_progress`, `_display_scope`,
  `_display_dashboard`, `_get_source_description`, and the import of
  `_load_integration`). They are now restored inline in `commands/connect.py`.
- **`hb test --context` / `hb connect --context`** with a long literal
  string no longer crashes with `OSError: File name too long` (errno 63 on
  macOS). The code used `Path(value).is_file()` to decide whether the
  `--context` flag held a path or a literal; `Path.is_file()` calls
  `stat()`, which fails with `ENAMETOOLONG` rather than returning `False`
  when given a long string. Both commands now share `_resolve_context()`
  which wraps the stat in a try/except and falls back to literal on error.
- **Local test failures no longer print a raw Python traceback to users.**
  `engine/local_runner.py` previously logged the full `traceback.format_exc()`
  at ERROR level for every exception, including expected configuration
  errors (no LLM provider set, etc.). Tracebacks now log at DEBUG, so
  end-users see only the clean `Local test failed: ...` message. Run with
  `--debug` to see the full stack.
- **`hb test` no longer falls silently into local mode when the user is
  signed in but has no project selected.** The runner selection is still
  "login + project → Platform, otherwise local," but previously a logged-in
  user without a project would be routed to local, then fail with the
  misleading "No LLM provider configured" error. Users in this state now
  get a dedicated message pointing at `hb projects use`, `hb connect`, or
  `hb test --local`.

### Added
- **Local flow for `hb connect`** — when the user is not authenticated,
  `hb connect` now runs a lightweight scope extraction via the configured
  local LLM provider (`HB_PROVIDER` / `HB_API_KEY`) and writes `./scope.yaml`
  in the canonical template shape, consumable by `hb test --scope`.
- **Compliance template overlay** — the local flow auto-detects the agent's
  domain (banking, insurance, healthcare, legal, e-commerce) from its
  extracted business scope and overlays the corresponding regulatory
  restricted intents. The EU AI Act cross-cutting restrictions are applied
  unconditionally. Templates are bundled under
  `humanbound_cli/templates/compliance/` and are also published at
  [docs.humanbound.ai/compliance/](https://docs.humanbound.ai/compliance/).
  Deeper regulatory mapping, threat prioritisation with citations, and
  persistent project history remain available with `hb login`.
- New `humanbound_cli/engine/compliance.py` module exporting
  `detect_domain`, `apply_template`, `apply_eu_ai_act_only`, and
  `load_template`.

### Changed
- Ruff's `F821` (undefined name) rule is no longer globally suppressed in
  `pyproject.toml`. The six dangling references in `commands/connect.py`
  were shielded by this blanket ignore; the rule is now enforced across
  the tree to prevent a similar regression.
- `tests/unit/test_connect.py` rewritten to exercise `_connect_agent`'s
  body — HTTP is mocked at the wire level (`client.post`), and the local
  flow's LLM is stubbed via a fake `LLMPinger.ping`. The prior suite
  mocked `_connect_agent` wholesale, which allowed the v2.0.0 NameError
  to ship unnoticed.

## [2.0.0] — 2026-04-21

### Changed
- **Contribution policy**: external contributions are now accepted under the
  Humanbound Contributor License Agreement (see `CLA.md`) rather than the
  DCO sign-off, aligning with the sibling `humanbound-firewall` project. The
  library remains Apache-2.0 licensed.
- **Renamed package**: `humanbound-cli` → `humanbound`. This consolidates the
  Humanbound brand with a single PyPI install name. The old name remains on
  PyPI as a transitional meta-package through 2026-06-20, emitting a
  `DeprecationWarning` on import.
- **Copyright attribution**: LICENSE updated to name AI and Me Single-Member
  Private Company (also known as Humanbound) as the copyright holder,
  reflecting the company's current corporate identity.
- **License text**: corrected LICENSE from the earlier MIT stub to the full
  Apache-2.0 text matching `pyproject.toml`.
- SPDX headers standardized across source files: `Apache-2.0` + `Humanbound`.

### Added
- **Public SDK namespace** — new top-level `humanbound/` import, ships in the
  same wheel as `humanbound_cli/`:
  ```python
  from humanbound import (
      Bot, LocalRunner, Insight, TestingLevel,
      EngineCallbacks, OrchestratorModule,
      OwaspAgentic, OwaspSingleTurn, BehavioralQA,
  )
  ```
  This is the stable, semver-protected contract. `humanbound_cli.*` stays as
  the CLI implementation and is marked internal.
- `py.typed` markers on both `humanbound/` and `humanbound_cli/` for PEP 561.
- **`firewall` extra now depends on `humanbound-firewall`** (renamed from
  `hb-firewall`). `pip install humanbound[firewall]` pulls both packages
  together.
- **OSS hygiene documents**: `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  `CONTRIBUTING.md`, `CLA.md`, `TRADEMARK.md`, `ROADMAP.md`.
- **GitHub automation**: CI matrix (Python 3.10 / 3.11 / 3.12), release
  workflow with PyPI Trusted Publishing (OIDC) and sigstore attestations,
  issue/PR templates, dependabot, CLAAssistant configuration.
- **Dev tooling**: `.pre-commit-config.yaml`, ruff + mypy configuration in
  `pyproject.toml`.
- Transitional stub `humanbound-cli==1.2.0` published alongside so existing
  users get a clear deprecation signal.

### Deprecated
- The `humanbound-cli` PyPI name. Install `humanbound` instead. The stub will
  be yanked on or after 2026-06-20.

### Coming in 2.1
- `humanbound.run_red_team()` — single-call high-level helper for notebook /
  script usage
- Library-mode `LocalRunner` with `output_dir=None` (in-memory only)
- Expanded public-API documentation and examples gallery on docs.humanbound.ai

## [1.1.0]

Last release as `humanbound-cli`. See the
[old release](https://pypi.org/project/humanbound-cli/1.1.0/) on PyPI for
notes — that history is preserved there and is not re-documented here.

[Unreleased]: https://github.com/humanbound/humanbound/compare/v2.5.0...HEAD
[2.5.0]: https://github.com/humanbound/humanbound/releases/tag/v2.5.0
[2.4.0]: https://github.com/humanbound/humanbound/releases/tag/v2.4.0
[2.3.0]: https://github.com/humanbound/humanbound/releases/tag/v2.3.0
[2.0.0]: https://github.com/humanbound/humanbound/releases/tag/v2.0.0
