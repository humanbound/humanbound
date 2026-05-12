---
description: "Upload real conversation logs and evaluate them against Humanbound's security judges — score safety, scope, and policy adherence retroactively."
---

# Upload Conversation Logs

Evaluate real production conversations against security judges. This is useful for testing actual user interactions with your AI agent.

!!! warning "Deprecation"
    `hb upload-logs` is deprecated. Use `hb logs upload` instead.

## Upload from File

```bash
hb logs upload conversations.json
```

## Upload with Custom Tag

```bash
hb logs upload conversations.json --tag prod-v2
```

## Specify Language

```bash
hb logs upload conversations.json --lang english
```

## Expected JSON Format

```json
[
  {
    "conversation": [
      {"u": "user message", "a": "agent response"},
      {"u": "follow up", "a": "agent reply"}
    ],
    "thread_id": "optional-thread-id"
  },
  {
    "conversation": [
      {"u": "another conversation", "a": "agent response"}
    ],
    "thread_id": "thread-2"
  }
]
```

Each conversation object should contain an array of turn pairs (user input and agent response). The `thread_id` is optional but recommended for tracking.
