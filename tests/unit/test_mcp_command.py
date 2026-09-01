# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""`hb mcp` must say why the MCP import failed, not just that it did.

A missing SDK and an incompatible one need different fixes, so the error keeps
the install command first and the underlying cause as a labelled detail.
"""

import sys

import pytest
from click.testing import CliRunner

from humanbound_cli.main import cli

MCP_SERVER = "humanbound_cli.mcp_server"

ABSENT = "No module named 'mcp'"
INCOMPATIBLE = (
    "No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer"
)


class _RaisingFinder:
    """Meta-path finder that fails one module with a chosen ImportError."""

    def __init__(self, target: str, exc: ImportError):
        self._target = target
        self._exc = exc

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self._target:
            raise self._exc
        return None


def _run_hb_mcp(monkeypatch, message: str):
    """Invoke `hb mcp` with the MCP server import failing with `message`."""
    monkeypatch.delitem(sys.modules, MCP_SERVER, raising=False)
    monkeypatch.setattr(
        sys,
        "meta_path",
        [_RaisingFinder(MCP_SERVER, ModuleNotFoundError(message))] + sys.meta_path,
    )
    return CliRunner().invoke(cli, ["mcp"])


@pytest.mark.parametrize("message", [ABSENT, INCOMPATIBLE])
def test_underlying_import_error_reaches_the_user(monkeypatch, message):
    result = _run_hb_mcp(monkeypatch, message)

    assert result.exit_code != 0
    assert message in result.output, result.output
    assert "pip install 'humanbound[mcp]'" in result.output


def test_the_actionable_line_comes_before_the_details(monkeypatch):
    """The install command is the headline; the raw cause stays secondary."""
    output = _run_hb_mcp(monkeypatch, ABSENT).output

    assert output.index("pip install") < output.index(ABSENT)


def test_distinct_causes_produce_distinct_messages(monkeypatch):
    absent = _run_hb_mcp(monkeypatch, ABSENT).output
    incompatible = _run_hb_mcp(monkeypatch, INCOMPATIBLE).output

    assert absent != incompatible
