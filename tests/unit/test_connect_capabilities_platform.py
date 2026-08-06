# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""hb connect --repo (platform path, NEW project): POST body includes scope.capabilities."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.commands.connect import connect_command

FIXTURES = Path(__file__).parent.parent / "fixtures" / "capabilities"


def _stub_scan_response(*args, **kwargs):
    """Stand-in for _scan_with_progress — returns a fully-built BE-side scope."""
    return {
        "scope": {
            "overall_business_scope": "Customer support agent for flight bookings",
            "intents": {"permitted": ["search"], "restricted": []},
        },
        "risk_profile": {"level": "medium"},
        "sources_metadata": {},
        "default_integration": None,
    }


def _stub_repo_scanner_scan(self):
    """Stand-in for RepoScanner.scan() — returns tool-bearing agentic content."""
    return {
        "files": ["agent.py"],
        "tools": [{"name": "search_flights", "description": "Search for flights."}],
        "system_prompt": "You are a helpful flight booking assistant.",
        "readme": "",
    }


@patch("humanbound_cli.commands.connect._scan_with_progress", new=_stub_scan_response)
@patch("humanbound_cli.extractors.repo.RepoScanner.scan", new=_stub_repo_scanner_scan)
@patch("humanbound_cli.commands.connect.HumanboundClient")
def test_platform_new_project_includes_capabilities(mock_client_cls, tmp_path):
    client = MagicMock()
    client.is_authenticated.return_value = True
    client.organisation_id = "org-123"
    client.project_id = None  # No active project — this is a new-project flow
    client.post.return_value = {"id": "new-1", "name": "agent-x"}
    mock_client_cls.return_value = client

    runner = CliRunner()
    fixture = FIXTURES / "tools_only_py"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            connect_command,
            ["--name", "agent-x", "--repo", str(fixture), "--yes"],
        )
        # We don't strictly need exit_code 0 (auto-test may fail in mocks) — what
        # we care about is the POST body for project creation.
        # Check that client.post was called with a "projects" path.
        post_calls = [c for c in client.post.call_args_list if c.args and c.args[0] == "projects"]
        assert post_calls, (
            f"client.post('projects', ...) was not called. All calls: {client.post.call_args_list}. CLI output:\n{result.output}"
        )

        project_post = post_calls[0]
        payload = project_post.kwargs.get("data") or (
            project_post.args[1] if len(project_post.args) > 1 else None
        )
        assert payload is not None, f"Could not find data payload. Call: {project_post}"
        assert "scope" in payload
        assert payload["scope"]["capabilities"]["tools"] is True
        assert payload["scope"]["capabilities"]["memory"] is False


@patch("humanbound_cli.commands.connect._scan_with_progress", new=_stub_scan_response)
@patch("humanbound_cli.commands.connect.HumanboundClient")
def test_platform_existing_project_uses_write_capabilities(mock_client_cls, tmp_path):
    client = MagicMock()
    client.is_authenticated.return_value = True
    client.organisation_id = "org-123"
    client.project_id = "existing-1"  # Active project — update, not create
    client.get_project.return_value = {
        "id": "existing-1",
        "name": "T",
        "scope": {
            "overall_business_scope": "Customer support agent for flight bookings",
            "intents": {"permitted": [], "restricted": []},
            "capabilities": {
                "tools": False,
                "memory": False,
                "inter_agent": False,
                "reasoning_model": False,
            },
        },
    }
    mock_client_cls.return_value = client

    runner = CliRunner()
    fixture = FIXTURES / "tools_only_py"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Mirror Task 19's RepoScanner mock — needed to get past the "no sources" guard.
        from unittest.mock import patch as inner_patch

        with inner_patch("humanbound_cli.extractors.repo.RepoScanner") as ScannerCls:
            scanner = ScannerCls.return_value
            scanner.scan.return_value = {"files": ["a.py"], "tools": ["t"], "system_prompt": "x"}
            result = runner.invoke(
                connect_command,
                ["--name", "agent-x", "--repo", str(fixture), "--yes"],
            )

    # On the existing-project branch we should call update_project, not post('projects', ...).
    update_calls = client.update_project.call_args_list
    assert update_calls, f"update_project was not called. Output:\n{result.output}"
    # And no POST to create a new project should have happened.
    new_project_posts = [
        c for c in client.post.call_args_list if c.args and c.args[0] == "projects"
    ]
    assert not new_project_posts, f"Unexpected new-project POST: {new_project_posts}"

    # The PUT body should contain the full scope with capabilities flipped.
    payload = update_calls[0].args[1]
    assert payload["scope"]["capabilities"]["tools"] is True
    # And the existing scope's overall_business_scope must be preserved by read-modify-write.
    assert payload["scope"]["overall_business_scope"].startswith("Customer support")


def _write_scope_with_capabilities(tmp_path):
    p = tmp_path / "scope.yaml"
    p.write_text(
        "business_scope: 'Banking support agent for Acme Bank'\n"
        "permitted: [balance]\n"
        "restricted: [advice]\n"
        "capabilities:\n"
        "  tools: true\n"
        "  memory: false\n"
    )
    return p


@patch("humanbound_cli.commands.connect._scan_with_progress", new=_stub_scan_response)
@patch("humanbound_cli.commands.connect.HumanboundClient")
def test_platform_scope_file_capabilities_reach_project(mock_client_cls, tmp_path):
    """A `capabilities:` block in --scope lands on the created project's scope."""
    client = MagicMock()
    client.is_authenticated.return_value = True
    client.organisation_id = "org-123"
    client.project_id = None
    client.post.return_value = {"id": "new-1", "name": "agent-x"}
    mock_client_cls.return_value = client

    scope_file = _write_scope_with_capabilities(tmp_path)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            connect_command,
            ["--name", "agent-x", "--scope", str(scope_file), "--yes", "--no-test"],
        )

    post_calls = [c for c in client.post.call_args_list if c.args and c.args[0] == "projects"]
    assert post_calls, f"client.post('projects', ...) was not called. Output:\n{result.output}"
    payload = post_calls[0].kwargs.get("data") or post_calls[0].args[1]
    assert payload["scope"]["capabilities"] == {"tools": True, "memory": False}


@patch("humanbound_cli.commands.connect._scan_with_progress", new=_stub_scan_response)
@patch("humanbound_cli.extractors.repo.RepoScanner.scan", new=_stub_repo_scanner_scan)
@patch("humanbound_cli.commands.connect.HumanboundClient")
def test_platform_scope_file_capabilities_override_repo_scan(mock_client_cls, tmp_path):
    """--scope + --repo: the file's explicit values win over scanned ones per key."""
    client = MagicMock()
    client.is_authenticated.return_value = True
    client.organisation_id = "org-123"
    client.project_id = None
    client.post.return_value = {"id": "new-1", "name": "agent-x"}
    mock_client_cls.return_value = client

    scope_file = tmp_path / "scope.yaml"
    scope_file.write_text(
        "business_scope: 'Banking support agent for Acme Bank'\n"
        "permitted: [balance]\n"
        "restricted: [advice]\n"
        "capabilities:\n"
        "  tools: false\n"  # scanner would say True for tools_only_py — file wins
    )
    runner = CliRunner()
    fixture = FIXTURES / "tools_only_py"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            connect_command,
            [
                "--name",
                "agent-x",
                "--repo",
                str(fixture),
                "--scope",
                str(scope_file),
                "--yes",
                "--no-test",
            ],
        )

    post_calls = [c for c in client.post.call_args_list if c.args and c.args[0] == "projects"]
    assert post_calls, f"client.post('projects', ...) was not called. Output:\n{result.output}"
    payload = post_calls[0].kwargs.get("data") or post_calls[0].args[1]
    caps = payload["scope"]["capabilities"]
    assert caps["tools"] is False  # file override
    assert caps["memory"] is False  # from scan baseline
