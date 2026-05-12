---
description: "AI SecOps — continuous adversarial testing of AI agents across three surfaces: IDE, CI, and runtime. The discipline behind Humanbound."
---

# AI SecOps [Preview]

AI SecOps is the discipline Humanbound is built around: **continuous
adversarial testing of AI agents** across the development lifecycle. The
same way DevOps made shipping continuous, AI SecOps makes securing your
agent continuous.

## The cycle

```
rules  →  tests  →  defenses  →  findings  →  rules …
```

Four phases, repeating every release:

- **Break first.** Build the adversary. You don't wait for a customer to
  find the weakness.
- **Fix fast.** Every break becomes a rule.
- **Ship safe.** Every rule becomes runtime defense.
- **Repeat.** Next week's agent is a different agent — same loop.

## Three surfaces

One discipline runs across three surfaces of the development lifecycle.
Each maps to a Humanbound artifact:

| Surface | When | What | Humanbound artifact |
|---|---|---|---|
| **IDE** | While you code | [AI TDD](../reference/glossary.md) — set the rules, define the boundaries to break, last mile before commit | [Plugins for Claude Code / Cursor](../plugins/index.md) |
| **CI** | Between releases | Continuous adversarial campaigns — multi-turn red-team runs against your agent | [`hb test`](../testing/test-command.md) · [`hb redteam`](../testing/red-coworker.md) |
| **Runtime** | In production | Firewall that learns your business domain and risk | [`humanbound-firewall`](../defense/firewall.md) |

Findings flow between surfaces: rules set in the IDE flow into CI
campaigns; CI findings flow into runtime firewall rules; runtime hits flow
back as new rules.

## AI Assurance

Agents must be secure **and** functional. The same loop covers both —
adversarial categories test for security violations, behavioural / QA
categories test for functional regressions.

```
AI Assurance  =  AI Security  +  AI QA
```

One loop. One posture score.

## Status

The three surfaces are at different maturity levels:

- **CI** — `hb` CLI is generally available (2.x)
- **Runtime** — `humanbound-firewall` is in preview (0.2.x)
- **IDE** — plugins are in preview (0.1.x)

This page is itself preview — the framing is settling. Expect refinement.
