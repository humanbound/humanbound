# Contributing to humanbound

Thanks for considering a contribution. This document covers the essentials —
for extended guidance, see [docs.humanbound.ai/community/contributing](https://docs.humanbound.ai/community/).

## Quick start

```bash
git clone https://github.com/humanbound/humanbound.git
cd humanbound
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,engine,firewall]'
pre-commit install
pytest
```

That sequence gets you a working dev environment with the test suite, linter,
and formatter wired up.

## Using the library

```python
from humanbound import Bot, LocalRunner, Insight, OwaspAgentic
# ... see docs.humanbound.ai for the full usage walkthrough
```

## Filing issues

Bugs, feature requests, and questions all live in
[GitHub Issues](https://github.com/humanbound/humanbound/issues).
Use the provided templates:

- **Bug report** — include `humanbound` version, Python version, and a
  minimal reproduction
- **Feature request** — describe the problem first, then the proposed solution

**Do not file security issues publicly.** See [SECURITY.md](./SECURITY.md) for
the private disclosure channel.

## Developer Certificate of Origin (DCO) — required

This project does **not** use a CLA. Contributions are accepted under the
[Developer Certificate of Origin](./DCO.md) — the same lightweight mechanism
used by the Linux kernel, CNCF projects, and GitLab. You keep the copyright
to your work; it is licensed inbound = outbound under
[Apache-2.0](./LICENSE), exactly like the rest of the codebase.

There is nothing to sign — just add the `-s` flag when committing:

```bash
git commit -s -m "your message"
```

CI checks that every commit in a pull request carries the resulting
`Signed-off-by` trailer. Forgot one? `git commit --amend -s` (or
`git rebase --signoff main` for a whole branch) and force-push.

## Third-party code and licenses

To keep the project safely redistributable under Apache-2.0:

- **Code copied or vendored into this repository** must be under a
  permissive license: Apache-2.0, MIT, BSD (2- or 3-clause), or ISC.
  Include the upstream copyright notice and license text, and mention the
  origin in your PR description.
- **New runtime dependencies** must be permissively licensed as above;
  weak-copyleft dependencies (MPL-2.0, LGPL) are acceptable only as
  unmodified, dynamically imported packages and need maintainer sign-off.
- **GPL, AGPL, SSPL, or BSL-licensed code cannot be accepted** in any form
  (vendored, copied, or as a dependency).

If you're unsure about a license, ask in the PR before writing code.

## Change workflow

1. Fork the repository and create a branch off `main`
2. Make your changes — keep them focused (one concern per PR)
3. Add or update tests
4. Ensure `pytest`, `ruff check`, and `mypy` pass locally
5. Update [CHANGELOG.md](./CHANGELOG.md) under the `[Unreleased]` section
6. Open a pull request using the template

### Code style

- Formatter and linter: `ruff` (run via `pre-commit`)
- Type checker: `mypy` (see `pyproject.toml` for configuration)
- Every new `.py` file gets the SPDX header:
  ```
  # SPDX-License-Identifier: Apache-2.0
  # Copyright (c) 2024-2026 Humanbound
  ```

### Tests

- Every new feature needs a test
- Every bug fix needs a regression test
- Tests run against Python 3.10, 3.11, and 3.12 in CI

### Public vs internal APIs

Two import surfaces ship from this package:

| Import path | Stability |
|---|---|
| `from humanbound import X` | **Stable** — covered by semver |
| `from humanbound.<module> import Y` | **Stable** — covered by semver |
| `from humanbound_cli.* import Z` | **Internal** — may change any release |

If you're adding something meant for end-users, expose it via `humanbound`.
Keep CLI-specific internals in `humanbound_cli`.

## How changes ship

Maintainers cut releases on a rolling basis, not on a fixed cadence.

| Step | Who | What |
|---|---|---|
| PR review | Maintainer | Reviews code, tests, CHANGELOG |
| Merge to `main` | Maintainer | Squash merge |
| Tag `vX.Y.Z` | Maintainer | Triggers `release.yml` |
| Publish to PyPI | CI via Trusted Publishing | No tokens, sigstore-signed |
| GitHub Release | CI | Created from `CHANGELOG.md` entry |

Versioning follows [semver](https://semver.org). See
[docs.humanbound.ai/community/release-process/](https://docs.humanbound.ai/community/)
for the current cadence and supported-version matrix.

## Community

- **Discord** — [discord.gg/gQyXjVBF](https://discord.gg/gQyXjVBF) for questions
  and discussion
- **Discussions** — on the GitHub repo, for longer-form topics
- **Docs** — [docs.humanbound.ai](https://docs.humanbound.ai)

## Code of Conduct

Participation is governed by our [Code of Conduct](./CODE_OF_CONDUCT.md).
Violations can be reported privately to
[conduct@humanbound.ai](mailto:conduct@humanbound.ai).
