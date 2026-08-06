---
description: "Discover the agents deployed on a hosted platform (e.g. OpenAI Assistants) from a vendor credential and onboard one as a Humanbound project — no hand-written config."
keywords:
  - vendor discovery
  - hb connect --vendor
  - OpenAI Assistants onboarding
  - hosted platform agents
  - agent discovery
---

# Agent Discovery

Onboard an agent deployed on a hosted platform (currently OpenAI Assistants) without writing a
connector config by hand: `hb connect --vendor` lists the agents your credential can see
and turns the one you pick into a Humanbound project. Requires being logged in (`hb login`).

## How it works

1. Pick a vendor: `hb connect --vendor openai`.
2. Supply the credential — read from the vendor's env var (e.g. `OPENAI_API_KEY`) or a
   hidden interactive prompt. Credentials are **never** passed on the command line.
3. The backend queries the vendor API and returns your deployed agents (e.g. OpenAI
   Assistants); the CLI lists them.
4. Pick one — it becomes the project's `default_integration`, and the usual `hb connect`
   flow continues (scope probe or `--scope`, project creation, first test).

```bash
# Discover and onboard (reads $OPENAI_API_KEY or prompts)
hb connect --vendor openai

# Bring your own scope and project name
hb connect --vendor openai --scope ./scope.yaml --name "Prod Assistant"
```

The discovery response is not persisted — only the picked agent's connector config is
stored, and subsequent `hb test` runs use it automatically.

See [Agent Configuration](../getting-started/agent-config.md#hosted-platform-connector)
for the connector config this produces, and the
[commands reference](../reference/commands.md) for all `hb connect` flags.

## Supported vendors

| Vendor | id | Credential |
|---|---|---|
| OpenAI (Assistants) | `openai` | API key (`OPENAI_API_KEY`) |

!!! note "Assistants API deprecation"
    The Assistants API is deprecated and will be removed in August 2026. The recommended
    replacement is the Responses API. A Responses-based connector (`openai_responses`) is
    planned and will run alongside `openai_assistants`.

More vendors are added over time; `hb connect --vendor` with no valid id lists the
currently supported ones.
