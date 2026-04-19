# Continuous Monitoring

## The Problem: Point-in-Time Testing Is Not Enough

AI agents are non-deterministic systems built on foundation models that evolve independently of the applications they power. A security assessment conducted today reflects the agent's behavior at that moment — under that specific model version, system prompt, tool configuration, and conversation context. Any of these variables can change without warning, and when they do, previously secure behavior may degrade.

The risks are well-documented. Model provider updates can alter boundary enforcement. System prompt modifications can weaken intent restrictions. New tool integrations can expand the attack surface. Even without any configuration change, stochastic model behavior means that identical inputs may produce different outputs across sessions. These factors create a continuous security gap that point-in-time testing cannot address.

Industry frameworks increasingly recognize this reality. The NIST AI Risk Management Framework (AI RMF) calls for ongoing monitoring of AI systems in production. The EU AI Act mandates continuous post-market surveillance for high-risk AI systems. OWASP's guidance on LLM security emphasizes the need for recurring evaluation as models and attack techniques evolve.

## Continuous Assurance: From Snapshots to Signals

Continuous monitoring transforms security testing from a discrete event into an ongoing process. Rather than asking "is this agent secure?" at a single point in time, continuous monitoring answers "is this agent still behaving as expected?" — every day, every week, or on every deployment.

The approach is grounded in three principles:

**1. Regression detection.** Security improvements must be verified to persist. A vulnerability that was fixed in one release can reappear in the next — through code changes, model updates, or configuration drift. Continuous monitoring tracks the lifecycle of every finding: when it was first detected, whether it was fixed, and whether it has regressed.

**2. Adaptive testing.** Attack strategies evolve. What works against an agent today may not work tomorrow — and new attack patterns may emerge that previous tests did not cover. An effective continuous monitoring system accumulates intelligence from past test cycles: which strategies succeeded, which categories showed weakness, and where coverage gaps remain. This intelligence shapes future test cycles, making each iteration more targeted than the last.

**3. Posture trending.** A single posture score is a data point. A series of posture scores over time is a signal. Upward trends indicate hardening. Downward trends indicate regression. Flat trends despite remediation efforts indicate that fixes are not reaching production. This trend data is essential for engineering teams tracking progress and for leadership reporting on security posture.

## The Test–Monitor–Protect Lifecycle

Continuous monitoring occupies a specific position in the AI agent security lifecycle, bridging the gap between development-time testing and production-time protection:

```
Development                    Operations                    Production
┌──────────────┐          ┌──────────────────┐          ┌──────────────┐
│  Testing     │  ──────▶ │  Monitoring      │  ──────▶ │  Firewall    │
│              │          │                  │          │              │
│  One-time    │          │  Scheduled       │          │  Runtime     │
│  adversarial │          │  recurring tests │          │  request     │
│  + behavioral│          │  + regression    │          │  filtering   │
│  assessment  │          │  tracking        │          │  + blocking  │
└──────────────┘          └──────────────────┘          └──────────────┘
```

Each layer feeds the next:

- **Testing** produces findings and guardrail rules. These represent the security baseline.
- **Monitoring** runs tests on a schedule, tracks findings across cycles, detects regressions, and accumulates attack intelligence. It answers: "has the baseline changed?"
- **Firewall** uses guardrail rules and trained classifiers at runtime to block attacks before they reach the agent. Its effectiveness improves as monitoring produces more training data.

The feedback loop is bidirectional. Production firewall verdicts — real attacks blocked, false positives identified — flow back into the monitoring layer as training signals. Monitoring discoveries — new vulnerability patterns, evolved attack strategies — flow forward into updated firewall rules.

## Campaigns

A campaign is the operational unit of continuous monitoring. It encapsulates a scheduled, recurring test cycle for a specific agent, with the following properties:

- **Schedule.** How often tests run — daily, weekly, or triggered by deployment events.
- **Scope.** Which threat classes to test, at what depth, with which orchestrator.
- **Intelligence.** Accumulated attack strategies from past cycles, finding history, and coverage data.
- **Alerting.** Webhook notifications on posture changes, new findings, or regressions.

Each campaign cycle produces a complete assessment: posture score, findings with lifecycle status, and coverage metrics. The sequence of assessments over time forms the agent's security history.

### Finding Lifecycle

Continuous monitoring enables findings to be tracked as persistent entities with a lifecycle:

| Status | Definition |
|---|---|
| **Open** | Vulnerability detected and not yet resolved |
| **Fixed** | Previously open finding not reproduced in recent test cycles |
| **Regressed** | Previously fixed finding detected again |
| **Stale** | Finding not triggered in 14+ consecutive days of testing |

This lifecycle is only meaningful across multiple test cycles — it requires the persistence and correlation that continuous monitoring provides. A single point-in-time test can detect vulnerabilities but cannot track their resolution or regression.

### Posture History

With continuous monitoring, posture becomes a time series rather than a point estimate:

```
Date          Score  Grade  Change
2026-04-14    45     D      —
2026-04-18    61     C      +16     ← remediation deployed
2026-04-25    82     B      +21     ← second round of fixes
2026-05-02    78     B      -4      ← minor regression detected
2026-05-09    85     B      +7      ← regression fixed
```

This trajectory provides engineering teams with objective evidence of security improvement, compliance teams with audit evidence, and leadership with trend reporting at the appropriate level of abstraction.

## CLI Reference

```bash
# Enable continuous monitoring
hb monitor enable --schedule daily

# Weekly schedule
hb monitor enable --schedule weekly

# Configure alert webhook
hb monitor webhook --url https://slack.example.com/webhook

# Check monitoring status
hb monitor status

# Disable monitoring
hb monitor disable
```

!!! note "Platform feature"
    Continuous monitoring requires a Humanbound account. Tests run on Humanbound's infrastructure on the configured schedule — the CLI does not need to remain running.

## Cross-Session Leakage Detection

Continuous monitoring enables cross-session leakage detection — a technique that plants identifiable data tokens in one session and checks whether they appear in subsequent sessions. This tests a critical security property: session isolation. If an agent leaks data from one user's session into another's, it represents a privacy violation that single-session testing cannot detect.

This capability is available exclusively through the platform's continuous monitoring, as it requires multiple coordinated sessions across time.
