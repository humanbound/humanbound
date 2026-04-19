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

When a finding is identified, someone needs to own it — investigate the root cause, implement a fix, and verify the resolution. Finding delegation assigns this responsibility to a specific team member and tracks progress through resolution.

### Why Delegation Matters

Without delegation, findings sit in a list with no accountability. Nobody knows who's working on what, which critical vulnerabilities are being actively addressed, and which are falling through the cracks. Delegation creates a clear chain of responsibility:

- **Security lead** reviews findings after a test cycle, assigns critical and high-severity findings to the appropriate developers
- **Developer** receives the assignment, investigates the agent's behavior, implements a fix
- **Security lead** verifies the fix by reviewing the next test cycle's results

### Delegation States

| State | Who acts | What happens |
|---|---|---|
| **Unassigned** | Security lead | Finding exists but no one owns it yet |
| **Assigned** | Security lead → Developer | Finding assigned to a team member. Timestamp recorded. |
| **In Progress** | Developer | Developer is actively working on a fix |
| **Verified** | Security lead | Fix confirmed — finding should not reappear in next test cycle |

### CLI Usage

```bash
# List all findings
hb findings

# Filter by status or severity
hb findings --status open
hb findings --severity critical

# Assign a finding to a team member
hb findings assign <finding-id> --assignee <member-id>

# Update delegation status
hb findings assign <finding-id> --status in_progress
hb findings assign <finding-id> --status verified

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
