---
description: "Manage Humanbound authentication, organisation context, and access scopes for the CLI, MCP server, and API."
title: Authentication
keywords:
  - humanbound authentication
  - hb login
  - hb logout
  - hb whoami
  - OAuth authentication
  - on-prem login
  - organisation context
  - humanbound credentials
---

# Authentication & Context

The `hb login` command authenticates against the Humanbound platform via OAuth, storing credentials at `~/.humanbound/`; `hb logout` revokes the session. Use `hb whoami` to see your current user, org, and project, `hb switch` to move between organisations, and `hb --base-url ... login` to authenticate against an on-prem deployment instead of the default platform.

## Version

```bash
hb --version
```

## Login

```bash
# Standard login (api.humanbound.ai)
hb login

# Force re-authentication (skip "already logged in" prompt)
hb login --force

# On-prem: login against a custom API endpoint
hb --base-url https://my-server.com/api login

# Use a custom callback port (default: 8085)
hb login --port 9090
```

Opens your browser for OAuth authentication. Credentials are stored locally at `~/.humanbound/`. When using `--base-url`, the custom endpoint is persisted for subsequent commands.

| Option | Description |
|---|---|
| `--force, -f` | Force re-authentication even if already logged in |
| `--port` | Local OAuth callback port (default: 8085) |
| `--base-url` | API base URL for on-prem deployments |

## Headless (API key)

`hb login` opens a browser for OAuth, which isn't possible in CI/CD, Docker, or cron. There,
authenticate with a [user API key](management/api-keys.md) instead:

```bash
export HUMANBOUND_API_KEY=hb_…            # from `hb api-keys create`
export HUMANBOUND_ORG_ID=<org-id>         # selects the organisation (replaces `hb orgs use`)
export HUMANBOUND_PROJECT_ID=<project-id> # selects the project (replaces `hb projects use`)

hb test --wait --fail-on high
```

When `HUMANBOUND_API_KEY` is set the CLI sends the key on every request and skips OAuth
entirely, acting as the key's owner within the key's scope and org/project selection. No
credentials are written to `~/.humanbound/`.

Not every command is available this way — see
[API Keys → Which commands work headlessly](management/api-keys.md#which-commands-work-headlessly)
for the supported set, and for scoping and rotation.

## Logout

```bash
# Revoke the backend session and clear local credentials
hb logout

# Also revoke browser session
hb logout --revoke

# Custom callback port for revoke (default: 8085)
hb logout --revoke --port 9090
```

`hb logout` revokes the backend session, signing out any active session on the Humanbound platform or CLI for the same user. Use `--revoke` to also clear the Auth0 SSO browser cookie.

## Check Authentication Status

```bash
hb whoami
```

Shows current user, active organisation, and active project.

## Switch Organisation

```bash
hb switch <org-id>
```

## Open Documentation

```bash
# Open main documentation
hb docs

# Open specific topic
hb docs quickstart
```
