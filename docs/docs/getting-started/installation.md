---
description: "Install Humanbound — pip install, optional local engine extras, and quick paths for both account-less local mode and the full platform."
keywords:
  - humanbound installation
  - pip install humanbound
  - humanbound CLI setup
  - humanbound extras
  - local engine installation
  - humanbound ollama
  - humanbound MCP server
faq:
  - q: What are the system requirements for Humanbound?
    a: Humanbound requires Python 3.10 or higher, an LLM provider API key (OpenAI, Anthropic, Azure, etc.) or ollama for full local isolation, and an AI agent endpoint to test against.
  - q: How do I install Humanbound with local engine support?
    a: Run `pip install "humanbound[engine]"` to include the local testing engine with OpenAI, Anthropic, and Google SDK support. The base `pip install humanbound` installs the CLI without the local engine extras.
  - q: What optional extras can I install with Humanbound?
    a: Three extras are available — `engine` adds the local testing engine, `firewall` adds firewall training with scikit-learn and torch, and `mcp` adds an MCP server for AI coding assistants.
  - q: Do I need an API key to run tests?
    a: You need an LLM provider API key (OpenAI, Anthropic, Azure, etc.) for cloud-based testing, but you can use ollama with no API key at all for full local isolation.
  - q: How do I verify my Humanbound installation?
    a: Run `hb --version` to confirm the CLI is installed and `hb --help` to see available commands.
---

# Installation

Install Humanbound with `pip install humanbound`, optionally adding extras for the local testing engine, firewall training, or MCP server. The sections below walk through the install command, the available extras, system requirements, and running your first test, with pointers to provider configuration and the Quick Start guide.

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

<!-- faq -->
