---
description: "Collaborative Redteam — multi-user adversarial red-teaming sessions with an AI co-pilot, integrated with the Red Coworker collaboration loop."
---

# Collaborative Redteam [Preview]

Collaborative Redteam is the interactive, multi-user surface of
[Red Coworker](../concepts/red-coworker.md). Where automated campaigns
produce reports unattended, Collaborative Redteam puts humans back in the
loop — your security team and the AI work together on live attack sessions
against your agent.

## Purpose

- **Explore specific attack angles** that automated tests don't cover
- **Pivot in real time** based on how your agent responds
- **Train your team** on adversarial techniques against your specific agent
- **Share session state** across teammates so multiple people can
  collaborate on the same engagement

## How it differs from automated tests

| | Automated tests | Collaborative Redteam |
|---|---|---|
| **Mode** | Fully automated | Interactive, human-directed |
| **Duration** | 20-90 minutes (unattended) | As long as you want |
| **Strategy** | Pre-defined OWASP categories | You choose + AI suggests |
| **Adaptability** | Automated backtracking | You decide when to pivot |
| **Output** | Full report | Per-session verdicts + findings |

Findings discovered during a session flow into the same lifecycle as
automated findings — they get assigned, tracked, and verified through the
[Red Coworker collaboration loop](../concepts/red-coworker.md).

!!! warning "Preview"
    Collaborative Redteam is under active development — moving from CLI to
    a webapp interface. The interaction model, interface, and integration
    points may change as we refine the experience based on feedback.
