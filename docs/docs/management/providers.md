---
description: "Configure the LLM providers Humanbound uses for attack generation, judging, and evaluations — credentials, default selection, and per-experiment overrides."
keywords:
  - LLM providers
  - hb providers command
  - model provider configuration
  - OpenAI provider
  - Claude provider
  - Azure OpenAI configuration
  - default provider
  - custom LLM provider
---

# Model Providers

The `hb providers` commands manage the LLM providers Humanbound uses to generate adversarial attacks, run security judges, and produce evaluations. Six providers are supported out of the box (OpenAI, Anthropic Claude, Google Gemini, Azure OpenAI, Grok, and a Custom OpenAI-compatible option), plus an interactive setup flow. One provider can be marked as the default; experiments can override per-run with `--provider-id`.

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
