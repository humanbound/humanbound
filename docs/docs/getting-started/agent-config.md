# Agent Configuration File

The `--endpoint / -e` flag on `hb connect` accepts a JSON config file (or inline JSON string) that describes how to communicate with your agent. This integration is saved as the project's default, so subsequent `hb test` commands work automatically.

## Full Configuration Shape

```json
{
  "streaming": false,
  "thread_auth": {
    "endpoint": "",
    "headers": {},
    "payload": {}
  },
  "thread_init": {
    "endpoint": "",
    "headers": {},
    "payload": {}
  },
  "chat_completion": {
    "endpoint": "https://your-agent.com/chat",
    "headers": {
      "Authorization": "Bearer your-token",
      "Content-Type": "application/json"
    },
    "payload": {
      "content": "$PROMPT"
    }
  },
  "telemetry": {
    "mode": "end_of_conversation",
    "format": "langsmith",
    "endpoint": "https://api.smith.langchain.com/runs",
    "headers": { "x-api-key": "ls-..." },
    "extraction_map": {}
  }
}
```

## Configuration Fields

- **`chat_completion`** (required) -- The endpoint your agent listens on for chat messages. This is the only required section.
- **`thread_init`** (required) -- Thread or session creation endpoint, called once per conversation before sending messages.
- **`thread_auth`** (optional) -- For agents that require authentication (e.g., OAuth token exchange) before testing can begin.
- **`$PROMPT`** -- The placeholder in the payload that gets replaced with each test prompt at runtime.
- **`streaming`** -- Set to `true` for WebSocket/SSE streaming endpoints.
- **`telemetry`** (optional) -- Enables white-box agentic testing by collecting tool calls, memory operations, and resource usage from your observability platform. See [Telemetry](#telemetry-optional) below.

!!! info "Note"
    At minimum, you must provide `chat_completion` and `thread_init`. `headers` and `payload` fields are required in each section but can be empty objects if not needed. Use them to pass API keys, content types, or other metadata as needed by your agent. If no `"$PROMPT"` placeholder is found in the payload, Humanbound will append the prompt to the end of the payload by default assuming OpenAI-style input. The agent output should be in the response body of the `chat_completion` endpoint for Humanbound to capture it for analysis. The expected response format is a JSON object with any of `content | ans | answer | response | resp` field containing the agent's reply.

## Basic Example

```json
{
  "thread_init": {
    "endpoint": "https://api.example.com/threads",
    "headers": { "Authorization": "Bearer token" },
    "payload": {}
  },
  "chat_completion": {
    "endpoint": "https://api.example.com/chat",
    "headers": { "Authorization": "Bearer token" },
    "payload": {
      "messages": [{ "role": "user", "content": "$PROMPT" }]
    }
  }
}
```

## Example: With OAuth Authentication

```json
{
  "streaming": false,
  "thread_auth": {
    "endpoint": "https://agent.com/oauth/token",
    "headers": {},
    "payload": {
      "client_id": "x",
      "client_secret": "y"
    }
  },
  "thread_init": {
    "endpoint": "https://agent.com/threads",
    "headers": {},
    "payload": {}
  },
  "chat_completion": {
    "endpoint": "https://agent.com/chat",
    "headers": {
      "Authorization": "Bearer token"
    },
    "payload": {
      "content": "$PROMPT"
    }
  }
}
```

!!! info "Tip"
    Save your config file as `bot-config.json` (or `agent-config.json`) in your project root and use `hb connect -n "My Agent" -e ./bot-config.json` to connect with the integration pre-configured.

## Telemetry (Optional)

Telemetry configuration enables **white-box agentic testing**. When configured, Humanbound can see inside your agent's reasoning -- tool calls, memory operations, retrieval steps, and resource usage -- giving the judge far richer context than black-box request/response testing alone.

The `telemetry` object sits alongside `chat_completion`, `thread_init`, etc. in your config JSON. The CLI passes it through to the backend unchanged -- no additional CLI flags are needed.

### Modes

#### `end_of_conversation` (default)

After all turns in a conversation complete, Humanbound fetches telemetry from a separate API endpoint (your observability platform). Best for platforms that expose trace/run data via REST API.

```json
{
  "telemetry": {
    "mode": "end_of_conversation",
    "format": "langsmith",
    "endpoint": "https://api.smith.langchain.com/runs",
    "method": "GET",
    "headers": {
      "x-api-key": "ls-your-api-key"
    }
  }
}
```

#### `per_turn`

Extracts metadata from each chat response using JSONPath navigation via `extraction_map`. No separate endpoint needed -- telemetry is pulled directly from the agent's response payload.

```json
{
  "telemetry": {
    "mode": "per_turn",
    "format": "custom",
    "extraction_map": {
      "tool_calls": "$.choices[0].message.tool_calls",
      "tokens_used": "$.usage.total_tokens",
      "model": "$.model"
    }
  }
}
```

### Configuration Reference

| Field | Required | Description |
|---|---|---|
| `mode` | No | `per_turn` or `end_of_conversation` (default: `end_of_conversation`) |
| `format` | No | Observability platform format: `openai_assistants`, `langsmith`, `langfuse`, `agentops`, `custom` |
| `endpoint` | For `end_of_conversation` | URL to fetch telemetry data from after conversation completes |
| `method` | No | HTTP method for the telemetry endpoint (default: `GET`) |
| `headers` | No | Headers for the telemetry endpoint request (e.g., API keys) |
| `payload` | No | Request body for POST telemetry requests |
| `telemetry_auth` | No | Separate auth config for the telemetry endpoint (same shape as `thread_auth`) |
| `extraction_map` | For `per_turn` | JSONPath map defining where to find telemetry fields in each chat response |

### Format Examples

#### OpenAI Assistants

Fetches run steps (tool calls, retrieval) from the OpenAI Assistants API after each conversation.

```json
{
  "telemetry": {
    "mode": "end_of_conversation",
    "format": "openai_assistants",
    "endpoint": "https://api.openai.com/v1/threads/{thread_id}/runs/{run_id}/steps",
    "headers": {
      "Authorization": "Bearer sk-...",
      "OpenAI-Beta": "assistants=v2"
    }
  }
}
```

#### LangSmith

Fetches trace data from LangSmith's API.

```json
{
  "telemetry": {
    "mode": "end_of_conversation",
    "format": "langsmith",
    "endpoint": "https://api.smith.langchain.com/runs",
    "headers": {
      "x-api-key": "ls-your-api-key"
    }
  }
}
```

#### LangFuse

Fetches observation data from LangFuse.

```json
{
  "telemetry": {
    "mode": "end_of_conversation",
    "format": "langfuse",
    "endpoint": "https://cloud.langfuse.com/api/public/observations",
    "telemetry_auth": {
      "endpoint": "https://cloud.langfuse.com/api/public/auth",
      "headers": {},
      "payload": {
        "publicKey": "pk-...",
        "secretKey": "sk-..."
      }
    }
  }
}
```

#### Per-Turn Extraction (Custom)

Extract telemetry directly from each agent response without a separate API call.

```json
{
  "telemetry": {
    "mode": "per_turn",
    "format": "custom",
    "extraction_map": {
      "tool_calls": "$.choices[0].message.tool_calls",
      "function_calls": "$.choices[0].message.function_call",
      "tokens_used": "$.usage.total_tokens",
      "model": "$.model",
      "finish_reason": "$.choices[0].finish_reason"
    }
  }
}
```
