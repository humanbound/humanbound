---
description: "Manage organisation members and their access levels — invitation flows, role assignment, and removal."
---

# Team Members

Manage organisation members and their access levels.

## List Members

```bash
hb members list
```

## Invite Member

```bash
# Invite as developer (default)
hb members invite user@example.com

# Invite with specific role
hb members invite user@example.com --role admin
```

## Remove Member

```bash
# Remove with confirmation
hb members delete <id>

# Skip confirmation
hb members delete <id> --force
```

## Access Levels

| Role | Description |
|---|---|
| **Owner** | Full control including billing, member management, and all projects |
| **Admin** | Manage projects, members, and run all operations except billing |
| **Developer** | Create and manage projects, run tests, view results |
| **Expert** | View projects and results, annotate findings, no write access to projects or tests |
