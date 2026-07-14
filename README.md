<p align="center">
  <img src="https://raw.githubusercontent.com/humanbound/humanbound/main/assets/logo-dark.svg" alt="Humanbound" width="280"/>
</p>

<h3 align="center">humanbound</h3>

<p align="center">
  Open-source adversarial testing engine, SDK, and CLI for AI agents.
  <br/>
  Attack your agent the way real users and attackers will: live endpoints,
  multi-turn conversations, tool abuse. Then turn every failure into a firewall rule.
  <br/>
  Runs locally or against the Humanbound Platform. No login required to start.
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#from-test-results-to-guardrails">Test-to-Guardrail Loop</a> &middot;
  <a href="#python-sdk">SDK</a> &middot;
  <a href="https://docs.humanbound.ai/">Documentation</a> &middot;
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/humanbound/"><img src="https://img.shields.io/pypi/v/humanbound?style=flat-square&color=FD9506" alt="PyPI version"/></a>
  <a href="https://pypi.org/project/humanbound/"><img src="https://img.shields.io/pypi/pyversions/humanbound?style=flat-square&color=FD9506" alt="Python versions"/></a>
  <a href="https://pypi.org/project/humanbound/"><img src="https://img.shields.io/pypi/dm/humanbound?style=flat-square&color=FD9506" alt="Downloads"/></a>
  <a href="https://github.com/humanbound/humanbound/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/humanbound/humanbound/ci.yml?style=flat-square&color=FD9506" alt="CI"/></a>
  <a href="https://github.com/humanbound/humanbound/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-FD9506?style=flat-square" alt="License"/></a>
  <a href="https://discord.gg/WgTMpmSFtN"><img src="https://img.shields.io/badge/discord-community-FD9506?style=flat-square" alt="Discord"/></a>
  <a href="https://docs.humanbound.ai/"><img src="https://img.shields.io/badge/docs-humanbound.ai-FD9506?style=flat-square" alt="Docs"/></a>
</p>

---

> 📖 **Full documentation** lives at [**docs.humanbound.ai**](https://docs.humanbound.ai/) —
> this README covers the essentials; the docs have the depth.

## Why Humanbound

Most testing tools test prompts. Humanbound tests **agents**: it drives
multi-turn conversations against your real endpoint, probes tool use and scope
boundaries, and scores the results against your security policy. When tests
fail, `hb guardrails` converts the findings into deployable firewall rules —
so the same run that finds a hole also patches it.

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

# Point Humanbound at your agent and run an adversarial test
hb test --endpoint ./bot-config.json --repo . --wait

# View results
hb posture                         # security score (0-100, A-F)
hb logs                            # full multi-turn conversation logs
hb report -o report.html           # HTML report
```

Full air-gap with [Ollama](https://ollama.com) — zero external API calls:

```bash
export HB_PROVIDER=ollama
export HB_MODEL=llama3.1:8b
hb test --endpoint ./bot-config.json --scope ./scope.yaml --wait
```

### Describe your agent

`bot-config.json` tells the engine how to call your agent's API:

```json
{
  "chat_completion": {
    "endpoint": "https://your-bot.com/chat",
    "headers": {"Authorization": "Bearer <token>"},
    "payload": {"message": "$PROMPT"}
  },
  "thread_init": {
    "endpoint": "https://your-bot.com/sessions",
    "headers": {"Authorization": "Bearer <token>"},
    "payload": {}
  }
}
```

- **`chat_completion`** (required) — the request the engine sends for every
  conversation turn: your agent's chat endpoint.
- **`thread_init`** (optional) — called once before each conversation to
  create a session/thread. Stateless agents simply omit it (same for
  `thread_auth`, an optional separate auth step).

The `headers` and `payload` above are examples — they must match your agent's
actual API input schema. The engine sends them as-is after substituting the
placeholders:

- **`$PROMPT`** — replaced with the user message of each attack turn. If no
  `$PROMPT` appears in the payload, the engine appends the message as an
  OpenAI-style `messages` array instead.
- **`$CONVERSATION`** — replaced with the prior turns of the conversation,
  for stateless agents that expect the full history in every request.

`scope.yaml` declares what the agent is — and is not — allowed to do. The
`restricted` list is what turns generic jailbreak probes into targeted
tool-abuse attacks:

```yaml
business_scope: "Customer support for Acme Bank"
permitted:
  - Provide account balance and transaction info
  - Process routine transfers within limits
restricted:
  - Process transfers above 10,000 EUR   # tool-abuse boundary the engine attacks
  - Access internal system records
more_info: "HIGH: finance domain agent"
```

See [Agent Configuration](https://docs.humanbound.ai/getting-started/agent-config/)
and [Scope Discovery](https://docs.humanbound.ai/local-engine/scope-discovery/)
for the full specifications.

## From test results to guardrails

Every adversarial run produces training data. Feed it straight back into your
defenses:

```bash
hb test --endpoint ./bot-config.json --wait   # find the failures
hb guardrails -o rules.yaml                   # convert findings into firewall rules
hb firewall train                             # train a Tier 2 classifier from test logs
```

Deploy the output with
[humanbound-firewall](https://github.com/humanbound/humanbound-firewall) and
your agent is protected against exactly the attacks it just failed. No other
open-source tool closes this loop.

## Python SDK

```python
import json
import time

from humanbound import LocalRunner, TestConfig

config = TestConfig(
    endpoint=json.load(open("bot-config.json")),  # same config file the CLI uses
    scope_path="scope.yaml",
)

runner = LocalRunner()
experiment_id = runner.start(config)

while runner.get_status(experiment_id).status not in ("Finished", "Failed", "Terminated"):
    time.sleep(5)

posture = runner.get_posture(experiment_id)
print(f"Security posture: {posture.overall_score} ({posture.grade})")

for insight in runner.get_result(experiment_id).insights:
    print(insight["severity"], "—", insight["category"])
```

The CLI and SDK share the same implementation, so they cannot drift. Authoring
custom orchestrators and wiring `EngineCallbacks` is covered in the
[docs](https://docs.humanbound.ai/).

## Stability contract

| Import path | Stability |
|---|---|
| `from humanbound import X` | **Stable** — semver-protected |
| `from humanbound.<module> import Y` | **Stable** — semver-protected |
| `from humanbound_cli.* import Z` | **Internal** — may change any release, do not import from user code |

The full orchestrator authoring guide, Platform integration, and API reference
live on [docs.humanbound.ai](https://docs.humanbound.ai/).

## Release highlights

- **Clean name**: `humanbound` is the PyPI install. The old `humanbound-cli`
  package has been yanked from PyPI; install `humanbound` directly.
- **Public SDK namespace** alongside the CLI — use the CLI or drive the
  engine from Python.
- **Firewall integration**: `pip install humanbound[firewall]` pulls
  [`humanbound-firewall`](https://github.com/humanbound/humanbound-firewall)
  alongside the CLI.

See the [changelog](https://github.com/humanbound/humanbound/blob/main/CHANGELOG.md)
for full release notes.

## Contributing

Contributions welcome. See [CONTRIBUTING.md](https://github.com/humanbound/humanbound/blob/main/CONTRIBUTING.md) for the dev
loop, release process, and DCO sign-off requirement (see [DCO.md](https://github.com/humanbound/humanbound/blob/main/DCO.md)).

- 🐛 [Report a bug](https://github.com/humanbound/humanbound/issues/new/choose)
- 💡 [Request a feature](https://github.com/humanbound/humanbound/issues/new/choose)
- 🔒 [Report a security issue](https://github.com/humanbound/humanbound/blob/main/SECURITY.md) — **not via public Issues**
- 💬 [Join Discord](https://discord.gg/WgTMpmSFtN)

## Telemetry

The `hb` CLI sends anonymous usage data to help us improve it.
Disable with `hb telemetry disable`, `HB_TELEMETRY_DISABLED=1`, or
`DO_NOT_TRACK=1`. Full disclosure: [PRIVACY.md](https://github.com/humanbound/humanbound/blob/main/PRIVACY.md).

## License

[Apache-2.0](https://github.com/humanbound/humanbound/blob/main/LICENSE). Free to use in any context — commercial or
open-source — with attribution. See [TRADEMARK.md](https://github.com/humanbound/humanbound/blob/main/TRADEMARK.md) for the
trademark policy. The code is open; the name is not.

The sibling project [`humanbound-firewall`](https://github.com/humanbound/humanbound-firewall)
is also Apache-2.0 — same license, different product.
