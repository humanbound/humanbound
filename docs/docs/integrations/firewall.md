# Firewall

The Humanbound Firewall is an open-source, context-aware security layer that sits between your users and your AI agent. It uses an LLM-as-a-Judge approach to evaluate incoming messages in real time -- blocking prompt injections, off-topic requests, and policy violations before they reach your agent.

## Installation

```bash
pip install aiandme
```

!!! info "Note"
    The Python package is currently published as `aiandme` (not yet renamed to `humanbound`). The package name will be updated in a future release.

## Python Integration

```python
from aiandme import Firewall
from aiandme import AIANDME_Firewall_CannotDecide, AIANDME_Firewall_NotAuthorised

firewall = Firewall(
    api_key="your-azure-openai-key",
    azure_endpoint="https://your-resource.openai.azure.com",
    scope="You are a customer support bot for Acme Corp...",
    permitted_intents=["order_status", "returns", "product_info"],
    restricted_intents=["competitor_comparison", "internal_pricing"]
)

try:
    result = firewall.filter(user_input)
    # result.verdict: "Pass" | "Off-Topic" | "Violation" | "Restriction"
    # result.reasoning: explanation of the verdict
    if result.verdict == "Pass":
        response = your_bot.chat(user_input)
    else:
        response = result.reasoning
except AIANDME_Firewall_NotAuthorised:
    response = "Your request was blocked by the security firewall."
except AIANDME_Firewall_CannotDecide:
    response = "Unable to process your request. Please try again."
```

## Firewall Verdicts

| Verdict | Description |
|---|---|
| **Pass** | Input is safe and within scope. Forward to your agent. |
| **Off-Topic** | Input is outside the agent's defined scope. Reject with explanation. |
| **Violation** | Input contains prompt injection, jailbreak attempt, or security threat. |
| **Restriction** | Input touches a restricted intent (e.g., competitor comparison). |

## Adaptive Context Defense (ACD)

The firewall auto-learns from your Humanbound test results. When FSLF identifies adversarial FAIL examples, those patterns are incorporated into the firewall's defense model -- creating a feedback loop between testing and runtime protection.

## Guardrails -> Firewall Pipeline

Export learned guardrails and feed them into your firewall configuration:

```bash
# Export guardrails from test findings
hb guardrails -o guardrails.json

# Use in your firewall configuration
hb guardrails --vendor openai -o openai-rules.json
```

!!! info "Open Source"
    The Humanbound Firewall is Apache-2.0 licensed. Contributions welcome at [github.com/Humanbound/firewall](https://github.com/Humanbound/firewall).
