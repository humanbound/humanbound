# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Source-level guard for MCP tool error handling (#68).

Deliberately not gated on the [mcp] extra: this reads mcp_server.py as text,
so it protects the invariant even in environments where mcp isn't installed."""

from __future__ import annotations

import re
from pathlib import Path

MCP_SERVER_SRC = Path(__file__).parents[2] / "humanbound_cli" / "mcp_server.py"


def test_every_tool_has_a_broad_exception_fallback():
    """A tool without the `except Exception` fallback leaks FastMCP's raw
    "Error executing tool <name>: <exception>" text to the MCP client."""
    blocks = re.split(r"(?=@mcp\.tool\(\))", MCP_SERVER_SRC.read_text())
    tools = {
        re.search(r"def (\w+)\(", b).group(1): b for b in blocks if b.startswith("@mcp.tool()")
    }
    assert len(tools) >= 65
    missing = [name for name, block in tools.items() if "except Exception as e:" not in block]
    assert missing == []
