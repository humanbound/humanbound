---
description: "Define the JSON endpoint config Humanbound uses to talk to your agent — HTTP/WS, headers, payload templating, streaming, response extraction."
---

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
    "format": "langfuse",
    "mode": "end_of_conversation",
    "endpoint": "https://cloud.langfuse.com/api/public/sessions/$session_id",
    "headers": { "Authorization": "Basic <base64(pk:sk)>" }
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

The `telemetry` block enables **whitebox agentic testing**. When present, Humanbound fetches tool calls, memory operations, and resource usage from your observability platform after each conversation, giving the judge visibility into what the agent *did* -- not just what it *said*.

If the `telemetry` block is present, it is enabled. No separate flag needed.

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

Supported platforms: **LangFuse**, **LangSmith**, **OpenAI Assistants**, **Weights & Biases**, **Helicone**, **AgentOps**, and **Custom** (via `extraction_map`).

For full configuration details, vendor-specific examples, and the custom extraction map reference, see the [Telemetry Integration Guide](../integrations/telemetry.md).
