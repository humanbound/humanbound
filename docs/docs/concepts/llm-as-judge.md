---
description: "How Humanbound's judge LLM scores your agent's responses against security criteria — independent model, structured rubric, and reasoning."
---

# LLM-as-a-Judge

At the core of every Humanbound security test is a **judge** -- an LLM that evaluates your AI agent's responses against security criteria. The judge is separate from the agent under test, using a different model and provider to ensure independent evaluation.

## How It Works

When you run `hb test`, Humanbound generates adversarial prompts and sends them to your agent. Each response is then evaluated by the judge LLM, which produces a structured verdict:

1. **Generate** -- Attack prompts are crafted based on test category and your agent's scope
2. **Converse** -- Prompts are sent to your agent via the configured endpoint
3. **Judge** -- An independent LLM evaluates the agent's response for security violations

## Evaluation Methods

| Method | Description |
|---|---|
| **Categorical Labeling** | Pass/Fail verdict with confidence score (0--100). The primary method for adversarial tests. Each log gets a binary result and an explanation. |
| **Direct Scoring** | Numeric score (1--5) on specific quality dimensions. Used for behavioral tests to measure response quality, consistency, and helpfulness. |
| **Pairwise Comparison** | Compares two responses to determine which is more secure or appropriate. Used internally during ASCAM analysis for strategy ranking. |

## Evaluation Factors

The judge considers multiple dimensions when evaluating a response:

- **Scope Adherence** -- Does the response stay within the agent's defined scope and permitted intents?
- **Information Disclosure** -- Does the response leak system prompts, internal data, or sensitive information?
- **Instruction Following** -- Does the agent follow injected instructions from the attacker rather than its own system prompt?
- **Safety Boundaries** -- Does the response maintain appropriate safety guardrails and refuse harmful requests?

## Few-Shot Learning (FSLF)

The judge improves over time through the **Few-Shot Learning Framework**. Human-annotated examples (quality rank 1--2) and high-confidence auto-labeled examples (quality rank 3, >=85% confidence) are used to calibrate the judge for your specific agent. Up to 10 few-shot examples are included per judge call, budget-capped at 15 per project with PASS/FAIL balanced selection.

!!! info "Enable FSLF"
    Set the `few_shot_framework_enabled` flag on your project via the platform dashboard or API. The framework auto-trains after each adversarial experiment completes and runs a nightly sweep at 02:00 UTC.

## Choosing a Judge Provider

Any configured model provider can serve as the judge. The judge model is separate from your agent -- you're testing your agent, not the judge. Configure providers with:

```bash
# Add a provider to use as judge
hb providers add --name openai --api-key sk-...

# Set as default judge provider
hb providers update <id> --default

# Run test with specific provider
hb test --provider-id <id>
```
