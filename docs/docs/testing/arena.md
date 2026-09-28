---
description: "hb arena runs intentionally vulnerable AI agents locally in Docker, serves them over A2A v1.0 and an OpenAI-compatible API, and tests them with hb test --target arena://<id>."
keywords:
  - hb arena
  - vulnerable AI agents
  - arena://
  - A2A gateway
  - local AI red teaming
  - hb test --target
  - OpenAI-compatible endpoint
  - practice targets
---

# Arena

`hb arena` runs intentionally vulnerable AI agents on your machine and lets you test them with `hb test` in one step. It pulls a packaged agent from the Humanbound Arena catalog, starts it in Docker, and serves it through a local gateway that speaks A2A v1.0 (with an OpenAI-compatible façade), so every agent looks the same to `hb` and to other tools. No `hb login` is needed. Each agent also works as a worked example of pointing `hb` at your own agent.

## Quick Start

You need Docker (running) and an LLM key for the agent.

```bash
pip install humanbound
hb arena ls                                   # browse the catalog
hb arena info <agent>                         # details, required keys, planted vulnerabilities
hb arena config set OPENAI_API_KEY=sk-...     # the agent's key, stored in ~/.humanbound/arena/arena.env
hb arena run <agent>                          # pull, start, wait for health, start the gateway
hb test --target arena://<agent>              # adversarial test on the local engine
hb arena stop --all                           # stop your agents and your gateway
```

Replace `<agent>` with an agent id from `hb arena ls`; the examples below use the same placeholder.

`hb test` on an arena target always runs on the local engine, which needs its own LLM provider (for the attacker and the judge), for example:

```bash
export HB_PROVIDER=openai HB_API_KEY=sk-...   # model defaults to gpt-4.1
# or fully local:
export HB_PROVIDER=ollama                     # model defaults to llama3.1:8b
```

**Local models for the agent.** Agents that list `OPENAI_BASE_URL` among their keys (check `hb arena info <id>`) can use any OpenAI-compatible server instead of OpenAI. The agent runs in a container, so point it at the host, for example Ollama with Docker Desktop:

```bash
hb arena config set OPENAI_BASE_URL=http://host.docker.internal:11434/v1
hb arena config set OPENAI_API_KEY=ollama     # most local servers ignore the value
hb arena config set OPENAI_MODEL=llama3.1:8b  # when the agent lists OPENAI_MODEL
```

The host and port of `OPENAI_BASE_URL` are what hb lets the agent reach as its model (see [Network access](#network-access)): with the settings above that is `host.docker.internal:11434` and nothing else on your machine. `localhost` would be the agent's own container, so hb warns when `OPENAI_BASE_URL` points there.

On Linux with Docker Engine, a server listening on the host's `127.0.0.1` can't be reached from a container. Make the server listen on the Docker bridge address (usually `172.17.0.1`; see `ip -4 addr show docker0`); `host.docker.internal` then works as above (hb gives its proxy a `host-gateway` entry for it), and so does the address itself:

```bash
OLLAMA_HOST=172.17.0.1 ollama serve           # or OLLAMA_HOST=0.0.0.0, firewalled from your network
hb arena config set OPENAI_BASE_URL=http://172.17.0.1:11434/v1
```

`OLLAMA_HOST=0.0.0.0` also works, but exposes Ollama to your network unless a firewall blocks port 11434; with `ufw` or `firewalld` you may also need to allow that port from the Docker networks.

!!! warning "Intentionally vulnerable"
    Arena agents are built to be exploited, and their isolation is best effort: use them at your own risk, and never run them where there is sensitive data or access to critical systems. `hb arena run` says so every time it starts an agent. Their containers and the gateway listen on `127.0.0.1` only, and every gateway call needs your [access token](#access-token). `hb arena serve --host <addr>` binds the gateway to another interface and makes every running agent reachable (with the token) from your network; only do that on a network you trust, and never on a machine that holds real data or credentials the agents could reach.

    hb blocks an agent's [network access](#network-access), except for its model and the hosts its manifest lists. That narrows what a hijacked agent can do; it doesn't make it harmless. Whatever the agent sends to a destination it may reach leaves your machine. Don't run arena agents next to local services that hold real data or accept requests without authentication. On Linux with Docker Engine before 28, ports published on `127.0.0.1` may also be reachable from other machines on your local network; `hb arena run` warns about it, and upgrading the engine fixes it.

## Commands

None of these commands needs `hb login`. `ls`, `info` and `validate` never install anything; `pull` and `run` cache the manifest and pull the images.

| Command | What it does |
|---|---|
| `hb arena ls [--installed]` | List the catalog (or only installed agents), with a STATE column: `installed` or `running`. |
| `hb arena info <id>[:version] [--agent-yaml]` | Show details (developer, upstream project if any, and the image digests the catalog publishes), required and optional keys, what the agent may reach on the network and the planted vulnerabilities. `--agent-yaml` prints only the embedded `agent.yaml`. Never installs. |
| `hb arena validate <path>` | Validate an `arena.yaml` (its folder must be named after its `id`); for compose agents also check the compose file. Never installs. |
| `hb arena pull <id>[:version]` | Install the agent and pull its image(s), by digest when the catalog lists one (see [Catalogs and trust](#catalogs-and-trust)), and the image of hb's proxy. |
| `hb arena run <id>[:version] [--env-file FILE] [--yes]` | Install if needed, resolve keys, confirm an agent from a catalog other than the default one on its first run (`--yes` skips the question), start the agent with its [network access](#network-access) blocked, wait for its health check and make sure the gateway is up. Re-running an agent drops the conversations the gateway held for it. |
| `hb arena ps` | List running agents with their A2A and native URLs. |
| `hb arena logs <id> [-f] [--tail N] [--door]` | Show an agent's container logs (default: last 200 lines). `--door` shows what the agent reached or was refused on the network instead. |
| `hb arena reset <id>` | Recreate the agent from its image. This drops its conversations. |
| `hb arena check <id> [--json]` | Check the running agent's containers against the [container baseline](#container-baseline): one problem per line, exit code 0, 1 or 2. Never stops anything. |
| `hb arena stop <id>` / `--all` / `--all --any-owner` | Stop one of your agents, or all of yours, including one whose container exited or was stopped outside hb. Your gateway stops when none of your agents is left. `--all --any-owner` also stops every other user's or session's arena agents on this Docker (it warns with how many); their gateways keep running. |
| `hb arena rm <id>` | Stop the agent and remove its images and cached manifest. Only the images its manifest names are removed, and not one that a container outside the arena uses. |
| `hb arena endpoint <id>` | Print the A2A and OpenAI URLs, your gateway access token, a `curl` example and a ready-to-use hb bot config (both carry the token). |
| `hb arena token` | Print only your gateway access token (created if there is none yet), for scripts: `TOKEN=$(hb arena token)`. Treat it like a password. |
| `hb arena serve [--host H] [--port P]` | Run the gateway in the foreground (default `127.0.0.1`, port `HB_ARENA_PORT` or 11500; 1–65535). The access token is required whatever the host. |
| `hb arena config set/get/unset` | Manage the agents' keys (see below). |

The gateway listens on `http://127.0.0.1:11500`. Set `HB_ARENA_PORT` to use another port (a number from 1 to 65535); set it for every `hb arena` and `hb test` command, since they all find the gateway through it. Calls to the gateway and the agents on `127.0.0.1` never go through a proxy, even when `HTTP_PROXY` or `ALL_PROXY` is set.

**Several users or sessions on one machine.** Arena agents belong to the home directory that started them (its *owner*, a short id derived from `~/.humanbound/arena`). Containers, networks and compose projects are named `arena-<owner>-<id>` and labelled `io.humanbound.arena.owner=<owner>`, so two users, sandboxes or CI jobs with different `HOME`s can run the same agent side by side. `ps`, `stop`, `stop --all`, `rm`, `reset` and `hb test --target` only ever see your own agents; only `stop --all --any-owner` reaches the others (including containers from hb versions before owners existed, named `arena-<id>`). If containers from an older hb (without an owner) are left on this Docker, `ps` and `stop --all` point you at `hb arena stop --all --any-owner`. Each owner also needs its own gateway port: if `HB_ARENA_PORT` points at a port where another owner's gateway runs, hb refuses to use or stop it and asks you to pick another port.

## Network Access

An agent can be talked into doing things, so hb starts it with its network access blocked. It may reach:

| Destination | Where it comes from |
|---|---|
| its model | the host and port of `OPENAI_BASE_URL`, or `api.openai.com:443` when that key is unset. Only for agents that list an `OPENAI_*` key. |
| the hosts its manifest lists | `runtime.egress` in `arena.yaml`: exact host names, port 443 unless the entry says otherwise. |
| its own services | the other containers of a compose agent. |

Nothing else: not the internet, not your machine, not your local network. `hb arena info <id>` shows what an agent may reach before you install it, `hb arena run` prints it every time, and the confirmation before the first run of an agent from another catalog shows it too.

**How.** The agent's Docker networks are created without a route out (`--internal`), and, where Docker supports it, without an address of their own on the host. Next to each agent hb runs a small container of its own, the *door*, on the agent's networks and on one ordinary network. It carries calls from `127.0.0.1` on your machine in to the agent, and it is an HTTP proxy that lets the destinations above through and answers `403` (with the header `X-Arena-Egress: blocked`) to everything else. hb sets `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` (and their lowercase spellings) in every container of the agent, so clients that honour them use the proxy for everything but the agent's own services. The door runs in the official Python image, referenced by digest, as a non-root user, read-only and without capabilities.

```text
$ hb arena logs <agent> --door
door: in → arena-<owner>-<agent>:8080
door: out → api.openai.com:443
allowed api.openai.com:443
blocked example.com:443
```

One line per destination tried: `allowed`, `blocked` (not on the list, or a listed host that resolves to a private address) or `failed` (on the list, but unreachable). When an agent doesn't become healthy, `hb arena run` shows what the door refused.

**What it is not.**

- An allowed destination is still a way out. Whatever the agent sends to its model or to a listed host leaves your machine; hb filters by host name and port and does not look at what is sent.
- Only web traffic passes, and only from clients that use the proxy. A client that ignores the proxy variables, or speaks another protocol, can't connect at all; it fails instead of getting through. With Docker Engine 25.0.5 or later, names outside the agent's own services don't resolve inside its containers either; older engines may still pass name lookups on.
- Your own choice of model is let through as you wrote it, also when it is on your machine or your local network (that is what a local model needs): the host and the port of `OPENAI_BASE_URL`, nothing else there. Hosts from a manifest must resolve to public addresses.
- On a Docker that can't create a network without an address on the host, the agent may still reach what the Docker host serves on all interfaces, through the network's gateway address. `hb arena run` says so when that is the case. With Docker Desktop the Docker host is its virtual machine, not your computer.
- A container is not a virtual machine. This narrows what a hijacked agent can reach; the warning above still holds.

There is no option to start an agent without the block. An agent whose client can't use a proxy has to be changed to use one.

## Container Baseline

hb starts every agent container without privileges and out of reach of the host. Before it reports an agent ready, and again before a test, it inspects every container of the agent (for a compose agent, its side services too, running or not) and the networks they are on, and refuses to continue unless each one:

| Rule | The container… |
|---|---|
| `non-root` | runs as a user other than root: `Config.User` is set and is not `root` or `0` (a `:group` part is ignored). |
| `not-privileged` | is not privileged. |
| `capabilities` | drops all Linux capabilities (`ALL`) and adds none. |
| `no-new-privileges` | can't gain new privileges (`no-new-privileges`, or `no-new-privileges:true`). |
| `host-namespaces` | shares no namespace with the host (pid, ipc, network, uts, user), nor its pid, ipc or network namespace with another container. |
| `host-mounts` | mounts no host path (no `bind` or `npipe` mounts; named volumes and `tmpfs` are fine) and maps no host device. |
| `loopback-ports` | publishes ports on `127.0.0.1` only, both where they are published now and where its configuration would publish them (publishing nothing is fine). |
| `internal-networks` | is only on networks that have no route out (Docker reports `Internal: true` for each). |

A field hb can't read counts as a problem, since the rule can't be confirmed.

**When it runs.** `hb arena run` and `hb arena reset` (and a reset through the gateway, including the one `hb test` does before a run) check the containers right after starting them: if any rule fails, hb stops the agent and prints one problem per line instead of reporting it running. `hb test --target arena://<id>` checks again right before the experiment starts; if a rule fails it prints the problems, stops the agent and exits with code 2. There is no option to skip the check.

**`hb arena check <id>`** runs the same check on demand and only reports: it never stops anything.

```text
$ hb arena check <agent>
✓ <agent>: 2 containers meet the container baseline

$ hb arena check <agent>
arena-<owner>-<agent>-backend-1: non-root: runs as root (Config.User is '0')
```

| Exit code | Meaning |
|---|---|
| `0` | Every container meets the container baseline. |
| `1` | Problems found, one per line: `<container>: <rule>: <problem>` (a summary goes to stderr). |
| `2` | The agent isn't running, or Docker is unusable. |

`--json` prints `{"agent": "<id>", "containers": ["<name>", …], "violations": [{"container", "rule", "message"}, …]}` for scripts, with the same exit codes. `containers` lists every container checked; an agent with no containers to check is a problem (`(agent): inspect-data: no containers to check`), never a pass.

The rule ids (`inspect-data`, `non-root`, `not-privileged`, `capabilities`, `no-new-privileges`, `host-namespaces`, `host-mounts`, `loopback-ports`, `internal-networks`) are stable identifiers that scripts may match on. `inspect-data` reports problems with the agent as a whole (its container is `(agent)`): no containers to check, or inspect data hb can't read.

**What it does not cover.** The baseline is about how the containers and their networks are configured, nothing more. It says nothing about what an agent does, what its code or image contain, or what it sends to the destinations it may reach (see [Network access](#network-access)). Meeting it doesn't make an agent harmless: arena agents stay intentionally vulnerable, and their isolation is best effort.

## Platform Notes

- **Linux.** Docker Engine and Docker Desktop both work. If `hb arena` says it got *permission denied on the Docker socket*, add your user to the `docker` group (`sudo usermod -aG docker $USER`, then log out and in) or, for rootless Docker, set `DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock`. Compose agents need the Compose v2 plugin (`docker compose`, e.g. the `docker-compose-plugin` package). Docker Engine 28 or later is recommended (see the warning above); for local models, see [above](#quick-start).
- **macOS.** Docker Desktop (or another engine that provides the `docker` CLI and socket, such as Colima or OrbStack).
- **Windows.** Docker Desktop. Two limitations: there is no lock around starting the gateway, so two `hb` commands starting it at the same moment race (one of them fails and can simply be re-run); and the files under `%USERPROFILE%\.humanbound\arena` (keys, gateway token, results) are protected by your user profile's permissions, not by POSIX modes.
- **Podman** isn't supported, not even through its `docker` compatibility command.
- **The hb Docker image** can't run `hb arena`: the agents run on Docker on your machine, which the container can't drive. Commands that need Docker stop with a message; install hb on the host (`pip install humanbound`) and run `hb arena` and `hb test --target arena://<id>` there.

## Keys

Arena agents need their own keys (usually an LLM key). They are stored in `~/.humanbound/arena/arena.env`, readable only by you:

```bash
hb arena config set OPENAI_API_KEY=sk-... OPENAI_MODEL=gpt-4.1-mini
hb arena config get                 # values are masked
hb arena config unset OPENAI_MODEL
```

- **Only declared keys are passed.** An agent receives just the keys its manifest lists as required or optional.
- **Precedence** (later wins): `arena.env` < your shell environment < `--env-file`.
- **Only LLM keys, and only for agents from the default catalog, come from your shell.** An agent installed from the default Humanbound catalog may read `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `OLLAMA_HOST`, `MISTRAL_API_KEY`, `GROQ_API_KEY` and `XAI_API_KEY` from your shell. Every other key, and every key of an agent from another catalog (`HB_ARENA_INDEX`: a fork, a local checkout, a file path), comes only from `arena.env` and `--env-file`, so an exported secret is never handed to code you haven't reviewed by accident.
- **Confirming agents from other catalogs.** The first time you run an agent from a catalog other than the default one, `hb arena run` says which catalog it comes from and shows its developer (name, URL, contact), the upstream repository, commit and license it packages (if any), its images (with the digests the catalog lists, if any) and the key names it will receive, and asks before it starts. Your answer is remembered per agent version (and asked again if its manifest, compose file or digests change). `--yes` accepts without asking, and is required when there is no terminal (CI, scripts).
- **Reserved names.** `HB_*` and `HUMANBOUND_*` names belong to hb's own credentials: `config set` refuses them, and they are skipped everywhere else.
- **Value rules.** Values can't contain newlines, start or end with whitespace, or be wrapped in quotes. A value from your shell or `--env-file` that contains a newline, carriage return or NUL stops `hb arena run` with `cannot use key <NAME>` (the value is never printed).
- `hb arena run` prints the **names** of the keys it passes, never the values. If a required key is missing it stops before starting anything and tells you which `hb arena config set` to run.
- `hb arena reset` reuses the keys from the last `run`; key changes take effect on the next `run`. If the saved keys are missing (for example, the file under `~/.humanbound/arena/run/` was deleted) and the agent requires keys, `reset` refuses with `no saved keys for <id> → hb arena run <id> again` rather than restart the agent without them.

## Catalogs and Trust

There is one kind of arena agent. What hb trusts is **where the catalog came from**, never anything a manifest says about itself:

- **The default catalog** (the Humanbound Arena index on GitHub) is trusted: its agents may read the LLM keys above from your shell, and run without a confirmation.
- **Any other catalog** (`HB_ARENA_INDEX` set to another URL, a fork, a local checkout or an `index.json` path) is not: its agents never read your shell and are confirmed once before their first run (see [Keys](#keys)).

`pull` and `run` record where an agent was installed from (and the image digests below) in `~/.humanbound/arena/agents/<id>/<version>/installed.json`. Anonymous usage telemetry names the agent and version only for agents from the default catalog; for any other catalog it sends `agent: "custom"`.

### Image digests

A catalog's index can list, for each agent, the images it published and their registry digests (`images: [{ref, digest}]`); the published Humanbound catalog does. hb then runs exactly those images, for image agents and for every listed compose service:

- If the tag (`ref`) isn't on your machine, hb pulls `<repository>@<digest>` and tags it as `ref`, so Docker and Compose find it.
- If the tag is already there, it must be that image: its registry digests must include `<repository>@<digest>`. Otherwise `pull` and `run` refuse to use it and say what they found, for example a different digest (a stale pull) or *locally built, no registry digest* (you built the image yourself). To fix it, either remove the stale local image (`docker rmi <ref>`) so hb pulls the published one, or run from a local catalog (`HB_ARENA_INDEX=<checkout>`) to use your local build.
- Images the index doesn't list, and catalogs whose index lists no digests (a local checkout, a pull request), use tags as usual, with no warning.

## Calling Agents From Other Tools

### Access token

Every gateway call needs your access token, so other users and processes on your machine (and, with `serve --host`, on your network) can't drive your agents. hb creates it on first need in `~/.humanbound/arena/gateway.token` (readable only by you; one per home directory) and sends it on its own calls. `hb arena token` prints just the token (creating it if needed), so scripts can use `TOKEN=$(hb arena token)` without knowing where it is kept; `hb arena endpoint <id>` prints it too. Treat it like a password: anyone who has it can drive your running agents. Pass it as:

- `Authorization: Bearer <token>`, which A2A clients and OpenAI-compatible clients send: for an OpenAI SDK or eval tool, set `OPENAI_API_KEY=<token>` (and the base URL below);
- or `X-Arena-Token: <token>`.

A call without it, or with a wrong one, gets **401** (a JSON-RPC `error` on `POST /a2a/<id>`, `{"error": {...}}` elsewhere). The Agent Card needs it too, and declares it as an HTTP bearer scheme. The only exception is `GET /arena/v1/health`, which without the token answers just `{"status": "ok"}` (with it, also the gateway's version, pid and owner). The token never appears in saved results or telemetry; to rotate it, stop your gateway first (`hb arena stop --all`), then delete the file; the next `hb arena run` creates a new one. (A gateway whose token file is gone no longer accepts hb's calls, so hb treats it as someone else's and won't stop or reuse it.)

### A2A

Every running agent is an A2A v1.0 server behind the gateway:

```
GET  http://127.0.0.1:11500/a2a/<id>/.well-known/agent-card.json   Agent Card
POST http://127.0.0.1:11500/a2a/<id>                               JSON-RPC: SendMessage, GetTask
```

```bash
TOKEN=$(hb arena token)
curl -s http://127.0.0.1:11500/a2a/<agent> -H "Authorization: Bearer $TOKEN" \
  -H 'A2A-Version: 1.0' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"role":"ROLE_USER","messageId":"m1","parts":[{"text":"Hello"}]}}}'
```

- The reply is always a direct Message: `result.message.parts[0].text` holds the text and `result.message.contextId` the conversation id. Send the same `contextId` to continue a conversation; omit it to start a new one. Conversations are kept in the gateway's memory, per agent, until `reset` or a gateway restart.
- Per-turn metadata sits under `result.message.metadata.humanbound`: `agent`, `version`, `latency_ms` and, when the agent reports them, `tool_calls` (normalized to `{name, parameters, result}` items, see [Reporting tool calls](#reporting-tool-calls)) with the agent's own list under `tool_calls_raw`.
- **Protocol errors** (bad JSON, bad envelope, unknown method, non-text parts, a part whose `text` isn't a string, unsupported `A2A-Version`) come back as **HTTP 200** with a JSON-RPC `error`. `GetTask` always returns "task not found", since the gateway creates no tasks.
- **Agent failures** come back **non-200** (404 not running, 502 agent error or unreadable reply, 503 Docker down, 504 timeout) with a JSON-RPC `error` whose `data` holds a `google.rpc.ErrorInfo` with a `reason` such as `AGENT_TIMEOUT`, so clients fail the turn instead of reading an error as a reply.
- Agents that speak A2A natively are passed through: their replies are normalized to a direct Message like any other agent's, and their JSON-RPC errors come back with HTTP 502.
- Besides the token, the gateway only accepts `Content-Type: application/json` POSTs (others get **415**) and loopback `Host` headers (others get **400**), so web pages in your browser can't drive it.

### OpenAI-compatible façade

Eval tools that speak OpenAI Chat Completions can use base URL `http://127.0.0.1:11500/v1` with model `arena/<id>` and the token as the API key (`OPENAI_BASE_URL=http://127.0.0.1:11500/v1 OPENAI_API_KEY=<token>`):

```bash
curl -s http://127.0.0.1:11500/v1/chat/completions -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"model":"arena/<agent>","messages":[{"role":"user","content":"Hello"}]}'
```

Each request is a new conversation (prior `messages` are passed as history only to agents whose history the gateway keeps), system messages are ignored, and streaming isn't supported. Metadata is returned under a top-level `humanbound` key.

## Testing With hb test

```bash
hb test --target arena://<agent>
hb test --target arena://<agent> --no-reset --deep
```

- `--target` takes only `arena://<id>` values and can't be combined with `--endpoint`. The agent must be running (`hb arena run <id>`).
- The run always uses the local engine. The agent's `agent:` block becomes the test scope (unless you pass `--scope`, `--repo` or `--prompt`) and its manifest `context` goes to the judge.
- Before the run the agent is reset to a clean state. `--no-reset` skips that, and so does `--no-auto-start`.
- Right before the experiment starts, the agent's containers are checked against the [container baseline](#container-baseline) (with or without a reset). If one fails, `hb test` prints the problems, stops the agent and exits with code 2.
- Arena runs are **whitebox** when the agent reports its tool calls: an `integration.type: http` agent whose manifest sets `integration.response.tool_calls`. The gateway returns those tool calls in the per-turn metadata and the engine passes them to the judge, so findings can cite what the agent did, not only what it said. Other agents (including native A2A agents) run **blackbox**, and `hb test` prints `Depth: blackbox`.

**Your own A2A agent.** `hb arena endpoint <id>` prints the bot config `hb test` uses for a whitebox arena target (for a blackbox agent `hb test` leaves out the `telemetry` block). It holds your gateway token in its `Authorization` header, so keep it private. Use it as a template for any A2A v1.0 agent with `hb test --endpoint`: change the `endpoint` URL and, if your agent reports metadata, the `telemetry` paths. Two placeholders make it work with A2A, and both names are reserved:

- `$UUID`: a fresh id at every occurrence (the JSON-RPC `id` and `messageId`).
- `$humanbound_conversation_id`: one id per test conversation, stable across its turns (the `contextId`).

```json
{
  "streaming": null,
  "chat_completion": {
    "endpoint": "http://127.0.0.1:11500/a2a/<agent>",
    "headers": {"A2A-Version": "1.0", "Authorization": "Bearer <your gateway token>"},
    "payload": {"jsonrpc": "2.0", "id": "$UUID", "method": "SendMessage",
                "params": {"message": {"role": "ROLE_USER", "messageId": "$UUID",
                                        "contextId": "$humanbound_conversation_id",
                                        "parts": [{"text": "$PROMPT"}]}}}
  },
  "telemetry": {"mode": "per_turn",
                "extraction_map": {"metadata_path": "result.message.metadata.humanbound",
                                   "tool_executions": "tool_calls"}}
}
```

## Results

Every local run (arena targets always run locally) saves its results under `.humanbound/results/<experiment-id>/` in the directory you ran `hb test` from (owner-only permissions):

- **`meta.json`**: the experiment. Besides `id`, `status`, `test_category`, `testing_level`, `lang`, `results` (stats, insights, posture) and `scope`, it has:
    - `configuration`: `{test_category, testing_level, lang, provider, model}`, the engine's provider name and model (never its key or endpoint, and never the bot config or the gateway token);
    - `target` for `hb test --target arena://…` runs: `{kind: "arena", agent_id, agent_version, gateway, whitebox}` (`null` for other runs).
- **`logs.jsonl`**: one tested conversation per line: `thread_id`, `conversation` (`[{u, a}]` turns), `result` (`pass`/`fail`/`error`), `gen_category`, `fail_category`, `explanation`, `severity`, `confidence`, `exec_t` and `meta`. For a whitebox run, `meta.telemetry` holds:
    - `tools`: the tool names called, in order;
    - `tool_executions`: `[{turn, tool_name, parameters, result}]`, one per call, with the turn (1-based) it happened in;
    - `turns`: `[{turn, metadata}]`, the per-turn metadata the integration returned (for an arena agent: `agent`, `version`, `latency_ms`), minus `tool_calls` and `tool_calls_raw`, which `tool_executions` already holds;
    - `trace_id`, `tokens`, `api_calls`.

`turns` is saved for any bot config with `per_turn` telemetry, not only for arena targets: it is whatever the config's `metadata_path` points at in each reply, so don't put secrets there. To keep logs a reasonable size, any string longer than 4,000 characters in `telemetry` is cut and ends with `…[truncated N chars]`, lists longer than 200 items are cut with a last `…[N more items]` item, objects with more than 200 keys are cut with a `"…": "[N more keys]"` entry, and NaN or infinite numbers are saved as `null`. A benchmark can check an agent's `ground_truth` against these files, for example a `tool_called: {name, arg_regex}` rule against `tool_executions[].tool_name` and the JSON of `parameters`, and `reply_contains` / `reply_regex` against the `a` of each turn, and use `target.agent_id` and `target.agent_version` to pick the manifest.

## Writing an Arena Agent

An agent is an `arena.yaml` manifest: arena fields at the top level and the Humanbound `agent.yaml` embedded unchanged under `agent:`. It lives in a folder named after its `id` (`agents/<id>/arena.yaml` in the catalog). Check it locally with `hb arena validate path/to/<id>/arena.yaml`.

```yaml
developer:                          # required: who builds and maintains the agent
  name: ACME Security Research
  url: https://acme.example/arena   # http(s)
  contact: arena@acme.example       # optional
source:
  image: ghcr.io/acme/arena-bank:1.0.0
  upstream:                         # optional: the project the agent packages, if any
    repo: https://github.com/acme/vulnerable-bank
    ref: c0cf9a14adad76e9d6a53c41741f625334bd9971   # the full 40-character commit SHA
    license: Apache-2.0             # optional, an SPDX license id
```

- `developer` (`name`, `url`, optional `contact`) is shown by `hb arena info` and before the first run of an agent from a catalog other than the default one. `source.upstream` is optional; when present, `repo` must be an http(s) URL, `ref` a full commit SHA and `license` an SPDX id.
- `source.image` names a prebuilt image; `source.compose` names a compose file for multi-container agents. Reference images by tag: the digests hb checks come from the catalog's index (see [Image digests](#image-digests)), not from the manifest.
- Compose files are checked against an allowlist before they run. Services must use prebuilt `image:` (no `build:`), top-level networks must be plain bridge networks (only `driver: bridge`, `internal` and `labels`; no `ipam`), top-level volumes must be local (only `driver: local` and `labels`), and nothing may reach the host (no published ports, bind mounts, devices or extra privileges). `$` interpolation is refused, except a service `environment` value that is exactly `${KEY}` for a key the manifest declares; that is how the agent receives its keys. For the same reason an `environment` entry without a value (`- KEY` or `KEY:`) is only allowed for a declared key.
- Every agent container runs with `cap_drop: ALL`, `no-new-privileges`, `restart: "no"` and limits of 512 processes, 2 GB of memory and 2 CPUs (a compose service keeps a lower `mem_limit` or `cpus` of its own). Build images for that: set the runtime user with `USER` in the Dockerfile instead of switching users at start-up (`su`, `gosu`, `setpriv`, setuid binaries or a `chown` in the entrypoint fail without capabilities), and listen on a port of 1024 or above (binding a lower port needs `CAP_NET_BIND_SERVICE`, even as root).
- `runtime.egress` lists what the agent must reach besides its model, as exact lowercase host names, each with an optional port (`files.example.com`, `api.example.com:8443`; port 443 when left out): at most 20, no wildcards, addresses or URLs, and no names of the user's own machine or network (`host.docker.internal`, `*.local`, `*.internal`, …). Leave it out when the agent only talks to its model and its own services. Everything else is blocked (see [Network access](#network-access)), so make the agent's clients honour `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` (most HTTP libraries do by default), and don't declare those variables under `runtime.env`: hb sets them. A compose service can't be called `hb-door`.
- Every container must meet the [container baseline](#container-baseline), or hb stops the agent. In particular no image may run as root: set a non-root `USER` in your Dockerfiles, and give a compose service whose third-party image runs as root by default a `user:` (for example `user: "65534"`), if the image can run that way.
- Each `ground_truth` entry declares one planted vulnerability: `category` and `description`, and optionally `title`, `severity`, `vector`, `success` conditions and `references`. `references` maps the vulnerability to published standards, as a list of unique `<standard>:<id>` strings (for example `owasp-llm:LLM02` or `atlas:AML.T0051.000`). hb checks only that shape and shows the references in `hb arena info`; which ids exist is for the catalog to check.
- `hb arena validate` also accepts a local `.env` next to the manifest while you develop; installed agents never read one.
- `arena.yaml` and compose files can't use YAML anchors or aliases (`&name`, `*name`, `<<: *name`) and must stay under 256 KB. Text fields can't contain control characters (newlines and tabs are fine in descriptions, `context` and the `agent:` block). `runtime.timeout_s` and `runtime.health.timeout_s` are at most 600.

### Reporting tool calls

For a whitebox agent, point `integration.response.tool_calls` at a list in the agent's JSON reply. Emit one item per tool call in the preferred shape:

```json
{"reply": "...", "trace": [{"name": "lookup_price", "parameters": {"sku": "A1"}, "result": "9.99"}]}
```

with `response: {text: reply, tool_calls: trace}`. The gateway normalizes other common shapes to that one:

- the tool name from `name`, `tool` or `tool_name`;
- the arguments from `parameters`, `args`, `arguments` or `input` (a JSON-object string is parsed);
- the result from `result`, `output` or `content`;
- a call entry (`"type": "call"` or `"tool_call"`) followed by its result entry (`"type": "result"` or `"tool_result"`, same name or no name) becomes one item;
- items that aren't JSON objects are dropped.

The agent's original list is kept under `tool_calls_raw` in the metadata.
