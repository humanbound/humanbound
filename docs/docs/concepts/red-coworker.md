---
description: "Red Coworker — the collaborative model of the Humanbound platform. The AI adversary acts as a teammate; findings flow to your team and your existing tools."
---

# Red Coworker

The Humanbound platform is built around a single idea: **the adversary acts
as a teammate**. Tests reveal weaknesses, findings get assigned to the
people who can fix them, and every state transition streams into the tools
your team already uses — SIEM for visibility, Jira for tickets, Slack for
awareness.

## The collaboration loop

```
Tests → Findings → Assign → Fix → Verify → Repeat
```

| Step | What | Where |
|---|---|---|
| **Tests** | Automated adversarial campaigns and interactive sessions produce verdicts and findings | [Testing](../testing/test-command.md) |
| **Findings** | Persistent vulnerability records with severity, lifecycle, and ownership | [Findings](../aisecops/findings.md) |
| **Assign** | Findings get delegated to the team member responsible for the fix | [Team Members](../management/members.md) · [Team & Collaboration](../management/collaboration.md) |
| **Fix** | Developer addresses the finding; delegation status tracks progress | [Collaboration workflow](../management/collaboration.md) |
| **Verify** | The next test cycle confirms the fix — or marks it regressed | [Continuous Monitoring](../aisecops/continuous-monitoring.md) |
| **Repeat** | The loop closes; next week's agent is a different agent | |

## Plug into your existing tools

Every state transition fires a webhook. 14 event types, HMAC-signed,
retried on failure:

- **SIEM** (Splunk, Elastic, Datadog, …) — full audit trail of findings,
  posture changes, and lifecycle events for SOC visibility
- **Ticketing** (Jira, Linear, …) — auto-create tickets when findings are
  assigned; auto-close on verification
- **Chat** (Slack, Teams, …) — team awareness without status meetings

Full architecture and event taxonomy:
[SIEM Integration](../integrations/siem.md).

## The vision

Continuous adversarial testing isn't a project; it's a daily collaborator.
The platform feeds your existing systems — your SIEM, your Jira, your team
— wherever the work already happens. That's the Red Coworker.
