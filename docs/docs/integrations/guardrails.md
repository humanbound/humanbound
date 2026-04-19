# Guardrails Export

Guardrails are security rules extracted from your test results. They capture the attack patterns and boundary violations discovered during testing and translate them into actionable rules for runtime defence.

Guardrails are the bridge between testing and protection — they carry the knowledge gained from adversarial testing into the firewall's evaluation logic.

## How It Works

```
hb test → findings (what attacks succeeded)
    ↓
hb guardrails → rules (what to block)
    ↓
hb-firewall → runtime protection (blocking attacks)
```

Each guardrail rule includes:

- **Threat class** — which OWASP category it addresses
- **Pattern** — description of the attack technique
- **Severity** — how critical the vulnerability was
- **Action** — block (default)

## Export Guardrails

### From Local Test Results

```bash
# After running a test
hb test --endpoint ./config.json --scope ./scope.json --wait

# Export guardrails (reads from latest local results)
hb guardrails -o rules.json
hb guardrails --format yaml -o rules.yaml
```

### From Platform Data (Logged In)

```bash
# Richer rules — accumulated from multiple test cycles
hb guardrails -o rules.json
```

Platform guardrails are enriched by data from continuous monitoring — more test cycles produce more diverse attack patterns and therefore more comprehensive rules.

## Output Formats

```bash
# JSON (default)
hb guardrails -o guardrails.json

# YAML
hb guardrails --format yaml -o guardrails.yaml

# OpenAI moderation format
hb guardrails --vendor openai -o openai_rules.json
```

## Using with hb-firewall

Guardrails configure the firewall's Tier 3 LLM judge — they define what the agent is allowed and restricted from doing:

```python
from hb_firewall import Firewall

fw = Firewall.from_config("agent.yaml")
```

The `agent.yaml` scope (permitted/restricted intents) acts as the guardrail configuration. Exported rules can supplement or override the base configuration.

See [Firewall](firewall.md) for full integration details.

## Training Firewall Classifiers

Beyond rule-based guardrails, test results can train ML classifiers for the firewall's Tier 2:

```bash
# Train from local test data
hb firewall train

# Train from external red teaming results
hb firewall train --import pyrit_results.json
hb firewall train --import results.json:promptfoo

# Train from platform data (richer, requires login)
hb firewall train --source platform
```

See [Firewall — Tier 2](firewall.md#tier-2-agent-specific-classification) for details on classifier training.
