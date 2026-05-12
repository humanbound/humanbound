---
description: "Team workflows for AI agent security — coordinate security leads, developers, and compliance officers around shared projects and findings."
---

# Team & Collaboration

AI agent security is not a solo activity. The security lead identifies vulnerabilities. Developers fix them. Compliance officers verify the fixes. Humanbound provides the structure to coordinate this workflow — from discovery through resolution.

## Team Roles

Every organization member has a role that determines what they can see and do:

| Role | What they can do |
|---|---|
| **Owner** | Full control — projects, members, billing, all operations |
| **Admin** | Manage projects, members, run tests, view results (no billing) |
| **Developer** | Create projects, run tests, view results, manage providers |
| **Expert** | View projects and results, annotate findings — no write access to projects or tests |

The **Expert** role is designed for external security consultants or auditors who need to review findings and provide feedback without the ability to modify projects or run tests.

### Managing Members

```bash
# List members
hb members list

# Invite with role
hb members invite security@company.com --role admin
hb members invite dev@company.com --role developer
hb members invite auditor@external.com --role expert

# Remove
hb members remove <member-id>
```

## Finding Delegation

When a security test identifies vulnerabilities, the findings need to be triaged, assigned, and resolved. Finding delegation tracks this workflow with clear ownership and status at every stage.

### The Workflow

```
Test identifies vulnerability
        │
        ▼
  ┌─────────────┐
  │ Unassigned   │  Finding exists, nobody owns it
  └──────┬──────┘
         │  Security lead assigns to developer
         ▼
  ┌─────────────┐
  │ Assigned     │  Developer is responsible, timestamp recorded
  └──────┬──────┘
         │  Developer starts working on fix
         ▼
  ┌─────────────┐
  │ In Progress  │  Fix is being implemented
  └──────┬──────┘
         │  Next test cycle confirms fix works
         ▼
  ┌─────────────┐
  │ Verified     │  Resolution confirmed
  └─────────────┘
```

### Why It Matters

Without delegation:
- Critical findings sit in a list with no owner
- Multiple developers may work on the same issue unknowingly
- There's no visibility into which vulnerabilities are being actively addressed
- Fixed findings aren't verified — they may reappear silently

With delegation:
- Every critical finding has an owner and a deadline
- The security lead sees at a glance: what's unassigned, what's in progress, what's verified
- Webhook notifications keep the team informed without manual status meetings
- The next test cycle automatically validates whether the fix worked — if the finding reappears, it transitions to **regressed**

### CLI Usage

```bash
# Assign a finding to a team member (delegation status auto-set to "assigned")
hb findings assign <finding-id> --assignee <member-id>

# Update delegation progress
hb findings assign <finding-id> --delegation-status in_progress    # developer is working on it
hb findings assign <finding-id> --delegation-status verified       # fix confirmed

# View findings with their assignment and delegation status
hb findings
hb findings --status open          # filter by finding status (open/fixed/stale/regressed)
hb findings --severity critical    # filter by severity
```

### Webhook Notifications

Delegation events trigger webhooks — route them to Slack, email, or your ticketing system:

| Event | When |
|---|---|
| `finding.assigned` | Finding assigned to a team member |
| `finding.acknowledged` | Assignee acknowledged the assignment |
| `finding.resolution_verified` | Security lead verified the fix |

```bash
hb webhooks create --url https://slack.example.com/webhook \
  --events finding.assigned,finding.resolution_verified
```

### Integration with Continuous Monitoring

Delegation connects to the monitoring lifecycle:

1. **ASCAM cycle runs** → new findings detected or existing findings regressed
2. **Security lead reviews** → assigns critical/high findings to developers
3. **Developer fixes** → marks as in_progress
4. **Next ASCAM cycle** → finding not reproduced → status transitions to fixed
5. **Security lead verifies** → marks as verified

If a fixed finding reappears in a later cycle, it automatically transitions to **regressed** with elevated posture penalty (1.2x vs 1.0x for open) — the team is immediately alerted that a previous fix was lost.

## Organization Structure

Humanbound follows a simple hierarchy:

```
Organization
├── Members (with roles)
├── Projects (one per AI agent)
│   ├── Experiments (test runs)
│   ├── Findings (persistent, cross-experiment)
│   ├── Posture (score + history)
│   └── Monitoring (ASCAM campaigns)
├── Providers (LLM configurations)
├── API Keys
└── Webhooks
```

- One **organization** per company or team
- One **project** per AI agent
- **Members** have org-wide roles but can access all projects in the org
- **Findings** are scoped to a project but assigned to org members

```bash
# Organization management
hb orgs list
hb orgs current
hb switch <org-id>
```

!!! note "Platform feature"
    Team management and finding delegation require a Humanbound account. Local testing is single-user — no team features needed.
