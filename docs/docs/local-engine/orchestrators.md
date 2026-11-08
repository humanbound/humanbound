---
description: "Orchestrators generate attacks, run conversations, and evaluate responses — Humanbound ships three built-in engines and lets you author your own."
keywords:
  - test orchestrator
  - OWASP agentic testing
  - OWASP single-turn
  - behavioral QA testing
  - custom orchestrator
  - orchestrator SDK
  - test levels
  - custom bot integration
---

# Orchestrators

An orchestrator is the test engine that generates attack prompts, drives the conversation against your agent, and evaluates responses. Humanbound ships three built-in orchestrators — OWASP Agentic (multi-turn adversarial, the default), OWASP Single-Turn (high-volume single-prompt attacks), and Behavioral QA (intent boundary and response quality testing) — each supporting three test levels (unit, system, acceptance). The sections below cover built-in selection, test depth, and the SDK for authoring custom orchestrators.

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

`hb orchestrators list` shows every orchestrator `-t` accepts: the built-in ones, their
short names, and the custom ones you have installed.

## Test Levels

Each orchestrator supports three depth levels:

| Level | Flag | Duration | Conversations |
|---|---|---|---|
| **Unit** (default) | `-l unit` | ~20 min | ~50-100 |
| **System** | `-l system` or `--deep` | ~45 min | ~100-200 |
| **Acceptance** | `-l acceptance` or `--full` | ~90 min | ~200-400 |

## Building Custom Orchestrators

A custom orchestrator is a Python package that follows the orchestrator contract.

### Quick Start

Create a working orchestrator, check it, and run it:

```bash
hb orchestrators new pii_leak             # creates ~/.humanbound/orchestrators/pii_leak/
hb orchestrators validate pii_leak        # checks it without calling an LLM or your agent
hb test --endpoint ./config.json -t pii_leak --wait
```

The scaffold holds a single-turn conversation with your agent for each opening prompt
in `config.py` and asks an LLM judge to score each reply against the rubric there.
Start by editing `config.py`: the attack category, the opening prompts and what counts
as a failure. Then grow `generator.py` and `judge.py` as you need.

`hb orchestrators validate` imports the package the way `hb test` does and checks that
`orchestrator_generate` and `orchestrator_run` exist and accept the arguments `hb test`
passes, that `manifest.yaml` is valid, and that the name doesn't clash with a built-in
orchestrator. It exits with status 1 on a problem, so you can run it in CI; pass a path
(`hb orchestrators validate ./orchestrators/pii_leak`) to check one that isn't installed.
An argument is read as a path only when it contains a `/` or starts with `.` or `~`; a
bare name like `pii_leak` always means the installed orchestrator.

### Package Structure

```
my_orchestrator/
    manifest.yaml       # metadata
    config.py           # attack templates and evaluation metrics
    generator.py        # attack generation logic
    judge.py            # evaluation logic
    orchestrator.py     # generate + run + compute_quota
```

The directory is imported as a package, so `orchestrator.py` reaches its sibling
modules with relative imports (`from .generator import ...`, `from .judge import ...`).
An `__init__.py` is optional.

### Required Interface

Your `orchestrator.py` must expose `orchestrator_generate` and `orchestrator_run`. `compute_quota` is optional — `hb test` does not call it today:

```python
def orchestrator_generate(model_provider: dict, experiment: dict) -> dict:
    """Generate attack/test prompts.

    Returns dict mapping category → list of opening prompts.
    """


def orchestrator_run(
    organisation_id, model_provider, experiment, prompts, few_shots_model, callbacks=None
) -> None:
    """Execute the test. Emit logs via callbacks.on_logs()."""


def compute_quota(testing_level: str, dataset_len: int) -> int:
    """Estimate total conversation count."""
```

### Available SDK

Your orchestrator imports from the engine SDK:

```python
from humanbound_cli.engine.bot import Bot, Telemetry  # HTTP/WebSocket bot client
from humanbound_cli.engine.llm import get_llm_pinger  # LLM provider factory
from humanbound_cli.engine.schemas import LogsAnonymous  # log format
from humanbound_cli.engine.callbacks import EngineCallbacks  # I/O abstraction
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

`hb test` loads custom orchestrators from `~/.humanbound/orchestrators/`, where
`hb orchestrators new` creates them. To install one you wrote elsewhere (or created with
`hb orchestrators new <name> --dir <dir>`), copy or link it there:

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

The directory name is the `-t` value. A directory named like a built-in orchestrator
(for example `qa`) is never loaded; the built-in runs instead.

### Deploying to Platform (Planned)

Running a custom orchestrator on the Platform, for example on a continuous-monitoring
schedule, is planned. There is no command for it yet; today custom orchestrators run
only on the local engine.
