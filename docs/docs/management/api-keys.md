---
description: "Create and rotate API keys for programmatic access to Humanbound — for CI/CD pipelines, automation scripts, and SIEM forwarders."
faq:
  - q: How do I create a Humanbound API key?
    a: Run `hb api-keys create --name "CI Key"` to create a key. The key value is shown only once during creation — store it securely immediately, because it cannot be retrieved again.
  - q: What happens if I lose my API key?
    a: API keys are shown only once during creation. If lost, you must revoke the existing key with `hb api-keys delete <id>` and create a new one.
  - q: What scopes are available for API keys?
    a: Three scopes are available — `admin` for full access including user management and sensitive operations, `write` for creating and modifying projects and running tests, and `read` for view-only access to projects, experiments, and results.
  - q: How do I deactivate an API key without deleting it?
    a: Run `hb api-keys update <id> --inactive` to deactivate a key. You can reactivate it later with `hb api-keys update <id> --active`.
---

# API Keys

Create and manage API keys for programmatic access to Humanbound. Useful for CI/CD pipelines, automation scripts, and integrations.

## List API Keys

```bash
hb api-keys list
```

## Create API Key

```bash
# Create key (shows key once!)
hb api-keys create --name "CI Key"

# Create scoped key
hb api-keys create --name "CI Key" --scopes read
```

!!! warning "Important"
    API keys are shown only once during creation. Store them securely. If lost, you must revoke and create a new key.

## Update API Key

```bash
# Update name
hb api-keys update <id> --name "New Name"

# Activate key
hb api-keys update <id> --active

# Deactivate key
hb api-keys update <id> --inactive
```

## Revoke API Key

```bash
# Revoke with confirmation
hb api-keys delete <id>

# Skip confirmation
hb api-keys delete <id> --force
```

## Scopes

- **admin**: Full access including user management and sensitive operations
- **write**: Create and modify projects, run tests, update findings
- **read**: View-only access to projects, experiments, and results
