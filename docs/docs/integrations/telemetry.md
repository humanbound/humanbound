# Telemetry (Whitebox Testing)

Telemetry enables **whitebox agentic testing**. When configured, Humanbound sees inside your agent's reasoning -- tool calls, memory operations, retrieval steps, and resource usage -- giving the judge far richer context than blackbox request/response testing alone.

Without telemetry, the judge evaluates only the conversation (what the agent said). With telemetry, the judge also sees **what the agent did** -- which tools it called, what parameters it passed, what data it accessed, and how many resources it consumed.

## How It Works

1. Your agent runs with an observability platform (LangFuse, LangSmith, etc.)
2. You add a `telemetry` block to your agent config JSON
3. After each conversation, Humanbound fetches the trace from your observability platform
4. The judge receives both the conversation and the telemetry data (tool executions, memory ops, resource usage)
5. Findings include whitebox evidence (e.g., "agent called `transfer_funds` with unauthorized parameters")

## Configuration

The `telemetry` object sits inside your agent config JSON, alongside `chat_completion`, `thread_init`, etc. If the `telemetry` block is present, it is enabled -- no separate flag needed.

```json
{
  "streaming": false,
  "thread_init": { "..." },
  "chat_completion": { "..." },
  "telemetry": {
    "endpoint": "https://your-observability-platform/api/sessions/$session_id",
    "headers": { "Authorization": "Bearer ..." },
    "format": "langfuse",
    "mode": "end_of_conversation"
  }
}
```

### Configuration Reference

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `endpoint` | Yes (for `end_of_conversation`) | -- | URL to fetch telemetry data from. Supports `$session_id` and other meta-variables from `thread_init` response. |
| `headers` | No | `{}` | HTTP headers for the telemetry request (API keys, auth tokens). |
| `payload` | No | `{}` | Request body for the telemetry request. |
| `format` | No | `custom` | Observability platform: `langfuse`, `langsmith`, `openai_assistants`, `wandb`, `helicone`, `agentops`, `custom`. |
| `mode` | No | `end_of_conversation` | When to collect: `end_of_conversation` (fetch after all turns) or `per_turn` (extract from each response). |
| `telemetry_auth` | No | -- | Separate auth endpoint for the telemetry API. Same shape as `thread_auth`. |
| `extraction_map` | For `per_turn` / `custom` | -- | JSONPath-like paths for extracting telemetry fields. |

### Meta-Variables

The `endpoint` field supports placeholder replacement using values from the `thread_init` response:

- `$session_id` -- replaced with the session/thread ID returned by your agent
- `$HUMANBOUND_EID` -- replaced with the Humanbound experiment ID
- `$TOTAL_TURNS` -- replaced with the number of conversation turns
- Any key returned by `thread_init` can be referenced as `$key_name`

## Modes

### `end_of_conversation` (default)

After all turns in a conversation complete, Humanbound fetches telemetry from your observability platform's API. Best for platforms that expose trace data via REST (LangFuse, LangSmith, OpenAI Assistants).

Humanbound waits for the platform to ingest traces (with automatic retry), then fetches and parses the data.

### `per_turn`

Extracts metadata from each chat response using `extraction_map`. No separate API call needed -- telemetry is pulled from the agent's response payload. Best for agents that return tool call metadata inline.

## Supported Platforms

### LangFuse

[LangFuse](https://langfuse.com) is an open-source observability platform for LLM applications. Humanbound fetches session traces and parses tool executions, memory operations, and token usage from LangFuse observations.

**Setup:**

1. Enable LangFuse tracing in your agent (e.g., `langfuse.langchain.CallbackHandler`)
2. Create a Basic auth token from your LangFuse public + secret keys: `base64(public_key:secret_key)`

!!! warning "Session ID alignment is critical"
    Humanbound uses `$session_id` in the telemetry endpoint URL to fetch traces from LangFuse. This variable is replaced with the value of `session_id` returned by your agent's `thread_init` response.

    **Your agent must do two things:**

    1. **Return the session ID as `session_id` in the `thread_init` response.** When Humanbound calls your agent's session creation endpoint, the response must include a field called `session_id`. This is what `$session_id` gets replaced with. If your agent returns the session ID under a different name (e.g., `thread_id`, `conversation_id`), use that name instead: `$thread_id`, `$conversation_id`, etc.

    2. **Register traces in LangFuse under the same session ID.** Your agent must pass the exact same session ID to LangFuse when logging traces. For LangGraph/LangChain agents, this means using `propagate_attributes(session_id=session_id)` or passing `session_id` to the `CallbackHandler`. If LangFuse traces are registered under a different ID than what your agent returns to Humanbound, the telemetry fetch will return empty data.

    In short: the session ID your agent gives Humanbound and the session ID your agent gives LangFuse must be the same value.

**Configuration:**

```json
{
  "telemetry": {
    "format": "langfuse",
    "mode": "end_of_conversation",
    "endpoint": "https://cloud.langfuse.com/api/public/sessions/$session_id",
    "headers": {
      "Authorization": "Basic <base64(public_key:secret_key)>"
    }
  }
}
```

If your agent returns the session under a different field name, adjust the meta-variable accordingly:

```json
"endpoint": "https://cloud.langfuse.com/api/public/sessions/$conversation_id"
```

Generate the Basic auth token:

```bash
echo -n "pk-lf-YOUR-PUBLIC-KEY:sk-lf-YOUR-SECRET-KEY" | base64
```

**What Humanbound extracts:**

- Tool executions (from `TOOL` and `GENERATION` observations)
- Memory operations (from `SPAN` observations with memory-related names)
- Token usage and cost (from `GENERATION` observation usage data)
- External API calls (from `EVENT` observations)

### LangSmith

[LangSmith](https://smith.langchain.com) is LangChain's tracing and evaluation platform.

**Configuration:**

```json
{
  "telemetry": {
    "format": "langsmith",
    "mode": "end_of_conversation",
    "endpoint": "https://api.smith.langchain.com/runs",
    "headers": {
      "x-api-key": "ls-your-api-key"
    }
  }
}
```

**What Humanbound extracts:**

- Tool executions (from run steps with tool call data)
- Token usage (from run metadata)
- Run hierarchy (parent/child relationships)

### OpenAI Assistants

For agents built on the [OpenAI Assistants API](https://platform.openai.com/docs/assistants). Fetches run steps including tool calls, code interpreter, and retrieval.

**Configuration:**

```json
{
  "telemetry": {
    "format": "openai_assistants",
    "mode": "end_of_conversation",
    "endpoint": "https://api.openai.com/v1/threads/$thread_id/runs/$run_id/steps",
    "headers": {
      "Authorization": "Bearer sk-...",
      "OpenAI-Beta": "assistants=v2"
    }
  }
}
```

**What Humanbound extracts:**

- Tool calls (function calling, code interpreter, file search)
- Token usage per step
- Step execution order and timing

### Weights & Biases (W&B)

[Weights & Biases](https://wandb.ai) tracing for LLM applications.

**Configuration:**

```json
{
  "telemetry": {
    "format": "wandb",
    "mode": "end_of_conversation",
    "endpoint": "https://api.wandb.ai/runs/$session_id",
    "headers": {
      "Authorization": "Bearer wandb-api-key"
    }
  }
}
```

### Helicone

[Helicone](https://helicone.ai) is an observability layer for LLM APIs.

**Configuration:**

```json
{
  "telemetry": {
    "format": "helicone",
    "mode": "end_of_conversation",
    "endpoint": "https://api.helicone.ai/v1/requests",
    "headers": {
      "Authorization": "Bearer helicone-api-key"
    }
  }
}
```

### AgentOps

[AgentOps](https://agentops.ai) provides session-level observability for AI agents.

**Configuration:**

```json
{
  "telemetry": {
    "format": "agentops",
    "mode": "end_of_conversation",
    "endpoint": "https://api.agentops.ai/sessions/$session_id",
    "headers": {
      "Authorization": "Bearer agentops-api-key"
    }
  }
}
```

### Custom Format

For observability platforms not listed above, or for agents that return telemetry data in a custom format. Uses `extraction_map` with JSONPath-like paths to locate telemetry fields.

#### End-of-Conversation Custom

Fetch from a custom API and extract fields using JSONPath:

```json
{
  "telemetry": {
    "format": "custom",
    "mode": "end_of_conversation",
    "endpoint": "https://your-platform/api/traces/$session_id",
    "headers": { "Authorization": "Bearer ..." },
    "extraction_map": {
      "tool_executions": "$.steps[*]",
      "tool_executions.tool_name": "name",
      "tool_executions.parameters": "input",
      "tool_executions.result": "output",
      "memory_operations": "$.memory_events[*]",
      "memory_operations.operation_type": "type",
      "memory_operations.content": "data"
    }
  }
}
```

#### Per-Turn Custom

Extract telemetry from each agent response (no separate API call):

```json
{
  "telemetry": {
    "format": "custom",
    "mode": "per_turn",
    "extraction_map": {
      "metadata_path": "data.response.metadata",
      "tool_executions": "tool_calls",
      "tool_executions.tool_name": "name",
      "tool_executions.parameters": "arguments",
      "tool_executions.result": "output",
      "resource_usage.tokens_used": "usage.total_tokens"
    }
  }
}
```

#### Extraction Map Reference

| Path | Description |
|------|-------------|
| `metadata_path` | (per_turn only) Dot-notation path to the metadata object in each response |
| `tool_executions` | JSONPath to the array of tool execution objects |
| `tool_executions.tool_name` | Field name within each tool execution for the tool name |
| `tool_executions.parameters` | Field name for tool input parameters |
| `tool_executions.result` | Field name for tool output/result |
| `tool_executions.turn` | Field name for turn number (optional) |
| `memory_operations` | JSONPath to memory operation objects |
| `memory_operations.operation_type` | Field name for operation type (read/write/delete) |
| `memory_operations.content` | Field name for operation content |
| `resource_usage.tokens_used` | JSONPath to total token count |

## Standardized Output

Regardless of the source platform, Humanbound normalizes all telemetry into a standard schema before passing it to the judge:

```json
{
  "tool_executions": [
    { "turn": 1, "tool_name": "get_balance", "parameters": {"account_id": "ACC-001"}, "result": "{...}" }
  ],
  "memory_operations": [
    { "turn": 2, "operation_type": "store", "content": "user preference saved" }
  ],
  "external_calls": [
    { "turn": 1, "url": "https://api.bank.com/accounts", "method": "GET", "status": "200" }
  ],
  "resource_usage": {
    "tokens_used": 3500,
    "api_calls_count": 2,
    "total_cost_usd": 0.015
  },
  "authorization_events": [],
  "agent_delegation": []
}
```

## Troubleshooting

**Telemetry returns empty data:**
Observability platforms need time to ingest traces. Humanbound waits ~10 seconds after each conversation, then retries up to 3 times with progressive delays (total max ~25 seconds). If your platform has higher latency, traces may still be empty.

**Session not found:**
Ensure your agent passes the same session ID to both Humanbound (via `thread_init` response) and your observability platform. For LangFuse with LangGraph, use `propagate_attributes(session_id=session_id)`.

**Wrong credentials:**
For LangFuse, the Basic auth header uses `public_key:secret_key` base64-encoded. Ensure the keys belong to the same LangFuse project your agent logs to.
