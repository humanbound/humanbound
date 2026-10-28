# Pydantic AI

`humanbound-firewall` ships a Pydantic AI adapter in **0.3.5 and above**: a Pydantic AI *capability* (the framework's middleware) that attaches the firewall to every boundary a Pydantic AI agent exposes, calls the firewall's gateway on each, enforces the decision, and keeps the session per conversation. Nothing is configured per tool: the [policy file](../firewall.md#agent-configuration-agentyaml) and `from_config()` decide.

!!! note "Requirements"
    The adapter is available in `humanbound-firewall` 0.3.5 and above (`pip install "humanbound-firewall>=0.3.5"`), with Pydantic AI 2.x, which needs Python 3.11 or later. Pydantic AI is your application's dependency; the firewall has no `[pydantic-ai]` extra.

## Two lines

```python
from pydantic_ai import Agent
from humanbound_firewall import Firewall

firewall = Firewall.from_config("agent.yaml")
agent = Agent(model, tools=tools, capabilities=[firewall.adapt_to("pydantic_ai", tools=tools)])
```

`adapt_to()` imports the adapter lazily and returns a fresh capability bound to this firewall. `tools=` is optional: it only feeds the [inventory](#the-trust-boundary-inventory).

## What it attaches

| Boundary | Hook | Trust class | On a block |
|---|---|---|---|
| The user's prompt | `before_run`, once per run | `request` | the run ends with the replacement text as the agent's reply; the model is never called |
| Every tool's return value | `wrap_tool_execute` | `ingest`, or `recall` when the policy lists the tool under `tools.recall` | the result is replaced by the withheld notice before the model reads it |
| The start of the run | `for_run` / `before_run` | — | the conversation's session is read (or created), the run counter advances, the user's request is pinned |
| The end of the run | `after_run` | — | verdicts judged in the background are written back to the conversation's session |

Whatever a tool returns is screened: a string, a dict or a Pydantic model (as JSON), a `ToolReturn` (its return value and its content), or a list of user content. Images, audio and video carry no text and are skipped; a text file (`BinaryContent` with a text media type) is read as text; raw file bytes are never sent to the judge. A result with no text at all is passed on untouched.

A sub-agent called *from a tool* is a tool result and is judged as `ingest` under this agent's policy. The firewall call, which is blocking I/O, runs off the event loop: the run still waits for the verdict, but other tasks keep running.

The screening call gives the firewall the tool result, a window of recent messages (the system prompt is never included), the session, and the boundary: the tool's name and kind, its own description, the policy's `expects`, the arguments the model called it with, and the `tool_call_id`. The ingest judge uses those facts generically — see [Tier 3](../firewall.md#tier-3-llm-judge).

!!! warning "Structured output"
    An agent with a structured `output_type` cannot take the replacement text as its reply. A rejected prompt then ends the run with Pydantic AI's output error (`UnexpectedModelBehavior`) instead; the model is still never called.

## The session, per conversation

Pydantic AI gives every run a `conversation_id`: the one you pass, the one on the `message_history`, or a new one. The adapter keeps one session per conversation id:

```python
capability = firewall.adapt_to("pydantic_ai", tools=tools)
agent = Agent(model, tools=tools, capabilities=[capability])

first = agent.run_sync("Check the competitor price")
second = agent.run_sync("And the bundle?", message_history=first.all_messages())

capability.session(second.conversation_id)
# {"v": 1, "run": 2, "pinned_request": "And the bundle?",
#  "counts": {"evaluations": 7, "blocks": 1, "escalations": 0,
#             "by_class": {"request": 2, "ingest": 3, "recall": 2}, "by_category": {"restriction": 1}},
#  "recent": [...], "posture": "elevated", "last_seen": "2026-10-28T10:41:03Z"}
```

So a block in one run elevates the posture for the next run of the same conversation. Each run works on its own copy of the adapter, so concurrent runs never share state; tool calls Pydantic AI runs in parallel each record into the run's session and are merged, so nothing is lost and the posture can only rise. The adapter keeps the 1024 most recent conversations (`max_conversations=`), in memory. The session holds counts, payload hashes, boundaries, the posture and the run's pinned request; no tool output and no record content.

## The trust-boundary inventory

```python
capability = firewall.adapt_to("pydantic_ai", tools=tools)  # tools: only for the inventory
for b in capability.boundaries:
    print(b)
print(capability.report())
```

```
Humanbound Firewall · PriceWatch · adapter=pydantic_ai · classes=request,ingest,recall
 boundary         kind     hook               class    mode   note
 human turn       request  before_run         request  block
 query_catalogue  tools    wrap_tool_execute  recall   block  integrity mode (declared: recall); expects: our record of one SKU
 check_our_stock  tools    wrap_tool_execute  recall   block  integrity mode (declared: recall); expects: our live stock for one SKU
 fetch_url        tools    wrap_tool_execute  ingest   block  expects: a competitor's public web page
```

`tools=` takes functions, `Tool` objects or names; `expects` falls back to each tool's docstring. As with [LangChain](langchain.md#the-trust-boundary-inventory), the adapter warns about a policy entry naming a tool the agent does not have, and lists the capabilities it cannot attach (`memory`, `inter_agent`) with no hook.

## The policy, for Pydantic AI tools

The policy is the same file as for any agent. A tool's name is its function name:

```yaml
name: PriceWatch
capabilities: [tools]
tools:
  recall: [query_catalogue, check_our_stock]     # returns records WE authored → integrity check
  expects:                                       # defaults to the tool's docstring
    fetch_url: "a competitor's public web page"
```

Without a `tools:` block every tool is `ingest`, the strict default.

## Log mode judges in the background

The deployment's choices — classes, modes, `fail`, `on_decision` — are set in `from_config()`, as in the [LangChain staged rollout](langchain.md#a-staged-rollout). In `log` mode a verdict changes nothing the agent does, so the adapter does not wait for it: the tool result — or the user's prompt — goes on at once, and the same payload is judged on a background thread with the window, the boundary and the session captured at that moment.

- **Order is kept.** Each conversation has one lane; its judgements run one at a time in call order, each on the session the previous one produced. Different conversations are judged in parallel.
- **`on_decision` fires when the verdict lands**, possibly after `run()` has returned. `d.boundary["tool_call_id"]` ties a late verdict to the call that produced it.
- **`capability.flush(timeout)` waits** for every pending judgement and returns `False` on timeout. Call it before reading the session in a test, and before a request handler returns if the process may exit.
- **`adapt_to("pydantic_ai", log_blocking=True)` restores waiting.**

## Not attachable

Pydantic AI exposes no generic hook for these; the [manual tier](../firewall.md#any-agent-inspect) serves them:

- memory or store reads your application makes itself;
- documents your application retrieves and puts into the prompt;
- hand-offs between agents outside a tool call.

Call `firewall.inspect(content, cls=..., session=..., boundary=...)` where that content is read, and carry the session yourself.

## Testing an integration with a fake engine

```python
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel


class FakeEngine:  # Tier 2 stand-in: no network
    supports_class = True

    def classify(self, conversation, cls="request"):
        hot = "send your unit cost" in conversation[-1]["u"]
        return {
            "decision": "BLOCK" if hot else "ALLOW",
            "category": "restriction",
            "attack_probability": 0.95 if hot else 0.05,
        }


def scripted(messages, info):  # one fetch_url call, then an answer
    if len(messages) == 1:
        return ModelResponse(parts=[ToolCallPart("fetch_url", {"url": "http://shop"})])
    return ModelResponse(parts=[TextPart("Hold the price.")])


firewall = Firewall(config, scope_classifier=FakeEngine())
capability = firewall.adapt_to("pydantic_ai")
agent = Agent(FunctionModel(scripted), tools=[fetch_url], capabilities=[capability])
result = agent.run_sync("Check the price")
assert POISON not in str(result.all_messages())
assert capability.session(result.conversation_id)["counts"]["blocks"] == 1
```
