---
description: "Run the Humanbound CLI from the official Docker image — no Python install required. Covers the quickstart, file mounts, and platform auth; see CI/CD for pipeline examples."
keywords:
  - Docker image
  - ghcr.io/humanbound/humanbound
  - hb CLI Docker
  - container security testing
  - docker run hb test
  - host.docker.internal
  - Docker CI/CD
---

# Docker

Run the `hb` CLI anywhere Docker runs — no Python required. The official
image is published to GitHub Container Registry on every release:

```bash
docker pull ghcr.io/humanbound/humanbound
```

**Pin a tag in CI.** `:X.Y.Z`, `:X.Y`, and `:X` are published for every
release; `:latest` is for interactive experimentation, not pipelines.
Un-tagged and `:latest` always point at the newest release; `:2` tracks the
newest `2.x.y` and is re-pointed with every release in that major line;
`:2.7` and `:2.7.0` freeze to progressively narrower versions.

## Quick start (local mode — no login)

```bash
docker run --rm \
  -v "$PWD":/workspace \
  -e HB_PROVIDER=openai -e HB_API_KEY=$OPENAI_API_KEY -e HB_MODEL=gpt-4o-mini \
  ghcr.io/humanbound/humanbound \
  test --endpoint ./endpoint.json --wait --fail-on high
```

- `--rm` — the container runs one command, exits with `hb`'s exit code
  (`0` pass / `1` findings at or above `--fail-on` / `2` error), and removes
  itself.
- `-v "$PWD":/workspace` — mounts your project at the image's working directory.
  Inputs are read through it and results are written back through it.

## Two different keys

| Variable | What it is |
|---|---|
| `HB_API_KEY` | Your **LLM provider** key (OpenAI, Anthropic, …) — powers the attacker/judge models in local mode |
| `HUMANBOUND_API_KEY` | Your **Humanbound platform** project key — headless platform auth (coming soon) |

## Files in, results out

All file options (`--endpoint`, `--scope`, `--prompt`, `--context`,
`--repo`) are read inside the container. The rule: **mount your project at
`/workspace` and use relative paths** — `--scope ./scope.yaml` resolves to the
mounted host file. Absolute host paths do not exist inside the container, and
what happens next depends on the option: `--scope`, `--prompt`, and `--repo`
fail fast with a "does not exist" error; `--endpoint` falls through to "must
be a JSON string or path to a JSON file"; `--context` does neither — a
nonexistent path is silently treated as the literal context string. Double
check `--context` in particular, since a typo'd path won't error, it'll just
send the wrong text to the judge.

Results persist to `./.humanbound/results/exp-*/` on your host through the
same mount. Reports too:

```bash
docker run --rm -v "$PWD":/workspace ghcr.io/humanbound/humanbound report -o ./report.html
```

Inline escape hatches (no files needed): `--endpoint` accepts a JSON string
and `--context` accepts a plain string — useful for templating from CI
secrets.

**Two different `.humanbound` directories.** `<project>/.humanbound/results/`
is written relative to your workdir and persists on the host through the
`/workspace` mount above — that's the test results and reports. `~/.humanbound/`
in the container's home directory is a separate thing entirely: platform
credentials, config, and the telemetry identity. It only exists inside the
container if you mount it yourself, as shown in [Platform commands](#platform-commands).

## Reaching an agent on your host

Inside a container, `localhost` is the container. If the agent under test
runs on your machine:

- **macOS / Windows:** use `http://host.docker.internal:<port>` in your
  endpoint config.
- **Linux:** add `--add-host=host.docker.internal:host-gateway` to
  `docker run`, or use `--network host`.

## Platform commands

`hb status`, project-scoped `hb logs`, and platform-mode `hb test` need platform auth:

- **Today:** log in on the host, then mount your credentials (read-write —
  the CLI refreshes tokens):

  ```bash
  hb login   # on the host, once
  docker run --rm -v ~/.humanbound:/home/hb/.humanbound \
    ghcr.io/humanbound/humanbound status
  ```

- **Coming soon:** `-e HUMANBOUND_API_KEY=<project-key>` — headless project-key
  auth, no browser involved.

## Using the image in CI

For ready-made GitLab and CircleCI snippets that run this image in
your pipeline, see [CI/CD Integration](cicd.md#other-ci-systems-via-the-docker-image).

## Notes

- Linux bind-mount permissions: the container runs as uid 1000; add
  `--user $(id -u):$(id -g)` if your uid differs and result files come out
  root-owned or unwritable.
- Telemetry follows the CLI's normal rules — auto-disabled when a CI
  environment variable is set, and `-e HB_TELEMETRY_DISABLED=1` or
  `-e DO_NOT_TRACK=1` always works. It's also auto-disabled whenever the
  container has no TTY, which is every `docker run` without `-it` — including
  all of the example commands on this page — so scripted and CI runs never
  send anything. The fresh-machine caveat (a new anonymous ID and `install`
  event per container) only applies to interactive `-it` runs without a
  mounted `~/.humanbound`; mounting it as shown in Platform commands keeps the
  telemetry identity stable.
- Commands that open a browser (`hb login`, `hb docs`) don't work inside a
  container — run them on the host.
