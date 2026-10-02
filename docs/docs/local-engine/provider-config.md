---
description: "Configure the LLM provider the local engine uses for attack generation and response evaluation — bring your own API key."
keywords:
  - LLM provider configuration
  - HB_PROVIDER
  - HB_API_KEY
  - ollama setup
  - Azure OpenAI configuration
  - OpenRouter configuration
  - humanbound providers
  - provider precedence
  - hb config command
faq:
  - q: Which LLM providers does Humanbound support?
    a: Humanbound supports OpenAI, Anthropic (Claude), Google (Gemini), Azure OpenAI, Grok (xAI), and Ollama. Ollama requires no API key and runs fully locally.
  - q: How do I configure my LLM provider?
    a: Provider configuration is resolved in order — CLI flags first, then environment variables (e.g., `HB_PROVIDER`, `HB_API_KEY`), then the config file at `~/.humanbound/config.yaml`. The config file is set via `hb config set provider` and `hb config set api-key`.
  - q: How do I configure Azure OpenAI with Humanbound?
    a: Set `HB_PROVIDER=azureopenai`, provide your Azure API key via `HB_API_KEY`, and set `HB_ENDPOINT` to the full deployment URL including `?api-version=`, for example `https://your-resource.openai.azure.com/openai/deployments/your-deployment/chat/completions?api-version=2025-01-01-preview`.
  - q: Can I use OpenRouter or another OpenAI-compatible API?
    a: Yes. Set `HB_PROVIDER=openai`, put that service's key in `HB_API_KEY`, and set `HB_ENDPOINT` to its base URL, for example `https://openrouter.ai/api/v1`. `HB_MODEL` takes the service's own model ID, such as `anthropic/claude-haiku-4.5` on OpenRouter. The same works for LiteLLM, vLLM and other servers that expose `/chat/completions`.
  - q: Can I run Humanbound with no external API calls at all?
    a: Yes — use Ollama. Set `HB_PROVIDER=ollama` and `HB_MODEL=llama3.1:8b`, start `ollama serve`, and tests will only call your bot and the local Ollama instance. Note that local models produce lower-quality attacks than cloud providers.
---

# Provider Configuration

The local engine needs an LLM provider for attack generation and response evaluation, and you bring your own API key. Provider settings resolve in order — CLI flags override environment variables, which override the config file at `~/.humanbound/config.yaml`. Six providers are supported (OpenAI, Anthropic Claude, Google Gemini, Azure OpenAI, Grok, and Ollama for fully-local isolation); Azure requires a full endpoint URL with `?api-version=`.

## Configuration Methods

Provider is resolved in this order (first match wins):

1. **CLI flags** (one-off override)
2. **Environment variables** (CI/CD)
3. **Config file** (`~/.humanbound/config.yaml`)

### Environment Variables

```bash
export HB_PROVIDER=openai
export HB_API_KEY=sk-proj-...
export HB_MODEL=gpt-4.1        # optional for openai and ollama only (see below)
```

`HB_MODEL` (or `hb config set model …`) is optional only for `openai` (default `gpt-4.1`) and `ollama` (default `llama3.1:8b`). Every other provider needs an explicit model; for Azure OpenAI that is your deployment name.

### Config File

```bash
hb config set provider openai
hb config set api-key sk-proj-...
hb config set model gpt-4.1

# View current config
hb config
```

Config is stored at `~/.humanbound/config.yaml`. Never sent to Humanbound.

!!! note "Environment variables and the config file don't mix"
    When `HB_PROVIDER` is set, the config file is not read at all, so an `endpoint` or `model` saved with `hb config set` is ignored. Set everything through environment variables, or everything through the config file.

### Supported Providers

| Provider | `HB_PROVIDER` | Key prefix | Notes |
|---|---|---|---|
| OpenAI | `openai` | `sk-` | Default model `gpt-4.1`. Optional `HB_ENDPOINT` for OpenAI-compatible APIs |
| Anthropic | `anthropic` or `claude` | `sk-ant-` | `HB_MODEL` required |
| Google | `gemini` | | `HB_MODEL` required |
| Azure OpenAI | `azureopenai` | | Requires `HB_ENDPOINT` with `?api-version=`; `HB_MODEL` = deployment name |
| Grok (xAI) | `grok` | | `HB_MODEL` required |
| Ollama | `ollama` | Not needed | Full local isolation; default model `llama3.1:8b` |

### Azure OpenAI

Azure requires the full endpoint URL including the api-version:

```bash
export HB_PROVIDER=azureopenai
export HB_API_KEY=your-azure-key
export HB_MODEL=your-deployment   # required: the Azure deployment name
export HB_ENDPOINT="https://your-resource.openai.azure.com/openai/deployments/your-deployment/chat/completions?api-version=2025-01-01-preview"
```

### OpenRouter and other OpenAI-compatible APIs

The `openai` provider accepts a base URL in `HB_ENDPOINT`, so any service that speaks the OpenAI chat completions API works, including OpenRouter, LiteLLM and vLLM:

```bash
export HB_PROVIDER=openai
export HB_API_KEY=sk-or-...                      # the service's key, not an OpenAI key
export HB_ENDPOINT=https://openrouter.ai/api/v1  # base URL; /chat/completions is added
export HB_MODEL=anthropic/claude-haiku-4.5       # the service's model ID
```

With no `HB_ENDPOINT`, requests go to `api.openai.com` as before. If you switch from Ollama to OpenAI with `hb config`, clear the old endpoint with `hb config set endpoint ""`, or requests will go to the Ollama URL. An `HB_ENDPOINT` left in your shell does the same thing, so `unset HB_ENDPOINT` too.

### Ollama (Full Isolation)

For zero external network calls — everything runs locally:

```bash
# Install
pip install "humanbound[engine]"

# Start ollama
ollama serve
ollama pull llama3.1:8b

# Configure
export HB_PROVIDER=ollama
export HB_MODEL=llama3.1:8b   # optional, this is the default

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

<!-- faq -->
