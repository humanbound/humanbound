# Changelog

All notable changes to `humanbound` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.1.0] — 2026-05-11

### Added
- **`hb projects update --capabilities`** — declare an agent's
  capability surface (`tools`, `memory`, `inter_agent`, `reasoning_model`)
  via `key=value` pairs. Accepts `on/off`, `true/false`, `1/0`, `yes/no`,
  with `all=on/off` shorthand for setting the full set in one step.
- **`hb connect --repo` capability scan** — when scanning an agent
  repository, the CLI now infers the same capability surface from
  source-code patterns and offers to write it to the project scope.

### Changed
- **`hb test --test-category`, `--testing-level`, and `--lang` are now
  optional with no built-in fallback.** Omit any of them and the platform
  picks the default for that run. Specifying any flag still works exactly
  as before. Same applies to `hb connect --level` and the equivalent
  fields on the MCP `hb_run_test` tool.

## [2.0.3] — 2026-05-05

### Changed
- Slimmed the experiment stats schema. The HTML report's defense-rate
  KPI is now computed from pass/fail counts at render time.

### Fixed
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

[Unreleased]: https://github.com/humanbound/humanbound/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/humanbound/humanbound/releases/tag/v2.0.0
