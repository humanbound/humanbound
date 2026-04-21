# Changelog

All notable changes to `humanbound` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] — 2026-04-21

### Changed
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
  `CONTRIBUTING.md`, `DCO.md`, `TRADEMARK.md`, `ROADMAP.md`.
- **GitHub automation**: CI matrix (Python 3.10 / 3.11 / 3.12), release
  workflow with PyPI Trusted Publishing (OIDC) and sigstore attestations,
  issue/PR templates, dependabot, DCO enforcement.
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
