# Authentication & Context

Manage authentication, organisation context, and access to documentation.

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
