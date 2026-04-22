# Orchestrators

Orchestrators are the test engines that generate attacks, run conversations, and evaluate responses. Humanbound ships with three built-in orchestrators. You can also build your own.

## Built-In Orchestrators

Installed with `pip install humanbound`:

| Orchestrator | Flag | Description |
|---|---|---|
| **OWASP Agentic** (default) | `-t owasp_agentic` | Multi-turn adversarial testing. Score-guided attack escalation, cross-conversation intelligence, canary planting. |
| **OWASP Single-Turn** | `-t owasp_single_turn` | Single-prompt attacks at maximum strength. Fast, high-volume. |
| **Behavioral QA** | `-t behavioral` or `--qa` | Intent boundary validation, response quality, functional correctness. |

```bash
# Default: multi-turn adversarial
hb test --endpoint ./config.json --scope ./scope.json --wait

# Single-turn attacks
hb test --endpoint ./config.json --scope ./scope.json -t owasp_single_turn --wait

# Behavioral/QA testing
hb test --endpoint ./config.json --scope ./scope.json --qa --wait
```

## Test Levels

Each orchestrator supports three depth levels:

| Level | Flag | Duration | Conversations |
|---|---|---|---|
| **Unit** (default) | `-l unit` | ~20 min | ~50-100 |
| **System** | `-l system` or `--deep` | ~45 min | ~100-200 |
| **Acceptance** | `-l acceptance` or `--full` | ~90 min | ~200-400 |

## Building Custom Orchestrators

A custom orchestrator is a Python package that follows the orchestrator contract.

### Package Structure

```
my_orchestrator/
    manifest.yaml       # metadata
    config.py           # attack templates and evaluation metrics
    generator.py        # attack generation logic
    judge.py            # evaluation logic
    orchestrator.py     # generate + run + compute_quota
```

### Required Interface

Your `orchestrator.py` must expose three functions:

```python
def orchestrator_generate(model_provider: dict, experiment: dict) -> dict:
    """Generate attack/test prompts.
    
    Returns dict mapping category → list of opening prompts.
    """

def orchestrator_run(
    organisation_id, model_provider, experiment, prompts, few_shots_model,
    callbacks=None
) -> None:
    """Execute the test. Emit logs via callbacks.on_logs()."""

def compute_quota(testing_level: str, dataset_len: int) -> int:
    """Estimate total conversation count."""
```

### Available SDK

Your orchestrator imports from the engine SDK:

```python
from humanbound_cli.engine.bot import Bot, Telemetry      # HTTP/WebSocket bot client
from humanbound_cli.engine.llm import get_llm_pinger       # LLM provider factory
from humanbound_cli.engine.schemas import LogsAnonymous    # log format
from humanbound_cli.engine.callbacks import EngineCallbacks # I/O abstraction
```

### Callbacks

The `callbacks` parameter abstracts I/O. Your orchestrator should:

- Call `callbacks.on_logs(logs)` when a batch of conversation logs is ready
- Call `callbacks.on_complete(status)` when done
- Check `callbacks.is_terminated()` before starting each conversation
- Call `callbacks.on_error(title, details)` on non-fatal errors

### Custom Bot Response Formats

The `Bot` class handles standard response formats (`content`, `text`, `response`, `answer` fields). If your bot returns responses in a non-standard format, override `extract_custom_response()`:

```python
from humanbound_cli.engine.bot import Bot

class MyBot(Bot):
    def extract_custom_response(self, chunk):
        """Handle my bot's custom response format."""
        if isinstance(chunk, dict) and "data" in chunk:
            return chunk["data"].get("message", {}).get("text")
        return None  # fall back to default extraction
```

Pass your custom bot class to the orchestrator via the `Bot` constructor — it accepts the same endpoint config format.

### manifest.yaml

```yaml
name: my-custom-orchestrator
version: 1.0.0
description: Custom security test for my domain
author: Your Name
category: adversarial  # or behavioral
```

### Installing Custom Orchestrators

Place your orchestrator in `~/.humanbound/orchestrators/`:

```
~/.humanbound/orchestrators/my_orchestrator/
    manifest.yaml
    config.py
    generator.py
    judge.py
    orchestrator.py
```

Then run:

```bash
hb test --endpoint ./config.json -t my_orchestrator --wait
```

### Deploying to Platform (Future)

Custom orchestrators can be deployed to your platform workspace for continuous monitoring:

```bash
hb orchestrators deploy my_orchestrator
```

Once deployed, ASCAM can run your custom orchestrator on a schedule.
