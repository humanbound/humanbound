# Output & Export

After a test, results are saved locally and can be viewed or exported in multiple formats.

## Results Location

Results are saved to `.humanbound/results/exp-{timestamp}/` in your working directory:

```
.humanbound/results/exp-20260419-135646/
    meta.json       # experiment metadata + posture + insights
    logs.jsonl      # conversation logs (one per line)
```

## Viewing Results

### Posture Score

```bash
hb posture
```

Shows the overall security posture score (0-100, grade A-F), defense rate, and breached categories.

### Conversation Logs

```bash
# Table view (terminal)
hb logs

# Filter by verdict
hb logs --verdict fail

# Pagination
hb logs --page 2 --size 20
```

### Export Logs

```bash
# JSON
hb logs --format json -o logs.json

# Interactive HTML
hb logs -f html -o logs.html
```

## Reports

```bash
# HTML report (branded, self-contained)
hb report -o report.html

# JSON export
hb report --json -o results.json
```

The HTML report includes:

- Cover page with test metadata
- Posture score with donut chart
- Stats cards (total/pass/fail/defense rate)
- Severity distribution bar
- Findings table with severity badges
- Category coverage (breached vs defended)
- Failed conversation appendix (up to 20)
- Methodology description
- Technology disclaimer

## Guardrails Export

Export firewall rules from test findings:

```bash
# JSON format
hb guardrails -o rules.json

# YAML format
hb guardrails --format yaml -o rules.yaml

# OpenAI moderation format
hb guardrails --vendor openai -o openai_rules.json
```

Use with [hb-firewall](https://github.com/humanbound/hb-firewall):

```python
from hb_firewall import Firewall
fw = Firewall.from_config("agent.yaml", rules_path="rules.yaml")
```

## Firewall Training

Train a Tier 2 classifier from test results:

```bash
# From local test data
hb firewall train

# From external results (vendor-agnostic)
hb firewall train --import pyrit_results.json
hb firewall train --import results.json:promptfoo
```

## Log Schema

Each log entry contains 10 public fields:

| Field | Type | Description |
|---|---|---|
| `thread_id` | string | Session identifier |
| `conversation` | array | Turns: `[{"u": "...", "a": "..."}]` |
| `result` | string | `pass`, `fail`, or `error` |
| `gen_category` | string | OWASP category tested |
| `fail_category` | string | Evaluation that triggered |
| `explanation` | string | Judge's verdict explanation |
| `severity` | float | 0-100 |
| `confidence` | float | 0-100 |
| `exec_t` | float | Avg execution time per turn (seconds) |
| `meta` | dict | Telemetry data (tools called, resource usage) |

## Experiment Metadata

`meta.json` contains the experiment summary:

```json
{
  "id": "exp-20260419-135646",
  "name": "cli-owasp_agentic-20260419",
  "status": "Finished",
  "test_category": "humanbound/adversarial/owasp_agentic",
  "testing_level": "unit",
  "lang": "english",
  "results": {
    "stats": {"pass": 79, "fail": 18, "total": 97},
    "insights": [...],
    "posture": {"posture": 63.82, "grade": "C", ...},
    "exec_t": {"avg_t": 1.7, ...}
  },
  "created_at": "2026-04-19T13:56:46",
  "completed_at": "2026-04-19T14:15:22"
}
```
