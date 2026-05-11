---
description: "Install Humanbound — pip install, optional local engine extras, and quick paths for both account-less local mode and the full platform."
---

# Installation

## Install

```bash
pip install humanbound
```

For local engine support (run tests without login):

```bash
pip install "humanbound[engine]"
```

## Verify

```bash
hb --version
hb --help
```

## Requirements

- Python 3.10 or higher
- An LLM provider API key (OpenAI, Anthropic, Azure, etc.) OR [ollama](https://ollama.com) for full local isolation
- An AI agent endpoint to test against

## Optional Dependencies

| Extra | Install | What it adds |
|---|---|---|
| `engine` | `pip install "humanbound[engine]"` | Local testing engine (OpenAI, Anthropic, Google SDKs) |
| `firewall` | `pip install "humanbound[firewall]"` | Firewall training (humanbound-firewall, scikit-learn, torch) |
| `mcp` | `pip install "humanbound[mcp]"` | MCP server for AI coding assistants |

## Configure Provider

Before running local tests, configure your LLM provider:

```bash
# Environment variables (recommended for CI/CD)
export HB_PROVIDER=openai
export HB_API_KEY=sk-...

# Or config file (recommended for interactive use)
hb config set provider openai
hb config set api-key sk-...

# Or ollama (no API key needed)
export HB_PROVIDER=ollama
export HB_MODEL=llama3.1:8b
```

See [Provider Configuration](../local-engine/provider-config.md) for all supported providers.

## First Test

```bash
hb test --endpoint ./bot-config.json --repo . --wait
```

See [Quick Start](quick-start.md) for the full walkthrough.
