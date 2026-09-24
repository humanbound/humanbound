# Guardrails Export

`hb guardrails` carries what your tests found into your runtime defenses. It exports two kinds of output:

- **The policy file (`agent.yaml`)** — business scope, permitted and restricted intents, and capabilities — which the `humanbound-firewall` Tier 3 judge evaluates against. `--format yaml` writes it: logged in, from the project's policy; locally, from the scope your test ran against.
- **Rule lists** for the enforcement points that consume them — gateways, moderation APIs, your own filters: the attack patterns a local run found, as JSON, or an OpenAI [Guardrails](../reference/glossary.md#defense) configuration (`--vendor openai`) when logged in.

Guardrails are the bridge between testing and protection — they carry the knowledge gained from adversarial testing into your enforcement points.

## How It Works

```
hb test                         →  findings, and the scope the agent was tested against
    ↓
hb guardrails --format yaml     →  agent.yaml                →  humanbound-firewall (Tier 3 judge)
hb guardrails (local run)       →  rule list (JSON)          →  gateways, moderation APIs, your filters
hb guardrails --vendor openai   →  OpenAI Guardrails config  →  OpenAI Guardrails (logged in)
```

The policy file describes what the agent may and must not do; the firewall judges each request and each piece of ingested content against it. Logged in, the default JSON output is the same policy as `agent.yaml`, in JSON. A rule list describes the attacks that succeeded. Each rule in a local run's list includes:

- **Threat class** — which OWASP category it addresses
- **Pattern** — description of the attack technique
- **[Severity](../reference/glossary.md#scoring-posture)** — how critical the vulnerability was
- **Action** — block (default)

## Export Guardrails

### From Local Test Results

```bash
# After running a test
hb test --endpoint ./config.json --scope ./scope.json --wait

# Export guardrail rules (reads from latest local results)
hb guardrails -o rules.json

# Export the firewall policy file (agent.yaml) from the same run's scope
hb guardrails --format yaml -o agent.yaml
```

### From Platform Data (Logged In)

```bash
# The active project's policy as the firewall's agent.yaml
hb guardrails --format yaml -o agent.yaml

# The same policy as JSON
hb guardrails -o policy.json
```

Logged in, `hb guardrails` exports the active project's policy — business scope, permitted and restricted intents, and declared capabilities — in the `agent.yaml` layout. It comes from the latest policy recommendation you accepted on the platform, or from the project's scope when you have accepted none. The platform derives recommendations from your test cycles and monitoring, so the policy sharpens as more data comes in.

## Output Formats

```bash
# JSON (default)
hb guardrails -o guardrails.json

# YAML — the humanbound-firewall policy file (agent.yaml)
hb guardrails --format yaml -o agent.yaml

# OpenAI moderation format
hb guardrails --vendor openai -o openai_rules.json
```

## Using with humanbound-firewall

The firewall's Tier 3 LLM judge reads `agent.yaml` — scope, permitted and restricted intents, few-shot examples — which defines what the agent is allowed and restricted from doing. Export it with `--format yaml`:

```bash
# Logged in: the active project's policy, as the platform exports it
hb guardrails --format yaml -o agent.yaml

# Not logged in: from the scope your latest local test ran against
hb guardrails --format yaml -o agent.yaml

# Not logged in: from a scope file
hb guardrails --format yaml --scope ./scope.json -o agent.yaml
```

Not logged in, when the latest run has no saved scope (runs saved by an earlier release), run `hb test` again or pass `--scope`.

```python
from humanbound_firewall import Firewall

fw = Firewall.from_config("agent.yaml")
```

The file carries `scope` (business scope and additional info), `intents` (permitted and restricted) and `capabilities` — the `tools`, `memory`, `inter_agent` and `reasoning_model` flags that are on for your project or in your scope file. When none are declared, `capabilities` is left out and the firewall applies its default. `settings:` and `tools:` are deployment choices; add them yourself. The JSON and OpenAI rule lists are not read by the firewall.

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
