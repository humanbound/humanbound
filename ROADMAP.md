# Roadmap

A snapshot of where `humanbound` is heading. This is a living document — dates
and scope may change. Open a [discussion](https://github.com/humanbound/humanbound/discussions)
or [issue](https://github.com/humanbound/humanbound/issues) to weigh in.

The authoritative, continuously-updated roadmap lives at
[docs.humanbound.ai/community/roadmap](https://docs.humanbound.ai/community/).

## Now — shipping in 2.0.x

- **Package rename** to `humanbound`, with transitional `humanbound-cli` stub
- **Public SDK surface** (`from humanbound import ...`) — stable contract
- **OSS hygiene**: CLA enforcement, CI matrix, Trusted Publishing + sigstore

## Next — target 2.1

- `humanbound.run_red_team()` — single-call, script-friendly entry point
- **Library-mode `LocalRunner`** — `output_dir=None` returns Insights in-memory
  without writing to disk; full parity with today's CLI behavior remains the
  default when `output_dir` is set
- Examples gallery on docs.humanbound.ai (banking, support, coding-assistant)
- Expanded API reference

## Later — on the horizon, not committed

- **Custom orchestrator authoring kit** — clean templates, local loader,
  `hb orchestrators list` picks up authored orchestrators from
  `~/.humanbound/orchestrators/`
- **Notebook-first DX** — Jupyter magic + rich display of Insights
- **Extract `humanbound-core`** as a separate lightweight package once a
  3rd-party plugin ecosystem emerges (LangChain-style migration — users'
  imports don't change)

## Not doing

- Not becoming a general-purpose ML-testing framework — Humanbound is scoped
  to AI-agent security testing
- Not forking / rehosting third-party orchestrators under the Humanbound brand
- Not adding a hosted service within this repo — that's the Humanbound Platform
  (separate, commercial, closed-source)

## Release cadence

See [CONTRIBUTING.md](./CONTRIBUTING.md) for how changes ship and the semver
policy. The supported-version matrix is on the docs site.

---

_Humanbound is the trading name of AI and Me Single-Member Private Company,
incorporated in Greece._
