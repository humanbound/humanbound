# Arena

`hb arena` runs intentionally vulnerable AI agents on your machine, so you can practise testing agents and see what `hb test` finds. No `hb login` is needed.

## Concept and Architecture

Each agent is a packaged application with planted, documented vulnerabilities. You pull one from a catalog, run it locally, and attack it.

```text
hb test / other tools
        │  A2A v1.0 or OpenAI-compatible, with your access token
        ▼
gateway (127.0.0.1:11500)
        │
        ▼
door ──► agent containers        network without a route out
  │
  └────► the agent's model, and the hosts its manifest lists
```

| Part | What it does |
|---|---|
| **Catalog** | An index of agents, each described by an `arena.yaml` manifest. The default one is [humanbound-arena](https://github.com/humanbound/humanbound-arena). |
| **Agent** | One or more Docker containers, started without privileges, on a network that has no route out. |
| **Door** | A small proxy hb runs next to each agent: the way in from `127.0.0.1`, and the agent's only way out. |
| **Gateway** | A local server that presents every running agent the same way and requires your access token. |

!!! warning
    Arena agents are built to be exploited. Read the [disclaimer](#disclaimer) before you run one.

## Network and Privilege Isolation

Agents are built to be exploited, so hb limits what a hijacked one can reach and do.

**Network.** An agent's network has no route out. Through the door it may reach only:

| Destination | Source |
|---|---|
| Its model | The host and port of `OPENAI_BASE_URL`, or `api.openai.com:443` when unset. Only for agents that declare an `OPENAI_*` key. |
| Hosts its manifest lists | `runtime.egress` in `arena.yaml`. |
| Its own services | The other containers of a multi-container agent. |

Everything else is refused, including your machine and your local network. `hb arena logs <id> --door` shows what was `allowed` and what was `blocked`.

**Privileges.** Every container of an agent must meet the container baseline:

| Rule id | The container… |
|---|---|
| `non-root` | runs as a user other than root |
| `not-privileged` | is not privileged |
| `capabilities` | drops all capabilities and adds none |
| `no-new-privileges` | cannot gain new privileges |
| `host-namespaces` | shares no namespace with the host |
| `host-mounts` | mounts no host path or device |
| `loopback-ports` | publishes ports on `127.0.0.1` only |
| `internal-networks` | is only on networks with no route out |

Containers are also limited to 512 processes, 2 GB of memory and 2 CPUs.

hb checks the baseline before it reports an agent ready and again before a test, and stops an agent that fails. `hb arena check <id>` runs the check on demand: exit code `0` all rules met, `1` problems found, `2` agent not running or Docker unusable.

Neither protection can be switched off. Both have limits:

- An allowed destination is still a way out. hb filters by host and port, not by content.
- Only web traffic from clients that honour `HTTP_PROXY` and `HTTPS_PROXY` passes. Anything else fails to connect.
- The baseline covers how containers are configured, not what an agent does.
- On a Docker that cannot hide the network's gateway address, the agent may reach what the Docker host serves on all interfaces. `hb arena run` warns when that is so.

## Usage

### Quick start

You need Docker running and an LLM key for the agent.

```bash
pip install humanbound
hb arena ls                                   # browse the catalog
hb arena info <agent>                         # keys, network, planted vulnerabilities
hb arena config set OPENAI_API_KEY=sk-...     # the agent's model key
hb arena run <agent>                          # pull, start, wait until healthy
hb test --target arena://<agent>              # test it on the local engine
hb arena stop --all
```

### Model configuration

Two models are involved, configured separately.

| Model | Used for | Configured with |
|---|---|---|
| The agent's | The agent's own answers | `hb arena config set`, stored in `~/.humanbound/arena/arena.env` |
| The test engine's | The attacker and the judge in `hb test` | `HB_PROVIDER`, `HB_API_KEY`, `HB_MODEL` in your shell |

**The agent's model.** `hb arena info <id>` lists the keys an agent accepts. Most take:

| Key | Meaning |
|---|---|
| `OPENAI_API_KEY` | The key for the model's API. Usually required. |
| `OPENAI_MODEL` | The model name. The agent's default applies when unset. |
| `OPENAI_BASE_URL` | Any OpenAI-compatible server. `https://api.openai.com/v1` when unset. |

```bash
hb arena config set OPENAI_API_KEY=sk-... OPENAI_MODEL=gpt-4.1-mini

# a local model, for example Ollama on this machine
hb arena config set OPENAI_BASE_URL=http://host.docker.internal:11434/v1
hb arena config set OPENAI_API_KEY=ollama OPENAI_MODEL=llama3.1:8b
```

- Changes apply at the next `hb arena run`.
- The host and port of `OPENAI_BASE_URL` are the only model destination the agent may reach.
- `localhost` in `OPENAI_BASE_URL` would be the agent's own container; use `host.docker.internal`.
- On Linux the local server must listen on the Docker bridge address (usually `172.17.0.1`), not on `127.0.0.1`.

**The test engine's model.**

```bash
export HB_PROVIDER=openai HB_API_KEY=sk-...   # model defaults to gpt-4.1
export HB_PROVIDER=ollama                     # or fully local; defaults to llama3.1:8b
```

### Commands

| Command | What it does |
|---|---|
| `hb arena ls [--installed]` | List the catalog, or only installed agents. |
| `hb arena info <id> [--agent-yaml]` | Show an agent's details. Never installs. |
| `hb arena pull <id>` | Install an agent and pull its images. |
| `hb arena run <id> [--env-file FILE] [--yes]` | Start an agent and the gateway. |
| `hb arena ps` | List running agents and their URLs. |
| `hb arena logs <id> [-f] [--tail N] [--door]` | Show an agent's logs; `--door` shows what it reached or was refused. |
| `hb arena check <id> [--json]` | Check the agent's containers against the [container baseline](#network-and-privilege-isolation). |
| `hb arena reset <id>` | Recreate the agent. Drops its conversations. |
| `hb arena stop <id>` / `--all` / `--all --any-owner` | Stop one agent, all of yours, or every user's on this Docker. |
| `hb arena rm <id>` | Stop an agent and remove its images and manifest. |
| `hb arena endpoint <id>` | Print the agent's URLs, your token and a ready-to-use bot config. |
| `hb arena token` | Print only your access token. |
| `hb arena config set/get/unset` | Manage the keys agents receive. |
| `hb arena validate <path>` | Validate an `arena.yaml`. |
| `hb arena serve [--host H] [--port P]` | Run the gateway in the foreground. |

`HB_ARENA_PORT` changes the gateway port; set it for every `hb arena` and `hb test` command. Agents belong to the home directory that started them, so several users can share one Docker.

### Keys

Keys are stored in `~/.humanbound/arena/arena.env`, readable only by you.

- An agent receives only the keys its manifest declares. `hb arena run` prints their names, never their values.
- Precedence, later wins: `arena.env`, your shell, `--env-file`.
- Only LLM keys such as `OPENAI_API_KEY` are read from your shell, and only for agents from the default catalog.
- `HB_*` and `HUMANBOUND_*` names are never passed to an agent.

### Testing with hb test

```bash
hb test --target arena://<agent>
hb test --target arena://<agent> --no-reset --deep
```

- The agent must be running. It is reset to a clean state first; `--no-reset` skips that.
- The test scope and the judge's context come from the agent's manifest.
- Runs are **whitebox** when the agent reports its tool calls, otherwise **blackbox**.
- Results are saved under `.humanbound/results/<experiment-id>/`: `meta.json` (run, configuration, target) and `logs.jsonl` (one conversation per line, with tool executions for whitebox runs).

### Calling agents from other tools

Every call needs your token, as `Authorization: Bearer <token>` or `X-Arena-Token: <token>`. Treat it like a password.

```bash
TOKEN=$(hb arena token)

# A2A v1.0
curl -s http://127.0.0.1:11500/a2a/<agent> -H "Authorization: Bearer $TOKEN" \
  -H 'A2A-Version: 1.0' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"role":"ROLE_USER","messageId":"m1","parts":[{"text":"Hello"}]}}}'

# OpenAI-compatible: base URL http://127.0.0.1:11500/v1, model arena/<agent>, API key = token
curl -s http://127.0.0.1:11500/v1/chat/completions -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"arena/<agent>","messages":[{"role":"user","content":"Hello"}]}'
```

- A2A replies carry the text in `result.message.parts[0].text`. Send back `result.message.contextId` to continue a conversation.
- The Agent Card is at `/a2a/<agent>/.well-known/agent-card.json`.
- Agent failures return a non-200 status: 404 not running, 502 agent error, 503 Docker down, 504 timeout.
- The OpenAI-compatible endpoint starts a new conversation per request and does not stream.

`hb arena endpoint <id>` prints a bot config you can adapt for your own A2A agent with `hb test --endpoint`. It uses two placeholders: `$UUID` (a fresh id each time) and `$humanbound_conversation_id` (stable within a conversation).

### Other catalogs

`HB_ARENA_INDEX` points hb at another catalog: a URL, a fork, a local checkout or an `index.json` path.

- Agents from any catalog other than the default one never read keys from your shell.
- They are confirmed once before their first run, with their developer, images, key names and network access shown. `--yes` accepts without asking and is required in scripts.
- When a catalog's index lists image digests, hb pulls exactly those images and refuses a different local image under the same tag.

### Writing an agent

An agent is an `arena.yaml` in a folder named after its `id`. The Humanbound `agent.yaml` sits unchanged under `agent:`. Check it with `hb arena validate <path>`.

```yaml
developer:
  name: ACME Security Research
  url: https://acme.example/arena
source:
  image: ghcr.io/acme/arena-bank:1.0.0      # or compose: docker-compose.yml + service:
runtime:
  port: 8080
  env: {required: [OPENAI_API_KEY]}
  egress: [files.example.com]               # optional: hosts besides the model
```

- Images must run as a non-root user, listen on port 1024 or above, and work without capabilities.
- HTTP clients must honour the proxy variables. Do not declare them under `runtime.env`.
- Compose files may use prebuilt images only, with no published ports, host mounts or extra privileges.
- `ground_truth` declares each planted vulnerability, optionally with `references` such as `owasp-llm:LLM02`.
- For whitebox runs, point `integration.response.tool_calls` at a list of `{name, parameters, result}` items in the agent's reply.

### Platform notes

- **Linux:** Docker Engine 28 or later is recommended. Compose agents need the Compose v2 plugin.
- **macOS and Windows:** Docker Desktop.
- **Not supported:** Podman, and running `hb arena` inside the hb Docker image.

## Disclaimer

The arena is maintained for educational purposes. Its agents are deliberately vulnerable, and in places deliberately malicious: they exist to be attacked, so that you can learn how agents fail and how to test them.

- Never deploy an arena agent, and never run one where there is sensitive data or access to critical systems.
- Isolation is best effort. A container is not a virtual machine, and whatever an agent sends to a destination it may reach leaves your machine.
- Agents in the default catalog hold fake data only. Give an agent no real credentials beyond the LLM key it needs.
- You use the arena at your own risk. It comes with no warranty, and Humanbound accepts no liability for damage arising from its use.
