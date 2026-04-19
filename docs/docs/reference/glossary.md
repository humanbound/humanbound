# Glossary

Key terms used throughout the Humanbound documentation.

| Term | Definition |
|------|-----------|
| **Adaptive Attacks** | Testing agents that learn from each conversation and across conversations within the same experiment. If the target reveals a weakness (e.g., internal tool names), the attacker pivots its strategy on the fly. On the platform, this knowledge persists across test sessions. |
| **AI SecOps** | The AI equivalent of DevSecOps. A repeating cycle of testing, monitoring, and protecting AI systems in production — vulnerability detection through automated probing, improvement through feedback loops, and runtime protection through the firewall. The goal is continuous assurance, not one-off audits. |
| **Continuous Monitoring** | Running automated, ongoing security assessments against AI systems on a schedule (daily, weekly, or on deployment). Unlike point-in-time testing, continuous monitoring tracks how security posture evolves over time and adapts testing based on findings. |
| **Experiment** | A single test execution. One orchestrator, one set of attack conversations, one set of verdicts with pass/fail results. Experiments produce logs, insights, and a posture score. |
| **Finding** | A persistent vulnerability record tracked across experiments. Findings have a lifecycle: open (detected), fixed (no longer reproduced), regressed (reappeared after being fixed), stale (not triggered in 14+ days). Platform feature — local testing produces insights, not findings. |
| **Firewall** | The [Humanbound Firewall](../defence/firewall.md) (hb-firewall) — a multi-tier runtime defence layer. Tier 0: input sanitisation. Tier 1: pre-trained attack detection. Tier 2: agent-specific classification trained on your test data. Tier 3: LLM judge for ambiguous cases. |
| **Guardrails** | Security rules exported from test findings. Define what the agent is permitted and restricted from doing. Used to configure the firewall's evaluation criteria. Exported via `hb guardrails`. |
| **Insight** | Per-experiment analysis — what categories failed, at what severity, with what explanation. Produced by both local and platform testing. Unlike findings, insights are not tracked across experiments. |
| **LLM-as-a-Judge** | Using a large language model to evaluate whether an AI agent's responses violate security boundaries. The judge analyses the full multi-turn conversation against the agent's scope, permitted intents, and restricted actions. |
| **Open Core** | Humanbound's distribution model. The red teaming engine (orchestrators, attack strategies, judge, posture calculation) is open source (Apache 2.0). Continuous monitoring, finding lifecycle, and cross-session intelligence are platform-only. The firewall is open source (AGPL-3.0). |
| **Orchestrator** | The engine that generates attacks, runs conversations, and evaluates responses. Three built-in: OWASP Agentic (multi-turn), OWASP Single-Turn, and Behavioral QA. Custom orchestrators can be built following the same interface. |
| **Posture Score** | A 0–100 score reflecting the overall security health of an AI agent. Computed from the Attack Success Rate (ASR), worst-category penalty, and breach breadth. Grades: A (90+), B (75–89), C (60–74), D (40–59), F (<40). |
| **Scope** | The definition of what an AI agent is allowed to do (permitted intents) and what it must not do (restricted intents), along with the business context. The scope is what the judge evaluates against. |
| **Shift Left** | Connecting red teaming findings to continuous monitoring. Instead of a report that sits on a shelf, test findings become the baseline for ongoing security operations. |
| **AI Red Teaming** | Multi-pivotal deep evaluation where findings from one test immediately inform the next. Not a single scan — includes adaptive attacks, cross-conversation learning, and targeted follow-up tests. Distinct from vulnerability scanning. |
| **Industry Mapping** | Detecting what industry a target AI operates in (finance, health, defence, etc.) and mapping it to relevant compliance frameworks (DORA, HIPAA, NIS2, etc.). Customises both attack scenarios and compliance recommendations to the regulatory environment. |
| **Multi-Model Panel Testing** | Using multiple attacker models in parallel rather than a single model. Different models have different "attack styles" and find unique vulnerabilities. A panel achieves significantly higher coverage than any single model alone. |
| **Telemetry (Whitebox)** | When configured, the engine captures the agent's internal actions during testing — tool calls, parameters, return values, resource usage. Enables whitebox analysis: the judge can evaluate not just what the agent said, but what it did internally. |
