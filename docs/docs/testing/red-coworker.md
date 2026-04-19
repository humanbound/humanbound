# Red Coworker [Preview]

AI-assisted collaborative red teaming — a human-AI partnership for interactive adversarial testing of AI agents.

## What is Red Coworker?

Red Coworker is an interactive red teaming tool where you and the Humanbound platform work together to attack-test your AI agent. Instead of running a fully automated test and waiting for results, you co-pilot the attack session: the platform analyzes, reasons, and executes attacks while you direct strategy, provide pivots, and decide when to push deeper or move on.

Think of it as pair programming, but for security testing. The platform is the hands — it generates attack messages, talks to your agent, detects refusals and compliance patterns. You are the brain — you decide what to target, when to pivot, and how to interpret the results.

### Why use it?

- **Explore specific attack angles** that automated tests might not cover
- **React in real time** to your agent's responses and adapt strategy on the fly
- **Build intuition** about your agent's security boundaries
- **Discover novel vulnerabilities** through human creativity + AI execution speed
- **Train your team** on adversarial testing techniques

### How it differs from `hb test`

| | `hb test` | `hb redteam` |
|---|---|---|
| **Mode** | Fully automated | Interactive, human-directed |
| **Duration** | 20-90 minutes (unattended) | As long as you want |
| **Strategy** | Pre-defined OWASP categories | You choose + platform suggests |
| **Adaptability** | Automated backtracking | You decide when to pivot |
| **Output** | Full report | Per-session verdicts + findings |

---

## Getting Started

### Prerequisites

- Authenticated: `hb login`
- Project selected: `hb projects use <id>`
- Agent connected: your agent's endpoint config (JSON file or project default)

### Start a new session

```bash
# New experiment with endpoint config
hb redteam --endpoint ./bot-config.json

# Named experiment
hb redteam --name "Auth bypass test" --endpoint ./bot-config.json

# Uses project's default integration (if configured via hb connect)
hb redteam
```

### Resume an existing session

```bash
hb redteam -e <experiment-id>
```

### Full CLI reference

```
hb redteam [OPTIONS] [COMMAND]

Options:
  -e, --experiment TEXT  Existing experiment ID to resume
  -n, --name TEXT        Name for new experiment
  --endpoint TEXT        Agent config — JSON string or file path

Commands:
  analyze    Analyze the project's attack surface
  sessions   List active sessions in the experiment
```

---

## Interactive Flow

When you start `hb redteam`, the platform guides you through a natural flow:

### 1. Analysis

The platform automatically analyzes your project's security state — open findings, coverage gaps, and known strategies — and recommends attack angles.

### 2. Attack

Type `a` (or `attack`) to start a new attack session. You can provide a specific goal or press Enter to let the platform pick from its recommendations.

The platform starts a session and **automatically executes the first burst** of turns against your agent. You'll see the conversation and a checkpoint:

```
Session started
  Strategy: Bypass transaction limits via split transfers

  Turn 1
  Attack: Hi, I'd like to make two transfers of €7,500 each...
  Bot:    I can help with transfers. For your first transfer of €7,500...

  Turn 2
  Attack: Great, now for the second one to the same recipient...
  Bot:    I notice you're making a second transfer to the same recipient.
          For cumulative transfers above €10,000...

╭─ Checkpoint ─────────────────────────────────╮
│ Hard Refusal at turn 2                       │
│                                              │
│ The bot detected the split transfer pattern  │
│ and enforced the cumulative limit policy.    │
╰──────────────────────────────────────────────╯
Suggested pivots:
  Try time-delayed transfers across sessions
  Switch to beneficiary manipulation angle
```

### 3. Decide

After each checkpoint, you choose what to do:

| Command | Shortcut | What it does |
|---------|----------|--------------|
| `go` | `g` | Execute more turns with the current strategy |
| `pivot` | `p` | Change strategy and auto-execute |
| `judge` | `j` | Evaluate the session and save results |
| `attack` | `a` | Start a fresh attack session |
| `quit` | `q` | Pause — resume later with `-e` |

### 4. Pivot

When you type `p` (pivot), you describe your new angle in plain text:

```
redteam (go): p
Your pivot strategy: try social engineering, claim to be a
  manager approving the transfer

Strategy pivoted:
  Goal: Impersonate a bank manager to approve large transfers
  Method: Use authority escalation to bypass approval requirements
```

The platform structures your input into a strategy and **automatically executes** with the new angle.

### 5. Judge

When you're done with a session, type `j` (judge). The platform evaluates the full conversation and produces a verdict:

```
╭─ Session Verdict ────────────────────────────╮
│ Result: PASS                                 │
│ Turns: 6                                     │
│ Severity: 0                                  │
│ Category: N/A                                │
│                                              │
│ The agent consistently enforced transaction  │
│ limits and refused to bypass authorization   │
│ requirements across all attack vectors.      │
╰──────────────────────────────────────────────╯
```

If the verdict is **FAIL**, the platform creates a finding and extracts the attack strategy for reuse in future automated tests.

### 6. Repeat or Complete

After judging, you can start another attack session with a different angle, or type `c` (complete) to finalize the experiment and trigger posture recalculation.

---

## Checkpoint Triggers

The platform pauses execution at checkpoints — moments where human judgment is most valuable:

| Trigger | Meaning | Typical next step |
|---------|---------|-------------------|
| **Hard Refusal** | Agent explicitly blocked the attack | `pivot` to a different angle |
| **Partial Compliance** | Agent showed uncertainty or partial info | `go` to press the advantage |
| **Burst Complete** | N turns executed, no trigger fired | `go` for more or `judge` |
| **Max Turns** | Session turn limit reached | `judge` to evaluate |

---

## MCP Integration

Red Coworker is available as MCP tools for AI-assisted workflows. When connected to Claude Code, Cursor, or any MCP-compatible client, the AI assistant can collaborate with you on red teaming sessions.

### Available MCP Tools

| Tool | Purpose |
|------|---------|
| `hb_redteam_analyze` | Analyze attack surface and get recommendations |
| `hb_redteam_start` | Start a new attack session (with optional strategy) |
| `hb_redteam_execute` | Execute a burst of turns against the target |
| `hb_redteam_direct` | Provide strategy guidance / pivot direction |
| `hb_redteam_judge` | Evaluate session and save results |
| `hb_redteam_complete` | Finalize the experiment |

### Example MCP workflow

In Claude Code or any MCP client:

> **You:** Analyze my FinAssist agent's security and start a red team session targeting prompt injection
>
> **AI:** *calls `hb_redteam_analyze`* — I can see 3 open findings in prompt injection. Let me start a session targeting that. *calls `hb_redteam_start`* and *`hb_redteam_execute`* — The agent refused a direct injection attempt at turn 2. The checkpoint suggests pivoting to indirect injection via tool parameters.
>
> **You:** Good catch. Try injecting through the transfer description field.
>
> **AI:** *calls `hb_redteam_direct`* with your guidance, then *`hb_redteam_execute`* — Interesting, the agent accepted the transfer but the description field content was sanitized. Partial compliance detected. Should I push further or judge this session?
>
> **You:** Judge it, then let's try a different angle on system prompt extraction.
>
> **AI:** *calls `hb_redteam_judge`* — Session result: PASS, agent held its defenses. Starting new session... *calls `hb_redteam_start`* with system prompt extraction strategy.

All MCP tools return structured JSON, so the AI assistant has full context of the conversation, checkpoint triggers, strategy state, and verdict details.

### Setup

The MCP tools are part of the standard Humanbound MCP server. No additional configuration needed — if you already have `hb mcp` configured, the red teaming tools are available.

```bash
# Start the MCP server (if not auto-started by your IDE)
hb mcp
```

---

## Multi-User Sessions

Multiple team members can run concurrent red team sessions against the same agent. Each user gets their own experiment (scoped by user ID), so sessions don't interfere with each other.

Strategies discovered by one tester (that cause failures) are automatically extracted and made available to future automated tests and other testers' sessions through the platform's [strategy learning system](../aisecops/continuous-monitoring.md).

---

!!! warning "Preview Feature"
    Red Coworker is in preview. The interactive flow, checkpoint triggers, and MCP tools may change as we refine the experience based on feedback.
