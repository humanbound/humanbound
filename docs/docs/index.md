# <span class="hero-title">Humanbound</span>

**Find vulnerabilities in your AI agents before attackers do.**

AI agent security testing platform. Automated adversarial and behavioral testing, LLM-as-a-Judge evaluation, runtime firewall, OWASP-aligned attack scenarios, posture scoring, and guardrails export -- from your terminal to your CI/CD pipeline.

```
pip install humanbound-cli

$ hb login
$ hb connect --endpoint ./bot-config.json
$ hb posture
```

[Get Started](getting-started/installation.md){ .md-button .md-button--primary }

---

## What is Humanbound?

Humanbound is an AI agent security testing platform. Point it at your agent's endpoint, define the scope (or let it auto-extract one), and get structured findings mapped to OWASP LLM & Agentic AI categories. Works with any chatbot or agent -- cloud or on-prem.

<div class="grid cards" markdown>

- :shield: **Adversarial Testing**

    ---

    OWASP-aligned attack scenarios: prompt injection, jailbreaks, tool abuse, data exfiltration. Single-turn, multi-turn, and agentic modes.

- :white_check_mark: **Behavioral Testing**

    ---

    Validate intent boundaries, response quality, and functional correctness against your agent's defined scope.

- :dna: **Evolutionary Red Teaming**

    ---

    Score-guided attack refinement during ASCAM red-teaming campaigns. Strategies adapt automatically with backtracking, encoding, and cross-conversation learning.

- :bar_chart: **Security Posture**

    ---

    Quantified 0--100 score with grade (A--F). Tracks findings, coverage, and resilience over time.

- :mag: **Findings & Tracking**

    ---

    Persistent vulnerability records with lifecycle (open -> stale -> fixed -> regressed). Deduplicated across experiments.

- :lock: **Guardrails Export**

    ---

    Generate protection rules from test findings. Export to OpenAI or Humanbound Firewall format.

- :arrows_counterclockwise: **Continuous Assurance**

    ---

    ASCAM 4-activity lifecycle: Scan -> Assess -> Investigate -> Monitor. Runs automatically.

- :gear: **CI/CD & pytest**

    ---

    Block insecure deployments with exit codes. Native pytest plugin with markers, fixtures, and baseline comparison.

</div>

### Platform Structure

Humanbound follows a simple hierarchy:

- **Organisation** -- The top-level management unit. Handles team collaboration, security settings, and billing.
- **Projects** -- Each AI agent (chatbot, GenAI assistant) is managed under a project. Projects define business rules, safety checks, and testing workflows.
- **Experiments** -- Individual test executions that generate attack prompts, converse with your agent, and produce security verdicts.

Example: A company with a customer support agent and an internal knowledge agent would create **two projects** under one organisation.

### Three Phases of AI Security

| Phase | Description |
|---|---|
| **1. Development: Testing & Security** | Before deployment, test your AI under real-world adversarial conditions. Automated stress tests, LLM-as-a-Judge evaluation, and iterative refinement based on security insights. |
| **2. Production: Real-Time Protection** | Once live, the [Humanbound Firewall](integrations/firewall.md) monitors and filters user prompts in real time. Blocks risky or out-of-scope queries before they reach your agent. |
| **3. Post-Deployment: Auditing & Monitoring** | Continuous security checks via [log auditing](testing/log-upload.md), [SIEM integration](integrations/siem.md), and [ASCAM campaigns](concepts/campaigns.md). Catch regressions and drift before users notice. |

### How it Works

1. **Connect** -- `hb connect` scans your agent, extracts scope, and auto-runs security tests
2. **Harden** -- Review findings, export guardrails, track posture
3. **Monitor** -- Continuous assurance via ASCAM keeps your posture up to date

### Continuous Assurance Engine

Humanbound doesn't just run one-off tests. Under the hood, the **ASCAM** (AI Security Continuous Assurance Model) engine cycles through four activities -- scan, assess, investigate, and monitor -- adapting automatically to changes in your agent's behavior.

Inspired by coverage-guided fuzzing (AFL-style), ASCAM uses a Decision Engine that evaluates 9 signals each cycle (critical findings, regressions, posture drops, stale coverage, drift, and more), coverage tracking to prioritize unexplored attack surfaces, statistical drift detection to spot behavioral regressions, and a findings lifecycle to deduplicate and track vulnerabilities across runs. The result is an always-on feedback loop that gets smarter with every test cycle.

### Agent Configuration in 30 Seconds

Create a JSON file that tells Humanbound how to talk to your agent. The `$PROMPT` placeholder is where Humanbound injects test prompts during testing -- just place it where your agent expects user input.

```json
{
  "streaming": false,
  "thread_auth": {
    "endpoint": "https://your-bot.com/oauth/token",
    "headers": {},
    "payload": {
      "client_id": "YOUR_CLIENT_ID",
      "client_secret": "YOUR_CLIENT_SECRET"
    }
  },
  "thread_init": {
    "endpoint": "https://your-bot.com/threads",
    "headers": {},
    "payload": {}
  },
  "chat_completion": {
    "endpoint": "https://your-bot.com/chat",
    "headers": {
      "Authorization": "Bearer YOUR_API_KEY",
      "Content-Type": "application/json"
    },
    "payload": {
      "messages": [{"role": "user", "content": "$PROMPT"}]
    }
  }
}
```

| Field | Required | Description |
|---|---|---|
| `chat_completion` | Yes | The endpoint your agent listens on for chat messages. Use `$PROMPT` in the payload where user input goes. |
| `thread_auth` | No | OAuth/token endpoint called before testing begins. The response payload (`access_token`, `refresh_token`, etc.) is captured and injected into subsequent requests. |
| `thread_init` | Yes | Session/thread creation endpoint. Called once per conversation to initialize a thread before sending chat messages. |
| `streaming` | No | Set `true` if your agent uses WebSocket/SSE streaming. |

!!! info "Minimal config"
    `chat_completion` and `thread_init` are required. Skip `thread_auth` if your agent uses simple API key auth and doesn't need OAuth.

Then point Humanbound at it:

```bash
hb connect -n "My Agent" -e ./bot-config.json  # Connect, scan, and auto-test
```
