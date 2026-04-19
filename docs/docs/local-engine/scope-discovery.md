# Scope Discovery

The engine needs to know what your agent is allowed to do (permitted intents) and what it shouldn't do (restricted intents) to generate targeted attacks and evaluate responses.

## Scope Sources

Provide scope in order of preference:

### 1. Explicit Scope File (Recommended for precision)

```bash
hb test --endpoint ./config.json --scope ./scope.yaml --wait
```

```yaml
# scope.yaml
business_scope: "Customer support for Acme Bank"
permitted:
  - Provide account balance and transaction info
  - Process routine transfers within limits
  - Block lost cards
restricted:
  - Close accounts directly
  - Process transfers above 10,000 EUR
  - Access internal system records
more_info: "HIGH: finance domain agent"
```

Also accepts JSON:

```json
{
  "overall_business_scope": "Customer support for Acme Bank",
  "intents": {
    "permitted": ["Provide account balance", "Process transfers"],
    "restricted": ["Close accounts", "Access internal records"]
  }
}
```

### 2. Repository Scan (Recommended for convenience)

```bash
hb test --endpoint ./config.json --repo . --wait
```

Scans your agent's codebase for:

- **System prompt** (from config files, code, README)
- **Tool definitions** (function signatures, MCP tools)
- **README context**

Tools are critical for agentic testing — they reveal what actions the agent can take (e.g., `close_account`, `transfer_funds`), enabling excessive agency and tool abuse testing.

### 3. System Prompt File

```bash
hb test --endpoint ./config.json --prompt ./system_prompt.txt --wait
```

The engine uses the LLM to extract intents from your system prompt text.

### 4. Auto-Probe (No extra files)

```bash
hb test --endpoint ./config.json --wait
```

The engine sends probing messages to your bot and infers scope from its responses. Adds ~30-60 seconds. Less accurate than explicit scope.

!!! tip "Combine sources"
    You can combine `--repo` and `--prompt` for the richest extraction:
    ```bash
    hb test --endpoint ./config.json --repo . --prompt ./system_prompt.txt --wait
    ```
