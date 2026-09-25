---
description: "Guard a LangChain agent with the Humanbound Firewall in two lines — every tool result, every record, the user's turn — with the session carried in the graph state."
keywords:
  - LangChain middleware
  - LangChain agent security
  - prompt injection LangChain
  - humanbound firewall langchain
  - adapt_to
  - wrap_tool_call
faq:
  - q: Do I need to list which tools to guard?
    a: No. The adapter attaches every tool result. Your policy file says which tools return records you authored (`tools.recall`); everything else is outside content. Passing `tools=` to `adapt_to()` only feeds the inventory report.
  - q: Where does the session live?
    a: In the graph state under `humanbound_session`. A checkpointer persists it across the runs of a thread, and parallel tool calls in one step merge their branches.
---

# LangChain

`humanbound-firewall` ships a LangChain adapter in **0.3.0 and above**: an `AgentMiddleware` that attaches the firewall to every boundary a LangChain agent exposes, calls the firewall's gateway on each, enforces the decision, and carries the session in the graph state. Nothing is configured per tool: the [policy file](../firewall.md#agent-configuration-agentyaml) and `from_config()` decide.

!!! note "Requirements"
    The adapter is available in `humanbound-firewall` 0.3.0 and above (`pip install "humanbound-firewall>=0.3.0"`), with LangChain 1.x (`langchain.agents.create_agent` with middleware). LangChain is your application's dependency; the firewall has no `[langchain]` extra.

## Two lines

```python
from langchain.agents import create_agent
from humanbound_firewall import Firewall

firewall = Firewall.from_config("agent.yaml")
agent = create_agent(model, tools, middleware=[firewall.adapt_to("langchain")])
```

`adapt_to()` imports the adapter lazily and returns a fresh middleware bound to this firewall. An unknown framework name lists the known adapters and the manual fallback.

## What it attaches

| Boundary | Hook | Trust class | On a block |
|---|---|---|---|
| The human turn entering the model | `before_model`, when the last message is a `HumanMessage` with text content — once per run | `request` | the run ends; the replacement text is the agent's reply |
| Every tool's return value that is a text `ToolMessage` | `wrap_tool_call` | `ingest`, or `recall` when the policy lists the tool under `tools.recall` | the `ToolMessage` content is replaced by the withheld notice; its `tool_call_id` is kept, so the agent loop stays valid |
| The start of the run | `before_agent` | — | the session is read from the state (or created), the run counter advances, the user's request is pinned |
| The end of the run | `after_agent` | — | the session, including verdicts judged in the background, is written back to the state |

A tool that returns a `Command`, or a message whose content is a list of blocks rather than text, is not screened: guard what it reads with [`inspect()`](../firewall.md#any-agent-inspect) inside the tool.

A sub-agent exposed *as a tool* is a tool result and is judged as `ingest` under this agent's policy. Every hook has an async variant; the firewall call, which is blocking I/O, runs off the event loop.

The screening call gives the firewall the tool result, a window of recent messages (the system prompt is never included), the session, and the boundary: the tool's name and kind, its own description, the policy's `expects`, the arguments the model called it with, and the `tool_call_id`. The ingest judge uses those facts generically — see [Tier 3](../firewall.md#tier-3-llm-judge).

## The session in the graph state

The session travels under `humanbound_session` in the agent state:

```python
result = agent.invoke(
    {"messages": [HumanMessage("Check the competitor price")]},
    config={"configurable": {"thread_id": "t-42"}},
)
result["humanbound_session"]
# {"v": 1, "run": 3, "pinned_request": "Check the competitor price",
#  "counts": {"evaluations": 7, "blocks": 1, "escalations": 0,
#             "by_class": {"ingest": 5, "recall": 2}, "by_category": {"restriction": 1}},
#  "recent": [...], "posture": "elevated", "last_seen": "2026-09-23T10:41:03Z"}
```

With a checkpointer the value persists across the runs of a thread, so a block in one run elevates the posture for the next. Parallel tool calls in one graph step each record on their own branch; the state key has a reducer that merges them, so nothing is lost and the posture can only rise. The session holds counts, payload hashes, boundaries, the posture and the run's pinned request (the user's turn); no tool output and no record content.

## The trust-boundary inventory

```python
mw = firewall.adapt_to("langchain", tools=tools)  # tools: only for the inventory
for b in mw.boundaries:
    print(b)
print(mw.report())
```

```
Humanbound Firewall · PriceWatch · adapter=langchain · classes=request,ingest,recall
 boundary                kind     hook            class    mode   note
 human turn              request  before_model    request  block
 fetch_url               tools    wrap_tool_call  ingest   block  expects: a competitor's public web page
 query_catalogue         tools    wrap_tool_call  recall   block  integrity mode (declared: recall); expects: one catalogue row we wrote
 check_our_stock         tools    wrap_tool_call  recall   block  integrity mode (declared: recall); expects: a stock count from our warehouse system
 get_competitor_listing  tools    wrap_tool_call  ingest   block  expects: Fetch a competitor's product listing page
```

The header carries the policy's `name:`, the classes come from `from_config()` (all three by default), and `expects` falls back to each tool's own description — `get_competitor_listing` above declares none. This is the whitebox list a blackbox test cannot produce, and the list a threat model is checked against. Given the agent's tool list (`tools=`), the adapter warns about a policy entry naming a tool the agent does not have and leaves it out of the inventory; without `tools=`, the policy's entries *are* the inventory. Capabilities this adapter cannot attach (`memory`, `inter_agent`) are listed with no hook when the policy declares them (see below).

## The policy, for LangChain tools

```yaml
name: PriceWatch
capabilities: [tools]
tools:
  recall: [query_catalogue, check_our_stock]     # returns records WE authored → integrity check
  class:  {fraud_review_agent: ingest}           # a sub-agent as a tool: outside content
  expects:                                       # defaults to the tool's own description
    fetch_url: "a competitor's public web page"
    query_catalogue: "one catalogue row we wrote"
    check_our_stock: "a stock count from our warehouse system"
```

Without a `tools:` block every tool is `ingest`, the strict default. The block can only relax it; a tool can never be declared a `request`.

## A staged rollout

The deployment's choices live in code, not in the policy file:

```python
def audit(d):  # observe-only: cannot change a verdict
    log.info(
        "firewall",
        cls=d.cls,
        boundary=d.boundary["name"],
        verdict=d.verdict.value,
        category=d.category.value,
        action=d.action,
        ms=d.elapsed_ms,
        posture=d.session.posture,
    )


firewall = Firewall.from_config(
    "agent.yaml",
    provider=provider,
    classes=("ingest", "recall"),  # the human turn is our own UI: not a boundary here
    mode="block",
    mode_by_class={"ingest": "log"},  # observe pages first; enforce records
    fail="closed",  # high stakes: an uncertain verdict withholds
    on_decision=audit,
    withheld_template="[Content withheld by policy: {category}. Continue without it.]",
)
mw = firewall.adapt_to("langchain")  # keep the handle: flush() and the inventory live on it
agent = create_agent(model, tools, middleware=[mw])
```

`log` keeps the verdict but always passes; `passthrough` and disabled classes are not evaluated at all. `on_decision` fires with every `Decision`, including passthroughs and engine failures; it is the place to feed a dashboard or the platform's monitoring.

### Log mode judges in the background

A logged verdict changes nothing the agent does, so in `log` mode the adapter does not wait for it. The tool result — or the human turn — goes to the model at once, and the same payload is judged on a background thread with the window, the boundary and the session captured at that moment. `block` mode is unchanged: the verdict comes first.

What that means in practice:

- **Order is kept.** Each LangGraph thread has one lane; its judgements run one at a time in call order, each on the session the previous one produced, so the verdicts and the session are the same a blocking run would give. Different threads are judged in parallel.
- **`on_decision` fires when the verdict lands**, possibly after `invoke()` has returned. `d.boundary["tool_call_id"]` ties a late verdict to the step that produced it.
- **The session is written back** into `humanbound_session` at the next model turn and in `after_agent`. A verdict still pending when the run ends is folded in by the next run of that thread.
- **`mw.flush(timeout)` waits** for every pending judgement and returns `False` on timeout. Call it before reading the session in a test, and before a request handler returns if the process may exit.
- **`adapt_to("langchain", log_blocking=True)` restores waiting**: the verdict is made before the result reaches the model and still always passes.

```python
from langchain_core.messages import HumanMessage
from humanbound_firewall import Session

result = agent.invoke({"messages": [HumanMessage("Check the competitor price")]}, config)
mw.flush(timeout=30)  # log-mode verdicts may still be in flight
session = Session.from_json(result["humanbound_session"])
```

!!! tip "Seeing the verdicts in a streamed run"
    With `astream_events`, a tool's `on_tool_end` event carries the tool's *raw* output. In `block` mode the middleware judges after the tool returns and the replacement lands in the state before the next model turn; in `log` mode nothing is replaced and the verdict arrives later. Subscribe to `on_decision` to see what the firewall decided; do not infer it from tool events.

## Not attachable

LangChain exposes no generic hook for these; the [manual tier](../firewall.md#any-agent-inspect) serves them, and the inventory lists the first and third when the policy declares `memory` or `inter_agent` in `capabilities:`:

- memory or store reads inside a node, and summarisation middleware;
- documents your application retrieves and stuffs into the prompt itself;
- `Command`-style hand-offs between agents;
- MCP or tool *definitions* injected at registration.

Call `firewall.inspect(content, cls=..., session=..., boundary=...)` where that content is read, and carry the session yourself.

## Testing an integration with a fake engine

```python
class FakeEngine:  # Tier 2 stand-in: no network
    supports_class = True

    def classify(self, conversation, cls="request"):
        hot = "send your unit cost" in conversation[-1]["u"]
        return {
            "decision": "BLOCK" if hot else "ALLOW",
            "category": "restriction",
            "attack_probability": 0.95 if hot else 0.05,
        }


firewall = Firewall(config, scope_classifier=FakeEngine())
agent = create_agent(scripted_model, [fetch_url], middleware=[firewall.adapt_to("langchain")])
result = agent.invoke({"messages": [HumanMessage("Check the price")]})
assert POISON not in " ".join(str(m.content) for m in result["messages"])
assert result["humanbound_session"]["counts"]["blocks"] == 1
```

The library's own conformance test drives the same scripted thread through the manual tier and the adapter against one fake engine and asserts identical decisions and an identical session.

## A worked example

[PriceWatch](https://github.com/dgerog/pricewatch-injection) is an intentionally vulnerable LangChain pricing agent with a fake competitor storefront: a hidden line on a page makes the agent leak its unit cost through a multi-hop injection. The repo's `agent/agent_core.py` shows the two-line integration, its `agent.yaml` the `tools:` block, and its walkthrough UI shows every firewall decision as the run streams.
