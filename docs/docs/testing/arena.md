---
description: "Run intentionally vulnerable AI agents locally with hb arena and test them with hb test, with no login, served over the A2A protocol."
keywords:
  - hb arena
  - vulnerable AI agents
  - A2A agent
  - local agent testing
  - arena.yaml
---

# Arena

`hb arena` runs intentionally vulnerable AI agents on your machine so you can try `hb test` without wiring up your own agent. Each agent runs in Docker, bound to `127.0.0.1` only. A local gateway serves every agent over the [A2A protocol](https://a2a-protocol.org/) (v1.0) and an OpenAI-compatible endpoint.

## Quick start

```bash
pip install humanbound
hb arena ls
hb arena config set OPENAI_API_KEY=sk-...
hb arena run pricewatch
hb test --target arena://pricewatch
```

Arena targets always run on the [local engine](../local-engine/index.md), so no login is needed. Before each test the agent is recreated from its image so every run starts clean; pass `--no-reset` to skip that.

!!! warning
    Arena agents are vulnerable on purpose. Keep them on loopback. `hb arena serve --host 0.0.0.0` exposes them to your network (any Host header is accepted in that mode, with a warning printed at startup).

## Commands

| Command | What it does |
|---|---|
| `hb arena ls [--installed]` | List catalog agents |
| `hb arena info <id> [--agent-yaml]` | Details, required keys, planted vulnerabilities — never downloads or caches anything; `--agent-yaml` prints only the embedded agent.yaml |
| `hb arena pull <id>[:version]` | Download the manifest and image(s) |
| `hb arena run <id> [--env-file F]` | Pull if needed, start, health-check, serve |
| `hb arena ps` / `logs <id> [-f] [--tail N]` | Running agents / container logs |
| `hb arena reset <id>` | Recreate from the image (clean state), same keys as the last start |
| `hb arena stop [<id>] [--all]` | Stop one agent, or every agent and the gateway |
| `hb arena rm <id>` | Remove images and the cached manifest |
| `hb arena endpoint <id>` | curl, OpenAI and hb bot-config snippets |
| `hb arena config set/get/unset` | Keys the agents need, stored in `~/.humanbound/arena/arena.env` (0600) |
| `hb arena validate <path>` | Validate an `arena.yaml` |
| `hb arena serve [--host] [--port]` | Run the gateway in the foreground; refuses to start if a gateway is already answering on that port |

Only `pull` and `run` install anything; `info` and `validate` never touch Docker images or the cache.

### Keys

Agents' keys are separate from hb's own credentials — names starting with `HB_` or `HUMANBOUND_` are reserved for hb itself and are rejected everywhere (manifests, `config set`, `--env-file`). A value can't contain newlines, leading/trailing whitespace, or be wrapped in quotes.

Lookup order, later sources winning: `arena.env` (`hb arena config set`) < your shell environment < `--env-file`. `hb arena run` prints the *names* of the keys it passes to the agent, never their values.

## Calling agents from other tools

- **A2A:** Agent Card at `http://127.0.0.1:11500/a2a/<id>/.well-known/agent-card.json`, JSON-RPC `SendMessage` at `http://127.0.0.1:11500/a2a/<id>`. Tool calls and latency are in `result.message.metadata.humanbound`. Protocol errors (bad JSON-RPC, unsupported `A2A-Version`, notifications without an `id`) come back as HTTP 200 with a JSON-RPC `error`; agent failures come back as JSON-RPC `-32603` (or `-32006` for a response the gateway can't extract text from) with an HTTP status of 404/502/503/504 depending on the failure, plus a `google.rpc.ErrorInfo` reason in `error.data`. A missing `A2A-Version` header is accepted as `1.0`; any other version is rejected with `-32009`.
- **OpenAI-compatible:** base URL `http://127.0.0.1:11500/v1`, model `arena/<id>`. System messages are ignored (the agent's own system prompt comes from its `arena.yaml`), each request starts a fresh conversation, and streaming isn't supported.

Set `HB_ARENA_PORT` to use another port (it isn't persisted — export it wherever `hb arena` and `hb test` run), and `HB_ARENA_INDEX` to use your own catalog (a URL, an `index.json`, or a folder containing one).

## Testing your own A2A agent

The same A2A bot config works for any A2A agent. Run `hb arena endpoint <id>` to see it, change the endpoint, and pass it to `hb test --endpoint`.

`hb test --target arena://<id>` is exclusive with `--endpoint`, always forces the local engine, and resets the agent to a clean state before the run (skip that with `--no-reset`). The local engine's bot config format reserves two placeholders for building such payloads: `$UUID` (a fresh UUID on every occurrence, e.g. an A2A `messageId`) and `$humanbound_conversation_id` (one UUID per conversation, e.g. an A2A `contextId`) — alongside these, `$PROMPT` still carries the current turn's text.
