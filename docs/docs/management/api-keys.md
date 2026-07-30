---
description: "Create and scope Humanbound user API keys (hb_…) for headless access — CI/CD pipelines, Docker, automation scripts, and SIEM forwarders."
keywords:
  - API keys
  - hb api-keys command
  - HUMANBOUND_API_KEY
  - headless authentication
  - API key scopes
  - programmatic access
  - API key rotation
  - CI/CD authentication
faq:
  - q: How do I create a Humanbound API key?
    a: Run `hb api-keys create --name "CI Key"` to create a key. The key value (an `hb_…` secret) is shown only once during creation — store it securely immediately, because it cannot be retrieved again.
  - q: How do I use an API key without logging in?
    a: Set `HUMANBOUND_API_KEY=hb_…` in the environment. The CLI then authenticates with that key instead of `hb login`, acting as the key's owner. Add `HUMANBOUND_PROJECT_ID` (and optionally `HUMANBOUND_ORG_ID`) to select the target project headlessly.
  - q: What happens if I lose my API key?
    a: API keys are shown only once during creation. If lost, revoke the existing key with `hb api-keys delete <id>` and create a new one.
  - q: What scopes are available for API keys?
    a: Three cumulative scopes — `read` (view-only), `write` (adds creating projects and running tests), and `admin` (everything write can do, plus admin-level actions). A route declares a minimum, so a `write` key can also read. The default is `read`.
  - q: Which organisations can an API key access?
    a: Only organisations you OWN. A key never reaches an organisation where you are merely a member (admin, developer, or expert), and you can narrow it further with `--org` and `--projects`.
  - q: How do I deactivate an API key without deleting it?
    a: Run `hb api-keys update <id> --inactive` to deactivate a key. You can reactivate it later with `hb api-keys update <id> --active`.
---

# API Keys

A Humanbound **user API key** (`hb_…`) is the credential for **headless** access — CI/CD
pipelines, the Docker image, automation scripts, and SIEM forwarders — where an interactive
`hb login` isn't possible. The key authenticates **as its owner**, bounded by the scope and
selection you give it. `hb api-keys` covers create, list, update, and revoke.

!!! warning "Shown once"
    The key value appears only in the `create` response. Only a hash is stored, so it can
    never be retrieved again — copy it straight into your secret store. Lost a key? Revoke
    it and create a new one.

## Create a key

```bash
# Least privilege by default: read-only, all orgs you own
hb api-keys create --name "CI Key"

# Scoped: read-only, one org, one project, expires at a fixed time
hb api-keys create --name "CI Key" \
  --scope read \
  --org 2ab8ff03-2325-4f95-b22e-9262c09682c3 \
  --projects 68c7169a-6cb1-4f61-825f-bf1fd195ad7d \
  --expires 1767225600
```

| Flag | Meaning | Default |
|---|---|---|
| `--name` | Label shown in `hb api-keys list` | required |
| `--scope` | `read` \| `write` \| `admin` (cumulative) | `read` |
| `--org` | Restrict to organisation id(s); repeatable | all orgs you own |
| `--projects` | Restrict to project id(s); repeatable | all projects you own |
| `--expires` | Expiry as epoch seconds | never expires |

`--org` and `--projects` are validated at creation: you can only scope a key to an
organisation you **own** and to projects inside it. Anything else is rejected immediately,
so you never end up holding a key that silently can't do anything.

## Use a key headlessly

Set the key in the environment — no `hb login`, no browser:

```bash
export HUMANBOUND_API_KEY=hb_…            # the key from `create`
export HUMANBOUND_ORG_ID=<org-id>         # the organisation you own
export HUMANBOUND_PROJECT_ID=<project-id> # the project to work on

hb test --wait --fail-on high             # run a scan and gate the build
hb findings                               # read findings
hb posture                                # read the security posture
hb report -o report.html                  # export a report
```

With `HUMANBOUND_API_KEY` set, the CLI sends the key on every request and skips OAuth
entirely.

See [CI/CD Integration](../integrations/cicd.md) and [Docker](../integrations/docker.md)
for ready-made pipeline snippets.

## Which commands work headlessly

The connect → test → gate loop a pipeline needs:

| Command | Minimum scope | Notes |
|---|---|---|
| `hb connect` | `write` | Provisions a project + integration; use `--yes` for non-interactive |
| `hb test` | `write` | Pass `--provider-id` to skip provider auto-selection |
| `hb status <id>` | `read` | Single experiment; `--all` is **not** available headlessly |
| `hb logs` | `read` | |
| `hb findings` | `read` | |
| `hb posture` | `read` | Also `--org` |
| `hb report` | `read` | Project, `--org`, and `--assessment <id>` reports |
| `hb assessments list\|show` | `read` | Find the assessment id for `hb report --assessment` |
| `hb providers` | `read` | List only |

Anything not listed still requires `hb login`. Notably:

- **`hb api-keys …`** — key management is deliberately interactive-only: you cannot mint,
  rotate, or revoke a key using a key.
- **`hb orgs`, `hb members`, `hb projects`** — organisation and team administration.
- **`hb providers add|update|delete`** — provider setup (listing works headlessly).

If a command isn't supported, it fails with a clear error rather than falling back to a
browser login.

## What a key can reach

Two rules bound every request, and both must pass:

1. **Owner-only.** A key reaches **only organisations its creator owns** — never one where
   you are merely a member (admin, developer, or expert). Sharing a key with a teammate
   therefore keeps the blast radius inside your own organisation.
2. **Scope + selection.** The route's minimum scope must be satisfied (`admin` ⊇ `write` ⊇
   `read`), and the target org/project must be within the key's `--org` / `--projects`
   selection.

A key can only ever *narrow* what its owner can do — it never grants more. Key management
itself (`hb api-keys …`) always requires an interactive login: you cannot mint a key with a key.

!!! tip "Sharing keys with your team"
    As the organisation owner, create a tightly-scoped key (`--scope read`, one
    `--projects`, an `--expires`) and hand that to a teammate's pipeline. Requests made with
    it are attributed to you, the owner — so rotate per consumer rather than sharing one key
    everywhere.

## List keys

```bash
hb api-keys list
```

Shows id, name, scope, active state, and the key prefix (`hb_` + 8 characters) — never the
secret itself.

## Update a key

```bash
hb api-keys update <id> --name "New Name"   # rename
hb api-keys update <id> --scope write       # change scope
hb api-keys update <id> --inactive          # deactivate (requests → 401)
hb api-keys update <id> --active            # reactivate
```

## Revoke a key

```bash
hb api-keys delete <id>            # with confirmation
hb api-keys delete <id> --force    # skip confirmation
```

Deactivating (`--inactive`) stops a key immediately and is reversible; deleting is
permanent. Rotation is create-new → switch the secret → revoke-old.

## Scopes

Scopes are **cumulative** — a route declares the minimum it needs, so a higher scope also
satisfies the lower ones:

- **`read`** — view projects, experiments, findings, posture, and reports *(default)*
- **`write`** — everything `read` can do, plus create projects (`hb connect`) and run tests (`hb test`)
- **`admin`** — everything `write` can do, plus admin-level actions

Pick the lowest scope that works: a `read` key can gate a build on existing findings, but
cannot start a test or create a project.

<!-- faq -->
