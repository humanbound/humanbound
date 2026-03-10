# Guardrails Export

Export security rules and guardrails learned from testing for integration with your agent's runtime defense layer.

## Export (Humanbound Format)

```bash
hb guardrails
```

## Export for OpenAI Moderation

```bash
hb guardrails --vendor openai
```

## Save to File

```bash
hb guardrails -o guardrails.json
```

## Export as YAML

```bash
hb guardrails --format yaml
```

## Include Reasoning

```bash
hb guardrails --include-reasoning
```

Guardrails are automatically learned from your testing campaigns using Few-Shot Learning Framework (FSLF). They include attack patterns, violation rules, and defense strategies.
