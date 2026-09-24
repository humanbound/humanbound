# Guardrails Export

[Guardrails](../reference/glossary.md#defense) are security rules extracted from your test results. They capture the attack patterns and boundary violations discovered during testing and translate them into actionable rules for runtime defense. Export with `hb guardrails` as JSON, YAML, or OpenAI moderation format for the enforcement points that consume rule lists — gateways, moderation APIs, your own filters. The `humanbound-firewall` Tier 3 judge is configured by the policy file (`agent.yaml`), not by this export.

Guardrails are the bridge between testing and protection — they carry the knowledge gained from adversarial testing into your enforcement points.

## How It Works

```
hb test → findings (what attacks succeeded)
    ↓
hb guardrails → rules (what to block)
    ↓
humanbound-firewall → runtime protection (blocking attacks)
```

Each guardrail rule includes:

- **Threat class** — which OWASP category it addresses
- **Pattern** — description of the attack technique
- **[Severity](../reference/glossary.md#scoring-posture)** — how critical the vulnerability was
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

## Using with humanbound-firewall

The firewall's Tier 3 LLM judge reads `agent.yaml` — scope, permitted and restricted intents, few-shot examples — which defines what the agent is allowed and restricted from doing:

```python
from humanbound_firewall import Firewall

fw = Firewall.from_config("agent.yaml")
```

The `agent.yaml` scope (permitted/restricted intents) is the guardrail configuration the firewall enforces. The exported rule list is not read by the firewall today.

Since `humanbound-firewall` 0.3 the firewall judges every path into the model by trust class — `request`, `ingest`, `recall` — and few-shot examples in `agent.yaml` carry the class they were learned on (`class: request | ingest`, default `request`; the recall judge takes none). The export does not carry few-shot examples yet; when it does, each example will carry the class it was found on, so that the ingest judge learns from findings made through fetched content.

See [Firewall](firewall.md) for full integration details.

## Training Firewall Classifiers

Beyond rule-based guardrails, test results can train ML classifiers for the firewall's Tier 2:

```bash
# Train from your test results
hb firewall train --model detectors/setfit_classifier.py

# Add external red teaming results
hb firewall train --model detectors/setfit_classifier.py --import pyrit_results.json
hb firewall train --model detectors/setfit_classifier.py --import results.json:promptfoo
```

`--model` is the path to the detector script to train. When you are logged in with a project selected (or use an API key), `hb firewall train` pulls that project's experiments from the platform; otherwise it reads local results from `.humanbound/results`.

See [Firewall — Tier 2](firewall.md#tier-2-agent-specific-classification) for details on classifier training.
