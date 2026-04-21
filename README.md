<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-light.svg"/>
    <source media="(prefers-color-scheme: light)" srcset="assets/logo-dark.svg"/>
    <img src="assets/logo-dark.svg" alt="Humanbound" width="280"/>
  </picture>
</p>

<h3 align="center">humanbound</h3>

<p align="center">
  Open-source AI agent red-team engine, SDK, and CLI.
  <br/>
  Runs locally or against the Humanbound Platform. No login required to start.
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#cli-usage">CLI</a> &middot;
  <a href="#python-sdk">SDK</a> &middot;
  <a href="https://docs.humanbound.ai/">Documentation</a> &middot;
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/humanbound/"><img src="https://img.shields.io/pypi/v/humanbound?style=flat-square&color=FD9506" alt="PyPI version"/></a>
  <a href="https://pypi.org/project/humanbound/"><img src="https://img.shields.io/pypi/pyversions/humanbound?style=flat-square&color=FD9506" alt="Python versions"/></a>
  <a href="https://pypi.org/project/humanbound/"><img src="https://img.shields.io/pypi/dm/humanbound?style=flat-square&color=FD9506" alt="Downloads"/></a>
  <a href="https://github.com/humanbound/humanbound/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/humanbound/humanbound/ci.yml?style=flat-square&color=FD9506" alt="CI"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-FD9506?style=flat-square" alt="License"/></a>
  <a href="https://discord.gg/gQyXjVBF"><img src="https://img.shields.io/badge/discord-community-FD9506?style=flat-square" alt="Discord"/></a>
  <a href="https://docs.humanbound.ai/"><img src="https://img.shields.io/badge/docs-humanbound.ai-FD9506?style=flat-square" alt="Docs"/></a>
</p>

---

> 📖 **Full documentation** lives at [**docs.humanbound.ai**](https://docs.humanbound.ai/) —
> this README covers the essentials; the docs have the depth.

## Quick Start

### Install

```bash
pip install humanbound                       # CLI + SDK, core deps
pip install humanbound[engine]               # + OpenAI / Anthropic / Gemini providers
pip install humanbound[firewall]             # + humanbound-firewall runtime
pip install humanbound[engine,firewall]      # everything
```

### CLI usage

```bash
# Configure your LLM provider
export HB_PROVIDER=openai
export HB_API_KEY=sk-...

# Run a security test
hb test --endpoint ./bot-config.json --repo . --wait

# View results
hb posture                         # security score (0-100, A-F)
hb logs                            # conversation logs
hb report -o report.html           # HTML report
hb guardrails -o rules.yaml        # firewall rules
```

Full air-gap with [Ollama](https://ollama.com) — zero external API calls:

```bash
export HB_PROVIDER=ollama
export HB_MODEL=llama3.1:8b
hb test --endpoint ./bot-config.json --scope ./scope.yaml --wait
```

### Python SDK

```python
from humanbound import Bot, LocalRunner, OwaspAgentic, TestingLevel, EngineCallbacks

# Compose your own test pipeline
bot = Bot(endpoint="https://my-agent/chat", api_key="...")

class Callbacks(EngineCallbacks):
    def on_finding(self, insight): ...
    def on_progress(self, pct): ...

runner = LocalRunner()
# See docs.humanbound.ai for the full example
```

## Stability contract

| Import path | Stability |
|---|---|
| `from humanbound import X` | **Stable** — semver-protected |
| `from humanbound.<module> import Y` | **Stable** — semver-protected |
| `from humanbound_cli.* import Z` | **Internal** — may change any release, do not import from user code |

The full Tier-by-Tier walkthrough, orchestrator authoring guide, Platform
integration, and API reference all live on
[docs.humanbound.ai](https://docs.humanbound.ai/).

## What's shipping in 2.0

- **Clean name**: `humanbound` is the new PyPI install. The old
  `humanbound-cli` is a transitional stub that will be yanked after
  2026-06-20.
- **Public SDK namespace** alongside the CLI — use the CLI or drive the
  engine from Python. Both share the same implementation, so they can't
  drift.
- **Firewall integration**: `pip install humanbound[firewall]` pulls the
  renamed [`humanbound-firewall`](https://github.com/humanbound/humanbound-firewall)
  (formerly `hb-firewall`) alongside the CLI.

See [CHANGELOG.md](./CHANGELOG.md) for the full 2.0.0 release notes.

## Contributing

Contributions welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the dev
loop, release process, and DCO sign-off requirement (`git commit -s`).

- 🐛 [Report a bug](https://github.com/humanbound/humanbound/issues/new/choose)
- 💡 [Request a feature](https://github.com/humanbound/humanbound/issues/new/choose)
- 🔒 [Report a security issue](./SECURITY.md) — **not via public Issues**
- 💬 [Join Discord](https://discord.gg/gQyXjVBF)

## License

[Apache-2.0](./LICENSE). Free to use in any context — commercial or
open-source — with attribution. See [TRADEMARK.md](./TRADEMARK.md) for the
trademark policy. The code is open; the name is not.

The sibling project [`humanbound-firewall`](https://github.com/humanbound/humanbound-firewall)
is dual-licensed (AGPL-3.0 + commercial) — different product, different
license strategy.

---

<p align="center">
  <sub><em>Humanbound is the trading name of AI and Me Single-Member Private Company, incorporated in Greece.</em></sub>
</p>
