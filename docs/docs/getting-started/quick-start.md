---
description: "From install to your first adversarial test in minutes — local or platform mode, with a posture score at the end."
---

# Quick Start

Get from installation to your first security test in minutes.

## Local Testing (No Account Required)

### Step 1: Configure Your LLM Provider

```bash
# Option A: Environment variables
export HB_PROVIDER=openai
export HB_API_KEY=sk-...

# Option B: Config file
hb config set provider openai
hb config set api-key sk-...

# Option C: Ollama (full isolation, no external API calls)
export HB_PROVIDER=ollama
export HB_MODEL=llama3.1:8b
```

### Step 2: Prepare Your Agent Config

Create a `bot-config.json` describing how to talk to your agent:

```json
{
  "streaming": false,
  "thread_auth": {"endpoint": "", "headers": {}, "payload": {}},
  "thread_init": {
    "endpoint": "https://your-bot.com/sessions",
    "headers": {"Authorization": "Bearer token"},
    "payload": {}
  },
  "chat_completion": {
    "endpoint": "https://your-bot.com/chat",
    "headers": {"Authorization": "Bearer token"},
    "payload": {"message": "$PROMPT"}
  }
}
```

See [Agent Configuration](agent-config.md) for the full specification.

### Step 3: Run Your First Test

```bash
# Recommended: scan your code for scope + tools
hb test --endpoint ./bot-config.json --repo . --wait

# Or provide a scope file for precise control
hb test --endpoint ./bot-config.json --scope ./scope.yaml --wait

# Or provide your system prompt
hb test --endpoint ./bot-config.json --prompt ./system_prompt.txt --wait

# Or just point at the bot (auto-probe for scope)
hb test --endpoint ./bot-config.json --wait
```

See [Scope Discovery](../local-engine/scope-discovery.md) for details on each method.

### Step 4: View Results

```bash
hb posture                         # Security posture score (0-100, A-F)
hb logs                            # Conversation logs table
hb logs --verdict fail             # Only failed conversations
hb report -o report.html           # Full HTML report
hb logs -f html -o logs.html       # Interactive HTML log viewer
```

### Step 5: Export Defenses

```bash
hb guardrails -o rules.yaml        # Export firewall rules
hb firewall train                   # Train a Tier 2 classifier
```

Use with [humanbound-firewall](https://github.com/humanbound/humanbound-firewall) for runtime protection.

### Test Modes

```bash
# Default: threaded execution, progress spinner
hb test --endpoint ./config.json --wait

# Verbose: live progress bar + final results table
hb test --endpoint ./config.json --wait --verbose

# Debug: single-threaded, full turn-by-turn output
hb test --endpoint ./config.json --wait --debug
```

### Test Options

| Option | Description |
|---|---|
| `-e, --endpoint` | Agent integration config (JSON file or string) |
| `--repo` | Repository path for scope + tools discovery |
| `--prompt` | System prompt file for scope extraction |
| `--scope` | Explicit scope file (YAML/JSON) |
| `-t, --test-category` | Test type: `owasp_agentic` (default), `owasp_single_turn`, `behavioral` |
| `-l, --testing-level` | Depth: `unit` (~20 min), `system` (~45 min), `acceptance` (~90 min) |
| `--deep` | Shortcut for `-l system` |
| `--full` | Shortcut for `-l acceptance` |
| `--qa` | Shortcut for `-t behavioral` |
| `--lang` | Test language (default: english) |
| `--context` | Extra context for the judge (string or .txt file) |
| `--wait` | Wait for completion (automatic in local mode) |
| `--fail-on` | Exit non-zero on findings: `critical`, `high`, `medium`, `low`, `any` |
| `--debug` | Single-threaded, full turn-by-turn output |
| `--verbose` | Live progress bar + final results table |
| `--local` | Force local engine (even when logged in) |

### CI/CD

```bash
pip install humanbound
hb test --endpoint ./bot-config.json --repo . --wait --fail-on high
```

```yaml
# .github/workflows/security.yml
- run: pip install humanbound
- run: hb test --endpoint ./bot-config.json --repo . --wait --fail-on high
  env:
    HB_PROVIDER: openai
    HB_API_KEY: ${{ secrets.OPENAI_KEY }}
```

See [CI/CD Integration](../integrations/cicd.md) for more.

---

## Platform Testing (With Account)

For posture tracking, finding lifecycle, continuous monitoring, and team collaboration.

### Step 1: Authenticate

```bash
hb login
```

### Step 2: Connect Your Agent

```bash
hb connect --endpoint ./bot-config.json
```

This probes your agent, extracts scope, creates a project, and runs a first test.

| Option | Description |
|---|---|
| `-e, --endpoint` | Agent integration config |
| `-p, --prompt` | System prompt file |
| `-r, --repo` | Repository path |
| `-o, --openapi` | OpenAPI spec file |
| `-c, --context` | Extra context for the judge |
| `-n, --name` | Project name |
| `-y, --yes` | Skip confirmations |

### Step 3: Run Tests

```bash
# Uses project's saved integration (no --endpoint needed)
hb test --wait
```

### Step 4: View Enhanced Results

```bash
hb posture                # Score with delta from previous scan
hb posture --history      # Posture trends over time
hb findings               # Finding lifecycle (open/stale/fixed/regressed)
hb logs                   # Conversation logs
hb report -o report.html  # Full report
```

### Step 5: Continuous Monitoring

```bash
hb monitor enable --schedule daily    # Requires Pro
```
