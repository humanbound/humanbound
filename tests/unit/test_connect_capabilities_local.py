# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""hb connect --repo (local path): scope.yaml includes capabilities."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from humanbound_cli.commands.connect import connect_command

FIXTURES = Path(__file__).parent.parent / "fixtures" / "capabilities"

PATCH_CLIENT = "humanbound_cli.commands.connect.HumanboundClient"
PATCH_RESOLVE_SCOPE = "humanbound_cli.engine.scope.resolve"
PATCH_PROVIDER = "humanbound_cli.engine.local_runner._resolve_provider"
PATCH_LLM = "humanbound_cli.engine.llm.get_llm_pinger"


def _make_unauthenticated_client():
    m = MagicMock()
    m.is_authenticated.return_value = False
    m.organisation_id = None
    return m


def _stub_resolve_scope(*args, **kwargs):
    return {
        "overall_business_scope": "Customer support agent for flight bookings",
        "intents": {"permitted": ["search"], "restricted": []},
    }


class _StubPinger:
    """Minimal LLM pinger stub — returns a canned JSON string."""

    def ping(self, prompt):
        return '{"overall_business_scope":"stub","permitted":[],"restricted":[]}'


# resolve_scope is imported inside _connect_agent_local as:
#   from ..engine.scope import resolve as resolve_scope
# So the correct patch target is the original function location.
@patch(PATCH_CLIENT)
@patch(PATCH_RESOLVE_SCOPE, new=_stub_resolve_scope)
@patch(PATCH_PROVIDER, return_value={"name": "stub", "integration": {}})
@patch(PATCH_LLM, return_value=_StubPinger())
def test_local_connect_with_repo_writes_capabilities_to_yaml(
    mock_llm, mock_provider, mock_client_cls, tmp_path
):
    mock_client_cls.return_value = _make_unauthenticated_client()

    runner = CliRunner()
    fixture = FIXTURES / "tools_only_py"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            connect_command,
            ["--name", "agent-x", "--repo", str(fixture), "--yes"],
        )
        assert result.exit_code == 0, result.output

        scope_yaml = Path("scope.yaml")
        assert scope_yaml.is_file()
        scope = yaml.safe_load(scope_yaml.read_text())
        assert "capabilities" in scope, f"scope.yaml missing 'capabilities': {scope}"
        assert scope["capabilities"]["tools"] is True
        assert scope["capabilities"]["memory"] is False


@patch(PATCH_CLIENT)
@patch(PATCH_RESOLVE_SCOPE, new=_stub_resolve_scope)
@patch(PATCH_PROVIDER, return_value={"name": "stub", "integration": {}})
@patch(PATCH_LLM, return_value=_StubPinger())
def test_local_connect_with_repo_no_signals_omits_capabilities(
    mock_llm, mock_provider, mock_client_cls, tmp_path
):
    mock_client_cls.return_value = _make_unauthenticated_client()
    runner = CliRunner()
    empty = FIXTURES / "empty"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            connect_command,
            ["--name", "agent-x", "--repo", str(empty), "--yes"],
            input="1\n",  # in case --yes doesn't auto-default the chooser
        )
        assert result.exit_code == 0, result.output
        scope_yaml = Path("scope.yaml")
        assert scope_yaml.is_file()
        scope = yaml.safe_load(scope_yaml.read_text())
        assert "capabilities" not in scope, f"expected no capabilities key: {scope}"
