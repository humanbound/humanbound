# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""hb mcp — start the Humanbound MCP server on stdio."""

import click


@click.command("mcp")
def mcp_command():
    """Start the Humanbound MCP server (stdio transport).

    Exposes all Humanbound CLI capabilities as MCP tools so that
    AI assistants (Claude Code, Cursor, Gemini CLI, etc.) can use them.

    \b
    Prerequisites:
      pip install humanbound-cli[mcp]   # install MCP dependencies
      hb login                          # authenticate first

    \b
    Usage with Claude Code:
      Add to .claude/settings.json:
      {
        "mcpServers": {
          "humanbound": { "command": "hb", "args": ["mcp"] }
        }
      }
    """
    try:
        from ..mcp_server import main
    except ImportError:
        raise click.ClickException(
            "MCP dependencies not installed. Run: pip install humanbound-cli[mcp]"
        )
    main()
