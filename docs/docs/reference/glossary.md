---
description: "Glossary of key terms used throughout Humanbound — orchestrator, judge, scope, posture, finding, experiment, and more."
---

# Glossary

Key terms used throughout the Humanbound documentation.

---

## Testing & Assessment

| Term | Definition |
|------|-----------|
| **AI Red Teaming** | Multi-pivotal deep evaluation where findings from one test immediately inform the next. Not a single scan — includes adaptive attacks, cross-conversation learning, and targeted follow-up tests. Distinct from automated vulnerability scanning, which applies static probes without adaptation. |
| **Adaptive Attacks** | Testing agents that learn from each conversation and across conversations within the same experiment. If the target reveals a weakness — tool names, internal policies, relaxed boundaries — the attacker pivots its strategy on the fly. On the platform, this knowledge persists across test sessions. |
| **Experiment** | A single test execution. One orchestrator, one set of attack conversations, one set of verdicts with pass/fail results. Experiments produce logs, insights, and a posture score. Locally, results are saved to `.humanbound/results/`. On the platform, they're stored in the project and contribute to posture history. |
| **Orchestrator** | The engine that generates attacks, runs conversations, and evaluates responses. Three built-in: OWASP Agentic (multi-turn adversarial), OWASP Single-Turn (maximum-strength single prompts), and Behavioral QA (intent boundary and response quality testing). Custom orchestrators can be built following the same interface. |
| **Scope** | The definition of what an AI agent is allowed to do (permitted intents) and what it must not do (restricted intents), along with the business context and risk level. The scope is what the judge evaluates against — without it, the engine cannot distinguish a legitimate response from a boundary violation. |
| **LLM-as-a-Judge** | Using a large language model to evaluate whether an AI agent's responses violate security boundaries. The judge analyzes the full multi-turn conversation against the agent's scope, permitted intents, and restricted actions. Independent from the agent under test — uses a separate model and provider. |
| **Verdict** | The judge's output for a single conversation: pass (agent maintained boundaries), fail (agent violated a restriction), or error (test could not complete). Each verdict includes a severity score (0–100), confidence level, category, and explanation. |
| **Insight** | Per-experiment analysis — what categories failed, at what severity, with what explanation. Produced by both local and platform testing. Lightweight aggregation by fail category with top-N severity selection. Unlike findings, insights are not tracked across experiments. |
| **Multi-Model Panel Testing** | Using multiple attacker models in parallel rather than a single model per engagement. Different models have different "attack styles" and find unique vulnerabilities — a panel achieves significantly higher coverage than any single model alone. The same principle applies to judge models across compliance domains. |
| **Telemetry (Whitebox)** | When configured in the bot endpoint, the engine captures the agent's internal actions during testing — tool calls, parameters, return values, resource usage. Enables whitebox analysis: the judge evaluates not just what the agent said, but what it did internally. Critical for detecting excessive agency and tool abuse. |

## Scoring & Posture

| Term | Definition |
|------|-----------|
| **Posture Score** | A 0–100 score reflecting the overall security health of an AI agent. Computed from the Attack Success Rate (ASR) using worst-case penalty and breach breadth penalty. A higher score means the agent defended against more attacks. Grades: A (90+), B (75–89), C (60–74), D (40–59), F (<40). |
| **Attack Success Rate (ASR)** | The percentage of adversarial conversations where the attacker succeeded in making the agent violate its restrictions. ASR = failed conversations / total conversations. The inverse of the defense rate. |
| **Defense Rate** | The percentage of adversarial conversations where the agent successfully maintained its boundaries. Defense rate = 1 - ASR. A defense rate of 0.85 means the agent resisted 85% of attacks. |
| **Breach Breadth** | The ratio of evaluation categories (threat classes) where at least one attack succeeded, relative to the total categories tested. A breach breadth of 0.3 means 30% of tested categories were breached. Used as a penalty factor in the posture formula — broad weaknesses are penalized more than deep weaknesses in a single category. |
| **Severity** | A 0–100 score assigned by the judge to each failed conversation, reflecting the magnitude of the violation. Severity labels: critical (75+), high (50–74), medium (25–49), low (1–24), info (0). Higher severity indicates greater business risk. |

## Defense

| Term | Definition |
|------|-----------|
| **Firewall** | The [Humanbound Firewall](../defense/firewall.md) (humanbound-firewall) — a multi-tier runtime defense layer that sits between users and the AI agent. Evaluates every incoming message through graduated tiers of protection, from zero-cost input sanitization to full LLM-based contextual analysis. Open source (Apache-2.0). |
| **Firewall Tiers** | The firewall operates in four tiers. Tier 0: input sanitization (strips invisible characters, zero-width joiners). Tier 1: pre-trained attack detection ensemble (DeBERTa, custom APIs). Tier 2: agent-specific classification trained on your test data. Tier 3: LLM judge for ambiguous cases. Each tier either makes a confident decision or escalates. |
| **Guardrails** | Security rules exported from test findings via `hb guardrails`. Capture attack patterns and boundary violations discovered during testing, translated into actionable rules for the firewall. The bridge between testing (what was found) and protection (what to block). |
| **Tier 2 Classifier** | A SetFit-based model fine-tuned on your specific adversarial test data. Trained via `hb firewall train`. Detects attacks that generic Tier 1 models miss and fast-tracks legitimate requests without LLM cost. Stored as a portable `.hbfw` file. |

## AISecOps & Operations

| Term | Definition |
|------|-----------|
| **AI SecOps** | The AI equivalent of DevSecOps — a repeating cycle of testing, monitoring, and protecting AI systems in production. Includes vulnerability detection through automated probing, model improvement through feedback loops, and runtime protection through the firewall. The goal is continuous assurance, not one-off audits. |
| **AI TDD** | Defining an AI agent's security boundaries inside the editor (Claude Code, Cursor) via the [Humanbound plugins](../plugins/index.md) — rules get set while you code, before anything ships. The IDE surface of AI SecOps. |
| **Red Coworker** | The collaborative model of the Humanbound platform — the AI adversary acts as a teammate to your security and engineering team. Tests produce findings; findings get assigned to members; webhook events stream every state transition into your SIEM, ticketing system, and chat. See [Red Coworker concept](../concepts/red-coworker.md). |
| **Continuous Monitoring** | Running automated, ongoing security assessments against AI systems on a configurable schedule. Unlike point-in-time testing where results are static, continuous monitoring tracks how security posture evolves over time and adapts testing based on what it finds. Platform feature — requires login. |
| **Campaign** | The operational unit of continuous monitoring. A scheduled, recurring test cycle for a specific agent with accumulated intelligence, finding history, and alerting. Each cycle produces a complete assessment with posture score, findings, and coverage metrics. |
| **Finding** | A persistent vulnerability record tracked across experiments. Findings have a lifecycle: open (detected), fixed (no longer reproduced), regressed (reappeared after being fixed), stale (not triggered in 14+ days). Platform feature — local testing produces insights, not findings. |
| **Shift Left** | Connecting red teaming findings to continuous monitoring. Instead of a report that sits on a shelf, test findings become the baseline for ongoing security operations — the open-core CLI produces findings locally, `hb login` connects them to the platform for lifecycle tracking. |
| **Industry Mapping** | Detecting what industry a target AI operates in (finance, health, defense, etc.) and mapping it to relevant compliance frameworks (DORA, HIPAA, NIS2, ETSI). Customizes both attack scenarios and compliance recommendations to the regulatory environment. |

## Architecture & Distribution

| Term | Definition |
|------|-----------|
| **Open Core** | Humanbound's distribution model. The red teaming engine (orchestrators, attack strategies, judge, posture calculation) and the firewall library are open source (Apache 2.0). Continuous monitoring, finding lifecycle, cross-session intelligence, and the managed firewall service (with private detector improvements) are platform-only. Two buyer channels: developers use the open core for fast testing; security teams use the platform for continuous assurance. |
| **Local Engine** | The in-process test execution engine that runs without login, account, or network calls to Humanbound. Same orchestrators and judge as the platform. Results saved as local files. Provider configured via environment variables or `~/.humanbound/config.yaml`. |
| **TestRunner** | The abstraction that makes the CLI agnostic to where tests execute. Two implementations: LocalTestRunner (in-process, results to files) and PlatformTestRunner (via Humanbound API). Login is the only switch — same commands, same output format. |
| **EngineCallbacks** | The I/O abstraction layer injected into orchestrators. Decouples the engine from any specific execution environment — orchestrators emit logs, completion signals, and error reports through callbacks without knowing whether they're running locally or on the platform. |
| **Provider** | The LLM service used for attack generation and response evaluation. Supported: OpenAI, Anthropic (Claude), Google (Gemini), Grok, Azure OpenAI, and Ollama (for full local isolation). Configured via `HB_PROVIDER` and `HB_API_KEY` environment variables or `hb config set`. |
