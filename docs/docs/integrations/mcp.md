# MCP Server

Humanbound exposes an **MCP (Model Context Protocol) server** that lets AI coding assistants (Claude Code, Cursor, Windsurf, GitHub Copilot) query your security testing data directly. Ask natural-language questions about posture, findings, coverage, and experiments without leaving your IDE.

## Setup

The MCP server is built into the Humanbound CLI and ships as an extra. Install it first:

```bash
pip install 'humanbound[mcp]'
```

!!! tip "zsh users"
    Quote the extras (`'humanbound[mcp]'`) — unquoted, zsh treats `[mcp]` as a glob and fails with `no matches found`.

`hb mcp` speaks MCP over **stdio** and is meant to be spawned by an MCP client (Claude Code, Cursor, Windsurf, etc.) — don't run it manually in a terminal.

### Claude Code

Register the server with the `claude` CLI instead of hand-editing JSON:

```bash
claude mcp add humanbound -- hb mcp                 # this project, just you (default)
claude mcp add -s user humanbound -- hb mcp         # all your projects
claude mcp add -s project humanbound -- hb mcp      # commit to repo (.mcp.json)
```

Scopes write to:

| Scope | Stored in | Visible to |
|---|---|---|
| `local` (default) | project `.claude/settings.local.json` | only you, only this project |
| `user` | `~/.claude.json` | only you, every project |
| `project` | `.mcp.json` (committed) | anyone who clones the repo |

Verify with `claude mcp list`. Note: `claude mcp` only configures Claude Code — Claude Desktop reads a separate config.

### Other clients

For IDEs/clients that take a JSON config directly:

```json
{
  "mcpServers": {
    "humanbound": {
      "command": "hb",
      "args": ["mcp"]
    }
  }
}
```

If your client launches with a minimal `PATH` and can't find `hb`, replace `"hb"` with the absolute path from `which hb`.

## Available Tools

| Tool | Description |
|---|---|
| `get_posture` | Current security posture score, grade, and trend data for the active project |
| `get_findings` | List findings with optional status/severity filters |
| `get_coverage` | Test coverage summary and untested categories |
| `get_experiments` | Recent experiments with status, results, and configuration |
| `get_logs` | Conversation logs and verdicts from a specific experiment |
| `get_campaigns` | Current ASCAM campaign status and phase information |

## Example Queries

Once configured, you can ask your AI assistant questions like:

- *"What's my current security posture score?"*
- *"Show me all critical findings that are still open"*
- *"What attack categories haven't been tested yet?"*
- *"Did the last experiment find any prompt injection vulnerabilities?"*
- *"What ASCAM phase is my project currently in?"*

!!! info "Requirements"
    Humanbound CLI must be installed and authenticated (`hb login`). The MCP server uses your existing CLI credentials and active project context.
