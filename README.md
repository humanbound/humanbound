<p align="center">
  <img src="https://raw.githubusercontent.com/humanbound/humanbound/main/assets/logo-dark.svg" alt="Humanbound" width="280"/>
</p>

<h3 align="center">Find vulnerabilities in your AI agents before attackers do.</h3>

<p align="center">
  Humanbound attacks your agent the way real attackers will, scores every conversation,
  <br/>
  and turns each failure into a firewall rule. Open source, runs locally, no login needed.
</p>

<p align="center">
  <a href="https://docs.humanbound.ai/"><img src="https://img.shields.io/badge/Docs-docs.humanbound.ai-FD9506?style=for-the-badge" alt="Docs"/></a>
  <a href="https://app.humanbound.ai/?utm_source=github&utm_medium=readme&utm_content=badge_platform"><img src="https://img.shields.io/badge/Platform-start%20free-FD9506?style=for-the-badge" alt="Humanbound Platform: start free"/></a>
  <a href="https://discord.gg/QFTD6tr9zu"><img src="https://img.shields.io/badge/Discord-join-FD9506?style=for-the-badge" alt="Discord"/></a>
  <a href="https://www.humanbound.ai/contact?utm_source=github&utm_medium=readme&utm_content=badge_enterprise"><img src="https://img.shields.io/badge/Enterprise-contact%20us-555555?style=for-the-badge" alt="Enterprise: contact us"/></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/humanbound/"><img src="https://img.shields.io/pypi/v/humanbound?style=flat-square&color=FD9506" alt="PyPI version"/></a>
  <a href="https://github.com/humanbound/humanbound/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/humanbound/humanbound/ci.yml?style=flat-square&color=FD9506" alt="CI"/></a>
  <a href="https://github.com/humanbound/humanbound/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-FD9506?style=flat-square" alt="License"/></a>
  <a href="https://github.com/humanbound/humanbound/stargazers"><img src="https://img.shields.io/github/stars/humanbound/humanbound?style=flat-square&color=FD9506" alt="GitHub stars"/></a>
</p>

---

## Overview

AI agents hold conversations, call tools and keep state, so many security failures appear
only as a conversation unfolds, never in a single prompt.

Humanbound tests **the agent, not just the prompt**: it holds multi-turn conversations with
your real endpoint, tries to make the agent misuse its tools or step outside its role, and an
AI judge scores every reply against your security policy.

**Key capabilities:**

- **Realistic attacks** — multi-turn conversations that try prompt injection, jailbreaks,
  tool abuse and data leaks, the way a real attacker would
- **Standards-mapped** — every finding maps to the OWASP LLM and Agentic AI Top 10
- **Behavior checks** — does the agent stay on task and answer correctly
- **A security score** — 0–100 with an A–F grade, plus every conversation that failed
- **Findings into defenses** — failures become rules for
  [humanbound-firewall](https://github.com/humanbound/humanbound-firewall)
- **Fits your workflow** — CLI, Python SDK, GitHub Action and an MCP server for coding agents

<p align="center">
  <img src="https://raw.githubusercontent.com/humanbound/humanbound/main/assets/demo-terminal.png" alt="Output of hb posture, a score of 18.0 out of 100 and grade F, and hb logs --verdict fail, a table of failed conversations with their severity, category such as system_exposure and restriction_bypass, and the judge's explanation." width="100%"/>
  <br/>
  <sub>Security score and failed conversations after attacking the <code>hello-world</code> practice agent, with
  each conversation's severity (0–100) and the judge's reason.</sub>
</p>

## Use cases

- **Before launch** — red-team a new agent before real users reach it
- **On every pull request** — fail the build when a prompt, tool or model change opens a hole
- **In production** — monitor the agent continuously and catch regressions (Platform)
- **At runtime** — block the attacks it failed with firewall rules generated from the findings

## How it works

<p align="center">
  <img src="https://raw.githubusercontent.com/humanbound/humanbound/main/assets/how-it-works.svg" alt="How Humanbound works: the scope defines what the agent may do; attacks are generated from it and run as multi-turn conversations against the real agent; an AI judge scores each reply; failures become findings, which produce a security posture score and firewall rules; then the agent is tested again." width="100%"/>
</p>

---

## Quick start

**Prerequisites:** Python 3.10+, and an LLM API key (OpenAI, Anthropic, Gemini) or a local
[Ollama](https://ollama.com). The practice agents below also need Docker and an OpenAI key, or
an OpenAI-compatible server such as Ollama.

```bash
pip install 'humanbound[engine]'
export HB_PROVIDER=openai HB_API_KEY=sk-...   # the model that attacks and judges
```

### Attack a practice agent

No agent of your own yet? `hello-world` is a deliberately vulnerable shop chatbot that runs
in Docker. Start it, attack it and see how it broke:

```bash
hb arena config set OPENAI_API_KEY=sk-...             # the practice agent's model
hb arena run hello-world
hb test --target arena://hello-world --quick --wait   # about 20 minutes
hb posture                                            # security score, 0–100 and A–F
hb logs --verdict fail                                # the conversations where it broke
hb arena stop hello-world
```

Building with tools? Try `pricewatch` (tool use, indirect injection). `hb arena ls` lists every
practice agent ([Arena docs](https://docs.humanbound.ai/testing/arena/)).

> [!WARNING]
> Practice agents are built to be exploited. Never run them where there is sensitive data.

### Attack your own agent

Humanbound calls your agent's API over REST, WebSocket or SSE. Tell it how in
`bot-config.json`; `$PROMPT` is replaced with each attack message:

```json
{
  "chat_completion": {
    "endpoint": "https://your-bot.com/chat",
    "headers": {"Authorization": "Bearer <token>"},
    "payload": {"message": "$PROMPT"}
  }
}
```

The agent should reply with JSON that has the answer in a field such as `content`, `text`,
`reply` or `message`; nested fields are fine.

```bash
hb test --endpoint ./bot-config.json --wait   # about 20 minutes with a cloud model
hb report -o report.html                      # shareable HTML report
```

No API key, or your model refuses to write attacks? Test your agent on the Platform with
[hosted attack models](#hosted-attack-models).

**Next steps**

| Want to… | Do this |
|---|---|
| Test an agent that needs a session or login | See [Agent Configuration](https://docs.humanbound.ai/getting-started/agent-config/) |
| Get sharper attacks | Add `--prompt ./system.txt` or `--repo .`, or write a [`scope.yaml`](https://docs.humanbound.ai/local-engine/scope-discovery/) |
| Keep everything on your machine | `export HB_PROVIDER=ollama HB_TELEMETRY_DISABLED=1` ([details](https://docs.humanbound.ai/local-engine/provider-config/)) |
| Run in a container | Use the [Docker image](https://docs.humanbound.ai/integrations/docker/) |

---

## Humanbound Platform

Log in and the same CLI sends its runs to the
[Humanbound Platform](https://app.humanbound.ai/?utm_source=github&utm_medium=readme&utm_content=platform_heading).
Your findings and score are kept across runs, and the Platform can keep testing your agent on a
schedule (`hb monitor`). The free plan needs no card.

```bash
hb login
hb connect --endpoint ./bot-config.json    # creates a project and runs a first test
hb posture --trends                        # score over time
hb findings                                # open, fixed and regressed findings
```

**Everything in open source, plus:**

- Findings tracked across runs, and score history
- Continuous monitoring
- Cross-session leaks: does one user's data reach another
- [Hosted attack models](#hosted-attack-models), no API key needed
- Team collaboration

### Hosted attack models

Many models refuse to write attacks because of their safety rules, which makes them poor
attackers. Hosted attack models don't have that problem: if an attack doesn't work with one
model, it's retried with another, and a separate model grades the results, so the model that
wrote an attack never judges it.

Sign up, run `hb login` and `hb connect`, and `hb test` runs on the Platform with hosted attack
models, unless you add your own provider with `hb providers add`. Practice agents and
`hb test --local` always use your own model.

[**Start free on app.humanbound.ai →**](https://app.humanbound.ai/?utm_source=github&utm_medium=readme&utm_content=platform_cta)

### Enterprise

On-premises installation, SAML/OIDC single sign-on, SIEM integration,
bring-your-own-key models and a named engineer with an SLA.
[Contact sales →](https://www.humanbound.ai/contact?utm_source=github&utm_medium=readme&utm_content=enterprise_cta)

---

## Turn findings into guardrails

**Test → find → defend → test again.**

1. Export the findings as a firewall policy:

   ```bash
   hb guardrails -f yaml -o agent.yaml
   ```

2. Load `agent.yaml` into [humanbound-firewall](https://github.com/humanbound/humanbound-firewall)
   (`pip install humanbound-firewall`). It blocks the attacks your agent just failed.
3. Run `hb test` again to confirm.

Optional: train a dedicated classifier from your test logs with `'humanbound[firewall]'`
([Firewall docs](https://docs.humanbound.ai/defense/firewall/)).

## Run it in CI

[`humanbound/actions`](https://github.com/humanbound/actions) tests your agent on every pull
request and fails the build on findings at or above a severity:

```yaml
# .github/workflows/agent-security.yml
name: Agent security
on: [pull_request]

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose up -d agent # start your agent, reachable on localhost

      - uses: humanbound/actions@v1
        with:
          endpoint: ./bot-config.json   # same format as in the Quick start, pointing at localhost
          provider-api-key: ${{ secrets.OPENAI_API_KEY }}
          model: gpt-4.1
          fail-on: high
```

With a Humanbound account, pass `api-key`, `org-id` and `project-id` instead of
`provider-api-key` and `model`, and the run uses [hosted attack models](#hosted-attack-models)
(or your own provider, if you added one).

Findings can also appear in GitHub's Security tab
([SARIF](https://github.com/humanbound/actions#security-tab-sarif)). GitLab and other systems:
[CI/CD docs](https://docs.humanbound.ai/integrations/cicd/).

## Use it from your coding agent

**Ask about your results (MCP server).** Claude Code, Cursor, Windsurf or Copilot can answer
questions about your score, findings and runs on the Platform. It needs a Humanbound account:

```bash
pip install 'humanbound[mcp]'
hb login
claude mcp add humanbound -- hb mcp
```

Setup for other editors is in the [MCP docs](https://docs.humanbound.ai/integrations/mcp/).

**Let the agent run the test (plugin, preview).** The
[`humanbound-test` plugin](https://github.com/humanbound/plugins) lets Claude Code or Cursor
find your local FastAPI agent and test it for you. It needs a Humanbound account.

## Use it from Python

The CLI and the SDK share one implementation:

```python
import json
import time

from humanbound import LocalRunner, TestConfig

config = TestConfig(
    endpoint=json.load(open("bot-config.json")),
    test_category="humanbound/adversarial/owasp_agentic",
    testing_level="unit",
    lang="english",
)

runner = LocalRunner()
experiment_id = runner.start(config)
while runner.get_status(experiment_id).status not in ("Finished", "Failed", "Terminated"):
    time.sleep(5)

posture = runner.get_posture(experiment_id)
print(f"Security posture: {posture.overall_score} ({posture.grade})")
```

More in the [docs](https://docs.humanbound.ai/), including
[how the engine works](https://docs.humanbound.ai/local-engine/#architecture).

---

## Documentation

Everything else is at **[docs.humanbound.ai](https://docs.humanbound.ai/)**: configuration,
attack methodology, CI/CD, the Platform and the full command reference.

## Contributing

Code, docs and bug reports are welcome. See [CONTRIBUTING.md](https://github.com/humanbound/humanbound/blob/main/CONTRIBUTING.md) for the dev
setup and the DCO sign-off.

- 🐛 [Report a bug](https://github.com/humanbound/humanbound/issues/new/choose)
- 💡 [Request a feature](https://github.com/humanbound/humanbound/issues/new/choose)
- 🔒 [Report a security issue](https://github.com/humanbound/humanbound/blob/main/SECURITY.md) — **not via public issues**
- 💬 [Join Discord](https://discord.gg/QFTD6tr9zu)
- 📋 [Release notes](https://github.com/humanbound/humanbound/blob/main/CHANGELOG.md)

If Humanbound finds something in your agent, a ⭐ helps other builders find it too.

## Telemetry

The `hb` CLI sends anonymous usage data to help improve the project. To turn it off:

```bash
hb telemetry disable           # or: export HB_TELEMETRY_DISABLED=1, or: export DO_NOT_TRACK=1
```

Turning it off sends one final anonymous `telemetry_disabled` event per machine, so we can
count opt-outs. Details in [PRIVACY.md](https://github.com/humanbound/humanbound/blob/main/PRIVACY.md).

## Authorized use only

> [!WARNING]
> Humanbound is a security testing tool. Only test AI agents that you own or have explicit
> permission to test. Do not use it against third-party systems without permission.

## License

Humanbound is licensed under the
[Apache License 2.0](https://github.com/humanbound/humanbound/blob/main/LICENSE). See
[TRADEMARK.md](https://github.com/humanbound/humanbound/blob/main/TRADEMARK.md) for the
trademark policy.
