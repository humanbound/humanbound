---
description: "Findings are persistent vulnerability records that track security issues across test cycles — they remember when they first appeared and which regressions reintroduced them."
---

# Findings

Findings are persistent vulnerability records that track security issues across test cycles. Unlike per-experiment insights (which are snapshots), findings have memory — they know when they first appeared, whether they've been fixed, and whether they've come back.

## Finding Lifecycle

Every finding moves through a lifecycle that reflects its real-world status:

| State | Description | Posture impact |
|---|---|---|
| **Open** | Vulnerability detected and not yet resolved | Full penalty (1.0x) |
| **Fixed** | Not reproduced in recent test cycles | No penalty (0x) |
| **Regressed** | Was fixed, but reappeared — worse than a new finding because it means a previous fix was lost | Elevated penalty (1.2x) |
| **Stale** | Not triggered in 14+ consecutive days of testing — may still exist but current test strategies haven't reached it | Reduced penalty (0.5x) |

The lifecycle is automatic. When monitoring runs a new test cycle:
- Findings seen again remain **open**
- Findings not seen transition to **stale** after 14 days
- Stale findings that reappear transition to **regressed**
- Users can manually mark findings as **fixed**

## Team Delegation

When a finding is identified, someone needs to own it — investigate the root cause, implement a fix, and verify the resolution. Finding delegation assigns this responsibility to a specific team member and tracks progress through four stages: unassigned → assigned → in progress → verified.

See [Team & Collaboration](../management/collaboration.md) for the full delegation workflow, roles, and webhook notifications.

### CLI Usage

```bash
# List all findings
hb findings

# Filter by status or severity
hb findings --status open
hb findings --severity critical

# Mark a finding as fixed
hb findings update <finding-id> --status fixed

# Update severity
hb findings update <finding-id> --severity high

# Export as JSON
hb findings --json
```

### Webhook Notifications

When findings are assigned or their delegation status changes, webhook events are emitted:

| Event | When |
|---|---|
| `finding.assigned` | Finding assigned to a team member |
| `finding.acknowledged` | Assignee acknowledged the assignment |
| `finding.resolution_verified` | Resolution verified by security lead |

Configure webhooks to route these to Slack, email, or your ticketing system:

```bash
hb webhooks create --url https://slack.example.com/webhook --events finding.assigned,finding.resolution_verified
```

## Connection to Posture

Findings directly impact the posture score through severity-weighted penalties:

| Severity | Weight |
|---|---|
| Critical | 25 |
| High | 15 |
| Medium | 8 |
| Low | 3 |
| Info | 1 |

The penalty formula combines severity weight with finding status weight (open: 1.0, regressed: 1.2, stale: 0.5, fixed: 0.0). More open and regressed findings = lower posture score. Fixing findings and verifying fixes improves posture.

!!! note "Platform feature"
    Finding lifecycle tracking and team delegation require a Humanbound account. Local testing produces per-experiment insights, not persistent findings.
