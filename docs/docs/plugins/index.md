---
description: "Humanbound plugins for AI coding agents — adversarial security testing inside Claude Code and Cursor."
---

# Plugins [Preview]

Humanbound publishes a marketplace of plugins that bring adversarial
security testing into AI coding agents — currently **Claude Code** and
**Cursor**. This is [**AI TDD**](../reference/glossary.md): defining an
agent's security boundaries while you build it.

The plugins live in their own repository:
[**github.com/humanbound/plugins**](https://github.com/humanbound/plugins).
This page covers what's available today and how to install. Operational
details (slash commands, configuration, per-host differences) live in the
repo README and per-plugin documentation.

## What is a plugin?

A plugin is a self-contained extension installed into your AI coding agent
that adds slash commands, skills, and (optionally) an MCP server. Plugins
are Apache-2.0 licensed and run locally. They use the `humanbound` CLI and
MCP server under the hood — anything they can do, you can also do from the
terminal.

## Available plugins

| Plugin | Hosts | What it does |
|---|---|---|
| [`humanbound-test`](https://github.com/humanbound/plugins/tree/main/plugins/humanbound-test) | Claude Code · Cursor | Run adversarial / security tests against a local AI agent end-to-end — auto-detects your FastAPI server, exposes it via ngrok, you author `bot-config.json` with your endpoints, the plugin dispatches via the `humanbound` MCP and renders findings with severity counts and posture score |

More plugins are on the roadmap — see
[ROADMAP](https://github.com/humanbound/plugins/blob/main/ROADMAP.md) in the
repo.

## Install

### Claude Code

Claude Code installs directly from this Git URL via its plugin marketplace:

```text
/plugin marketplace add https://github.com/humanbound/plugins.git
/plugin install humanbound-test@humanbound-plugins
```

Restart your Claude Code session and the `/humanbound-test:*` slash commands
appear.

### Cursor

Cursor 2.5 does not yet support installing community plugins from a public
Git URL. Sideload via symlink:

```bash
git clone https://github.com/humanbound/plugins.git ~/src/humanbound-plugins
mkdir -p ~/.cursor/plugins/local
ln -s ~/src/humanbound-plugins/plugins/humanbound-test ~/.cursor/plugins/local/humanbound-test
# Restart Cursor
```

Verify in **Cursor → Settings → Plugins → Local plugins** that
`humanbound-test` is listed and enabled.

## Requirements

Plugins that dispatch adversarial tests through the Humanbound platform
(currently `humanbound-test`) require:

- The `humanbound[mcp]` Python package — the plugin offers to install it on
  first run
- An authenticated `hb` session — `hb login` is a hard prerequisite for
  `/humanbound-test:run`. The plugin verifies this on every run and falls
  back to an in-flow login recovery if the CLI is not yet authenticated
- `ngrok` CLI authenticated — the plugin walks you through
  `brew install ngrok` and auth-token setup if needed

Local-only operation without the platform is not currently in scope for the
plugins; the `humanbound` CLI itself supports local mode (see the
[Local Engine](../local-engine/index.md) docs) for offline use.

## Preview status

Plugin APIs, slash commands, and on-disk state layouts under `.humanbound/`
may change before each plugin reaches 1.0. Pin to a specific tag if you
depend on a particular shape.

## More

- **Repository:** [github.com/humanbound/plugins](https://github.com/humanbound/plugins)
- **Roadmap:** [github.com/humanbound/plugins/blob/main/ROADMAP.md](https://github.com/humanbound/plugins/blob/main/ROADMAP.md)
- **Discord:** [discord.gg/gQyXjVBF](https://discord.gg/gQyXjVBF)
