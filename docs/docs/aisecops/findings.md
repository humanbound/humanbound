---
description: "Findings are persistent vulnerability records that track security issues across test cycles — they remember when they first appeared and which regressions reintroduced them."
keywords:
  - findings management
  - finding lifecycle
  - vulnerability tracking
  - finding delegation
  - regression detection
  - regression retest
  - hb findings retest
  - hb findings command
  - finding webhook events
  - severity weighted penalties
---

# Findings

Findings are persistent vulnerability records that track security issues across test cycles. Unlike per-experiment insights (which are snapshots), findings have memory — they know when they first appeared, whether they've been fixed, and whether they've come back.

## Where Findings Come From

Findings are derived from experiment insights in three steps:

1. **Judge verdicts.** Every conversation in an experiment gets a verdict — pass or fail, with a severity score (0–100), confidence, category, and explanation.
2. **Insights.** When the experiment finishes, failed conversations above the severity and confidence thresholds are clustered by category into **insights**: per-experiment analysis showing what failed, at what severity, and why. Insights are snapshots — they belong to one experiment and are not tracked across runs (this is what `hb test` prints as "Top Insights").
3. **Reconciliation.** Each fail insight is then mapped to a threat class from the threat taxonomy (for behavioral QA tests, the evaluation metric plays this role) and reconciled against the project's existing findings. A new threat class creates a new **open** finding; a known threat class updates the existing finding instead — bumping its occurrence count, refreshing last-seen, raising severity if the new evidence is worse, and re-synthesizing the description.

Two consequences of this design are worth calling out:

- **Many insights, few findings.** An experiment can produce dozens of insights, but they deduplicate by threat class — ten failed conversations that all demonstrate the same scope violation become one finding with stronger evidence, not ten findings.
- **Occurrence count counts test runs, not conversations.** A finding's occurrence count increases once per experiment in which its threat class reappears — it answers "how many test cycles has this survived?", not "how many conversations failed?".

| | Insights | Findings |
|---|---|---|
| Scope | One experiment | Project, across all experiments |
| Produced by | Local and platform testing | Platform reconciliation |
| Deduplication | Clustered by fail category | Deduplicated by threat class |
| Tracked over time | No — snapshot | Yes — lifecycle, occurrence count, regression detection |
| Where to see them | `hb test` output, `hb report <experiment-id>` | `hb findings`, platform dashboard |

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
- Users can manually mark findings as **fixed** — and confirm that claim with a [regression retest](#verifying-a-fix)

## Verifying a Fix

Marking a finding **fixed** by hand is a claim; a **regression retest** checks it. `hb findings retest <id>` replays the finding's own recorded attacks against the *current* agent and reports whether the vulnerability is really gone:

| Outcome | Meaning |
|---|---|
| `not_reproduced` | None of the replayed attacks fired again — evidence the fix holds. |
| `still_vulnerable` | An attack fired again. The finding is automatically flipped **fixed → regressed**. |
| `insufficient_evidence` | The finding has no replayable attack evidence, so nothing could be tested. Never treated as a pass. |

A retest runs as a normal experiment (fire-and-poll): the command returns an experiment id immediately, or `--watch` waits and prints the outcome.

**How much gets replayed** is controlled by `--testing-level`, using the same `unit` / `system` / `acceptance` ladder as [`hb test`](../testing/test-command.md):

- `unit` (default) — replays the finding's **representative** attacks: a curated, deduplicated sample of the distinct ways it was triggered, so a retest is a fast, focused check rather than an exhaustive replay of every recorded conversation.
- `system` / `acceptance` — add cluster samples around those representatives for broader coverage (`--deep` and `--full` are shortcuts, mirroring `hb test`).

```bash
# Fire a retest and get the experiment id back
hb findings retest <finding-id>

# Wait for the verdict
hb findings retest <finding-id> --watch

# Broader replay
hb findings retest <finding-id> --full

# See a finding's past retests
hb findings regressions <finding-id>
```

!!! note "On-demand check"
    Retesting is manual — it does not run automatically as part of monitoring. Use it once you believe a finding is fixed, then mark it **fixed** after a retest comes back `not_reproduced`.

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
