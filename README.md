# Humanbound CLI

> AI agent security testing — adversarial attacks, posture scoring, guardrails export, and firewall training. Runs locally or on the platform. No login required.

[![PyPI](https://img.shields.io/pypi/v/humanbound-cli)](https://pypi.org/project/humanbound-cli/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](https://www.apache.org/licenses/LICENSE-2.0)

```bash
pip install humanbound-cli
```

---

## Quick Start

```bash
# Configure your LLM provider
export HB_PROVIDER=openai
export HB_API_KEY=sk-...

# Run a security test
hb test --endpoint ./bot-config.json --repo . --wait

# View results
hb posture                         # Security score (0-100, A-F)
hb logs                            # Conversation logs
hb report -o report.html           # HTML report
hb guardrails -o rules.yaml        # Firewall rules
```

Full isolation with [ollama](https://ollama.com) — zero external API calls:

```bash
export HB_PROVIDER=ollama
export HB_MODEL=llama3.1:8b
hb test --endpoint ./bot-config.json --scope ./scope.yaml --wait
```

---

## What It Does

Humanbound runs multi-turn adversarial attacks against your AI agent's live endpoint, evaluates responses using LLM-as-a-Judge, and produces structured findings aligned with [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/) and [OWASP Agentic AI Threats](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/).

| Feature | Local | Platform |
|---------|-------|----------|
| Multi-turn adversarial testing (OWASP) | Yes | Yes |
| Behavioral/QA testing | Yes | Yes |
| Posture score (0-100, A-F) | Yes | Yes + trends |
| HTML/JSON reports | Yes | Yes |
| Guardrails export | Yes | Yes (richer) |
| Firewall training | Yes | Yes (richer) |
| Finding lifecycle tracking | — | Yes |
| Continuous monitoring | — | Yes |
| Cross-session leakage detection | — | Yes |
| Managed LLM (no key needed) | — | Yes |

---

## Agent Configuration

Create a JSON file describing how to talk to your agent:

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

`$PROMPT` is where Humanbound injects test prompts.

---

## Test Modes

```bash
# Default: threaded, progress spinner (~20 min)
hb test --endpoint ./config.json --wait

# Verbose: live progress bar + final results table
hb test --endpoint ./config.json --wait --verbose

# Debug: single-threaded, full turn-by-turn output
hb test --endpoint ./config.json --wait --debug
```

## Test Categories

| Category | Flag | Description |
|----------|------|-------------|
| OWASP Agentic | `-t owasp_agentic` (default) | Multi-turn adversarial with score-guided escalation |
| OWASP Single-Turn | `-t owasp_single_turn` | Maximum-strength single prompts |
| Behavioral QA | `--qa` | Intent boundary + response quality testing |

## Testing Levels

| Level | Flag | Duration |
|-------|------|----------|
| Unit (default) | `-l unit` | ~20 min |
| System | `--deep` | ~45 min |
| Acceptance | `--full` | ~90 min |

## Scope Discovery

```bash
hb test --endpoint ./config.json --repo . --wait            # Scan code for scope + tools (recommended)
hb test --endpoint ./config.json --scope ./scope.yaml --wait # Explicit scope file
hb test --endpoint ./config.json --prompt ./system.txt --wait # Extract from system prompt
hb test --endpoint ./config.json --wait                      # Auto-probe the bot
```

---

## Defense

### Guardrails Export

```bash
hb guardrails -o rules.yaml
hb guardrails --vendor openai -o openai_rules.json
```

### Firewall Training

Train a Tier 2 classifier from test results:

```bash
hb firewall train                                  # From local test data
hb firewall train --import pyrit_results.json      # From PyRIT
hb firewall train --import results.json:promptfoo  # From promptfoo
```

Use with [hb-firewall](https://github.com/humanbound/hb-firewall) for runtime protection.

---

## CI/CD

```yaml
# .github/workflows/security.yml
- run: pip install humanbound-cli
- run: hb test --endpoint ./config.json --repo . --wait --fail-on high
  env:
    HB_PROVIDER: openai
    HB_API_KEY: ${{ secrets.OPENAI_KEY }}
```

---

## Platform (With Login)

For posture tracking, finding lifecycle, continuous monitoring, and team collaboration:

```bash
hb login
hb connect --endpoint ./bot-config.json    # Create project + first test
hb test --wait                              # Re-test (project remembered)
hb posture --history                        # Posture trends
hb findings                                 # Finding lifecycle
hb monitor enable --schedule daily          # Continuous monitoring
```

---

## Providers

| Provider | `HB_PROVIDER` | Notes |
|----------|---------------|-------|
| OpenAI | `openai` | GPT-4o, GPT-4.1 |
| Anthropic | `claude` | Claude 3.5, Claude 4 |
| Google | `gemini` | Gemini Pro |
| Azure OpenAI | `azureopenai` | Requires `HB_ENDPOINT` |
| Grok (xAI) | `grok` | |
| Ollama | `ollama` | Full local isolation |

```bash
hb config set provider openai
hb config set api-key sk-...
```

---

## pytest Integration

```python
import pytest

@pytest.mark.hb
def test_prompt_injection(hb):
    result = hb.test("llm001")
    assert result.passed

@pytest.mark.hb
def test_posture_threshold(hb_posture):
    assert hb_posture["score"] >= 70
```

```bash
pytest --hb tests/ --hb-fail-on=high
```

---

## MCP Server

Expose CLI capabilities as tools for AI assistants:

```bash
pip install humanbound-cli[mcp]

# Claude Code
claude mcp add humanbound -- hb mcp

# Cursor (.cursor/mcp.json)
{"mcpServers": {"humanbound": {"command": "hb", "args": ["mcp"]}}}
```

---

## Links

- [Documentation](https://docs.humanbound.ai)
- [Firewall (hb-firewall)](https://github.com/humanbound/hb-firewall)
- [PyPI](https://pypi.org/project/humanbound-cli/)
