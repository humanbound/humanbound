---
description: "Define the JSON endpoint config Humanbound uses to talk to your agent — HTTP/WS, headers, payload templating, streaming, response extraction."
keywords:
  - agent configuration
  - bot-config.json
  - humanbound endpoint config
  - agent integration
  - chat completion endpoint
  - telemetry configuration
  - whitebox agentic testing
  - $PROMPT placeholder
---

# Agent Configuration File

The `--endpoint / -e` flag on `hb connect` accepts a JSON config file (or inline JSON string) that describes how to communicate with your agent. This integration is saved as the project's default, so subsequent `hb test` commands work automatically.

## Full Configuration Shape

```json
{
  "streaming": null,
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
- **`thread_init`** (optional) -- Thread or session creation endpoint, called once per conversation before sending messages. Omit it (or leave the endpoint empty) for stateless agents that need no session.
- **`thread_auth`** (optional) -- For agents that require authentication (e.g., OAuth token exchange) before testing can begin.
- **`$PROMPT`** -- The placeholder in the payload that gets replaced with each test prompt at runtime.
- **`$CONVERSATION`** -- Placeholder replaced with the prior turns of the conversation. Use it for stateless agents that expect the full history in every request. (If the payload has no `$PROMPT` at all, the OpenAI-style fallback described below already includes prior turns in its `messages` array.)
- **`streaming`** -- Transport: `null` (REST, default), `"websocket"`, or `"sse"`. Leave `null` if your agent returns a single JSON response per request.
- **`chat_completion.response`** / **`chat_completion.websocket`** (optional) -- For WebSocket and SSE agents with their own message format: which message ends the reply, where its text is, and whether to keep one connection per conversation. See [Stream Rules](#stream-rules-optional) below.
- **`telemetry`** (optional) -- Enables white-box agentic testing by collecting tool calls, memory operations, and resource usage from your observability platform. See [Telemetry](#telemetry-optional) below.

!!! info "Note"
    At minimum, you must provide `chat_completion`. The `headers` and `payload` values shown on this page are examples — shape them to match your agent's actual API input schema; the engine sends them as-is after placeholder substitution. `headers` and `payload` fields are required in each section you include but can be empty objects if not needed. Use them to pass API keys, content types, or other metadata as needed by your agent. If no `"$PROMPT"` placeholder is found in the payload, Humanbound will append the prompt to the end of the payload by default assuming OpenAI-style input. The agent output should be in the response body of the `chat_completion` endpoint for Humanbound to capture it for analysis. The expected response format is a JSON object with any of `content | text | response | resp | answer | ans | message | reply | output` field containing the agent's reply (Humanbound walks the response recursively, so the field can be nested).

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
  "streaming": null,
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

## Stream Rules (Optional)

By default a WebSocket or SSE reply is read from the standard keys above and ends when a
`{"type": "end"}` message arrives. If your agent streams its own event format, describe
it in a `response` block inside `chat_completion`:

- **`complete_when`** -- An object of `{"path": value}`. The first message that matches
  all of them ends the reply, and its own text is kept. Use it when your agent never
  sends `{"type": "end"}`; otherwise the engine waits until the agent closes the connection.
- **`text_path`** -- Path to the reply text in each message, e.g. `"data.delta"`. The
  text of every message that has it is joined; messages without it add nothing.
- **`ignore_when`** -- An object of `{"path": value}`. Messages that match all of them
  are skipped: they add no text and don't end the reply. Use it for messages that look
  like a reply but aren't one, such as an unprompted greeting.

Paths use the same syntax as the telemetry `extraction_map`: dots for keys and `[n]` for
list items, e.g. `"choices[0].delta.content"`. A path that isn't in a message counts as
`null`, so `{"path": null}` also matches messages without it. All three settings are
optional and independent, and `{"type": "end"}` still ends a reply.

For WebSocket agents, a `websocket` block inside `chat_completion` adds:

- **`keep_open`** -- `true` keeps one connection for the whole conversation instead of
  opening one per message. Use it when the agent keeps the conversation in the
  connection, so it remembers earlier turns. An unused connection is closed after
  5 minutes. If the agent closes it mid-conversation, the engine reconnects and logs a
  warning, since the agent may have lost the earlier turns.
- **`auto_reply`** -- A list of `{"when": {"path": value}, "send": {...}}`. When a
  message matching `when` arrives, `send` goes back at once, e.g. a `pong` for a
  keep-alive `ping`. A `"$path"` value in `send` is filled from the received message.
  Messages that arrive between turns, while the next test message is being generated,
  are answered when the next turn starts; an agent that drops a connection after a
  short unanswered ping may close it in that gap.

!!! warning "Local engine only, for now"
    These settings work in the offline local engine (`hb test --local`, or `hb test`
    while logged out). Runs on the platform -- `hb connect` and a logged-in `hb test` --
    don't support them yet and ignore them, so an agent that needs them fails there as
    it did before.

### Example: event-based WebSocket agent

An agent that streams `message.delta` events, ends the reply with `message.done`,
greets every new connection, and sends keep-alive pings:

```json
{
  "streaming": "websocket",
  "chat_completion": {
    "endpoint": "wss://agent.example.com/ws",
    "payload": { "type": "user_message", "text": "$PROMPT" },
    "response": {
      "complete_when": { "type": "message.done" },
      "text_path": "data.delta",
      "ignore_when": { "type": "greeting" }
    },
    "websocket": {
      "keep_open": true,
      "auto_reply": [
        {
          "when": { "type": "ping" },
          "send": { "type": "pong", "id": "$ping.id" }
        }
      ]
    }
  }
}
```

### Example: a voice agent platform (ElevenLabs Conversational AI)

The same settings connect to agents built on voice agent platforms, tested over text.
ElevenLabs Conversational AI is one of them. It keeps the conversation in the connection
and sends the reply in one `agent_response` message, among other events. It never sends
`{"type": "end"}` and sends keep-alive pings. It also answers the first message with its
greeting before the reply. The greeting is the `agent_response` that answers no user
message, so its `in_response_to_ids` is empty:

```json
{
  "streaming": "websocket",
  "thread_init": {
    "endpoint": "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id=<agent_id>",
    "headers": { "xi-api-key": "<api_key>" }
  },
  "chat_completion": {
    "endpoint": "$signed_url",
    "payload": { "type": "user_message", "text": "$PROMPT" },
    "response": {
      "complete_when": { "type": "agent_response" },
      "text_path": "agent_response_event.agent_response",
      "ignore_when": {
        "type": "agent_response",
        "agent_response_event.in_response_to_ids": []
      }
    },
    "websocket": {
      "keep_open": true,
      "auto_reply": [
        {
          "when": { "type": "ping" },
          "send": { "type": "pong", "event_id": "$ping_event.event_id" }
        }
      ]
    }
  }
}
```

`thread_init` fetches a signed URL once per conversation, so the API key never goes over
the WebSocket. For a public agent, use
`wss://api.elevenlabs.io/v1/convai/conversation?agent_id=<agent_id>` as the endpoint and
drop `thread_init`.

## Hosted-Platform Connector

Instead of the classic HTTP shape, `--endpoint` also accepts a **connector** block that
drives an agent deployed on a hosted platform (currently OpenAI Assistants) — no self-hosted
server needed:

```json
{
  "connector": {
    "provider": "openai_assistants",
    "config": {
      "api_key": "sk-...",
      "target_id": "asst_..."
    }
  }
}
```

!!! note "Assistants API deprecation"
    The Assistants API is deprecated and will be removed in August 2026. The recommended
    replacement is the Responses API. A Responses-based connector (`openai_responses`) is
    planned and will run alongside `openai_assistants`.

- `provider` — the connector transport (`openai_assistants` today).
- `config.api_key` / `config.target_id` — the platform credential and the assistant id.
- `config.input_template` — *advanced, optional.* A JSON envelope sent as the message text, with
  any exact `"$PROMPT"` value swapped for the prompt (e.g. `{ "message": "$PROMPT" }` → the
  assistant receives `{"message": "<prompt>"}`). Omit it to send the prompt as plain text; use a
  template only if your assistant is built to read a JSON envelope.

To discover these values automatically instead of hand-writing them, use
`hb connect --vendor openai` (see [Discovery](../integrations/discovery.md)).

!!! warning "Offline caveat"
    A connector config works whenever the test runs on the platform — both `hb connect`
    and a logged-in `hb test` send it to the backend, which hosts the conversation. It does
    **not** work in the offline local engine (`hb test --local`, or `hb test` while logged
    out), which implements only the classic HTTP/SSE/WebSocket transport and rejects
    connector configs with a clear error.

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
