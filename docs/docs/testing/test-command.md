---
description: "hb test reference — orchestrators, testing levels, languages, providers, and every flag that shapes an adversarial run."
keywords:
  - hb test reference
  - test command flags
  - testing levels
  - test category
  - --fail-on flag
  - experiment configuration
  - test command CLI
  - adversarial test execution
---

# Test Command Reference

Full reference for `hb test` — the command that runs an adversarial test against your agent. Covers the test-category flag (which orchestrator to use), testing levels (unit / system / acceptance shortcuts), language and provider selection, the experiment name and description, behaviour flags (`--wait`, `--fail-on`), and the optional `--endpoint` override for testing against a different agent than the project's default.

```
hb test [OPTIONS]

Test Configuration:
  -t, --test-category     Test to run (default: humanbound/adversarial/owasp_agentic)
  --category              Shorthand alias for --test-category
  -l, --testing-level     Depth: unit | system | acceptance
  --deep                  Shortcut for --testing-level system
  --full                  Shortcut for --testing-level acceptance
  -n, --name              Experiment name (auto-generated if omitted)
  -d, --description       Experiment description
  --lang                  Language (default: english). Accepts codes: en, de, es
  -c, --context           Extra context for the judge (string or .txt file path)
  --provider-id           Provider to use (default: first available)

Behavior:
  --no-auto-start         Create without starting (manual mode)
  -w, --wait              Wait for completion
  --fail-on SEVERITY      Exit non-zero if findings >= severity
                          Values: critical, high, medium, low, any

Endpoint Override (optional):
  -e, --endpoint          Agent integration config -- JSON string or file path.
                          Same shape as 'hb connect --endpoint'.
                          Overrides the project's default integration.
```

!!! info "Note"
    The `-e / --endpoint` flag is only needed if your project was not connected with `hb connect --endpoint`, or if you want to temporarily test against a different agent. When a default integration is configured, `hb test` works with no additional flags. Your `--endpoint` JSON file can also include a `telemetry` section for white-box agentic testing -- see [Agent Configuration File](../getting-started/agent-config.md#telemetry-optional).
