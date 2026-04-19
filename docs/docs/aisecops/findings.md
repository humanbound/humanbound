# Findings

Findings are persistent, deduplicated vulnerability records that bridge individual experiments to your overall security posture. They provide long-term memory of security issues across multiple test runs.

## List All Findings

```bash
hb findings
```

## Filter by Status

```bash
hb findings --status open
hb findings --status stale
hb findings --status fixed
hb findings --status regressed
```

## Filter by Severity

```bash
hb findings --severity critical
hb findings --severity high
hb findings --severity medium
hb findings --severity low
hb findings --severity info
```

## Export as JSON

```bash
hb findings --json
```

## Update Finding Status

```bash
# Mark as fixed
hb findings update <id> --status fixed

# Update severity
hb findings update <id> --severity high
```

## Assign Finding to Team Member

```bash
# Assign to a team member
hb findings assign <id> --assignee <member-id>

# Assign with delegation status
hb findings assign <id> --assignee <member-id> --status in_progress
```

## Finding States

| State | Penalty | Description |
|---|---|---|
| **Open** | 1.0x | Active vulnerability requiring attention |
| **Stale** | 0.5x | Not seen in 30+ days, may be fixed |
| **Fixed** | 0x | User-confirmed resolution |
| **Regressed** | 1.2x | Was fixed, but reappeared (worse than open) |

## Delegation States

Findings support team delegation: **unassigned** -> **assigned** -> **in_progress** -> **verified**.
