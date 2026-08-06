---
description: "Upload real conversation logs and evaluate them against Humanbound's security judges — score safety, scope, and policy adherence retroactively."
keywords:
  - upload conversation logs
  - hb logs upload
  - retroactive evaluation
  - real conversation evaluation
  - conversation log format
  - log file evaluation
---

# Upload Conversation Logs

The `hb logs upload` command sends conversation logs from your live agent through Humanbound's judges so you can score real user interactions against the same security criteria adversarial tests use. The expected format is a JSON array where each entry has a `conversation` array of `{u, a}` turn pairs and an optional `thread_id`; an optional `--tag` lets you group uploads (for example, by release), and `--lang` sets the evaluation language.

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
