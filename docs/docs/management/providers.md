---
description: "Configure the LLM providers Humanbound uses for attack generation, judging, and evaluations — credentials, default selection, and per-experiment overrides."
---

# Model Providers

Configure LLM providers used for generating attacks, running security judges, and performing evaluations.

## List Providers

```bash
hb providers list
```

## Add Provider (Interactive)

```bash
hb providers add -i
```

## Add OpenAI Provider

```bash
hb providers add --name openai --api-key sk-...
```

## Add Azure OpenAI Provider

```bash
hb providers add --name azureopenai \
  --api-key ... \
  --endpoint https://your-resource.openai.azure.com
```

## Add Claude Provider

```bash
hb providers add --name claude --api-key sk-ant-...
```

## Update Provider

```bash
# Update API key
hb providers update <id> --api-key sk-new-key

# Set as default provider
hb providers update <id> --default
```

## Remove Provider

```bash
hb providers remove <id>
```

## Supported Providers

| Provider | Label | Requirements |
|---|---|---|
| Azure OpenAI | `azureopenai` | API key + endpoint URL |
| OpenAI | `openai` | API key |
| Anthropic Claude | `claude` | API key |
| Google Gemini | `gemini` | API key |
| Grok (xAI) | `grok` | API key |
| Custom | `custom` | API key + whitelisted endpoint |

!!! info "Custom providers"
    For self-hosted or OpenAI-compatible models, the endpoint must be whitelisted via the `CUSTOM_MODEL_PROVIDER_ENDPOINT` environment variable in your Humanbound deployment.
