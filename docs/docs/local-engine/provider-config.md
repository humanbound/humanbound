---
description: "Configure the LLM provider the local engine uses for attack generation and response evaluation — bring your own API key."
faq:
  - q: Which LLM providers does Humanbound support?
    a: Humanbound supports OpenAI, Anthropic (Claude), Google (Gemini), Azure OpenAI, Grok (xAI), and Ollama. Ollama requires no API key and runs fully locally.
  - q: How do I configure my LLM provider?
    a: Provider configuration is resolved in order — CLI flags first, then environment variables (e.g., `HB_PROVIDER`, `HB_API_KEY`), then the config file at `~/.humanbound/config.yaml`. The config file is set via `hb config set provider` and `hb config set api-key`.
  - q: How do I configure Azure OpenAI with Humanbound?
    a: Set `HB_PROVIDER=azureopenai`, provide your Azure API key via `HB_API_KEY`, and set `HB_ENDPOINT` to the full deployment URL including `?api-version=`, for example `https://your-resource.openai.azure.com/openai/deployments/your-deployment/chat/completions?api-version=2025-01-01-preview`.
  - q: Can I run Humanbound with no external API calls at all?
    a: Yes — use Ollama. Set `HB_PROVIDER=ollama` and `HB_MODEL=llama3.1:8b`, start `ollama serve`, and tests will only call your bot and the local Ollama instance. Note that local models produce lower-quality attacks than cloud providers.
---

# Provider Configuration

The local engine needs an LLM provider for attack generation and response evaluation. You bring your own API key.

## Configuration Methods

Provider is resolved in this order (first match wins):

1. **CLI flags** (one-off override)
2. **Environment variables** (CI/CD)
3. **Config file** (`~/.humanbound/config.yaml`)

### Environment Variables

```bash
export HB_PROVIDER=openai
export HB_API_KEY=sk-proj-...
export HB_MODEL=gpt-4.1        # optional, uses provider default
```

### Config File

```bash
hb config set provider openai
hb config set api-key sk-proj-...
hb config set model gpt-4.1

# View current config
hb config
```

Config is stored at `~/.humanbound/config.yaml`. Never sent to Humanbound.

### Supported Providers

| Provider | `HB_PROVIDER` | Key prefix | Notes |
|---|---|---|---|
| OpenAI | `openai` | `sk-` | GPT-4o, GPT-4.1, etc. |
| Anthropic | `claude` | `sk-ant-` | Claude 3.5, Claude 4, etc. |
| Google | `gemini` | | Gemini Pro, etc. |
| Azure OpenAI | `azureopenai` | | Requires `HB_ENDPOINT` with `?api-version=` |
| Grok (xAI) | `grok` | | |
| Ollama | `ollama` | Not needed | Full local isolation |

### Azure OpenAI

Azure requires the full endpoint URL including the api-version:

```bash
export HB_PROVIDER=azureopenai
export HB_API_KEY=your-azure-key
export HB_MODEL=gpt-4.1
export HB_ENDPOINT="https://your-resource.openai.azure.com/openai/deployments/your-deployment/chat/completions?api-version=2025-01-01-preview"
```

### Ollama (Full Isolation)

For zero external network calls — everything runs locally:

```bash
# Start ollama
ollama serve
ollama pull llama3.1:8b

# Configure
export HB_PROVIDER=ollama
export HB_MODEL=llama3.1:8b

# Run test (only calls: your bot + local ollama)
hb test --endpoint ./config.json --scope ./scope.json --wait
```

!!! note "Ollama quality"
    Local models produce lower-quality attacks and evaluations than GPT-4 or Claude. For best results, use a cloud provider. Use ollama when isolation is more important than accuracy.

## After Login: Humanbound Provider

When logged in, every Humanbound account includes an LLM provider — no external API key required. Tests run on the platform automatically use it:

```bash
hb login
hb connect --endpoint ./config.json
hb test --wait
# Uses Humanbound's LLM provider — no HB_PROVIDER or HB_API_KEY needed
```

You can still use your own provider on the platform by adding it via `hb providers add`.
