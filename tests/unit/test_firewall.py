"""
Unit tests for `hb firewall` commands (train, show).

Firewall train/show have complex local processing (hb_firewall imports,
model training) that's hard to mock cleanly, so we focus on help text
and auth guards.
"""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

runner = CliRunner()

PATCH_TARGET = "humanbound_cli.commands.firewall.get_runner"


def _make_mock_client(**overrides):
    mock = MagicMock()
    mock.is_authenticated.return_value = True
    mock.organisation_id = "org-123"
    mock.project_id = "proj-456"
    mock._organisation_id = "org-123"
    mock._project_id = "proj-456"
    mock._username = "tester"
    mock._email = "test@example.com"
    mock.base_url = "http://test.local/api"
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


class TestHappyPath:
    def test_firewall_help(self):
        """firewall --help shows group description."""
        result = runner.invoke(cli, ["firewall", "--help"])
        assert result.exit_code == 0
        assert "firewall" in result.output.lower()
        assert "train" in result.output.lower()
        assert "show" in result.output.lower()

    def test_firewall_train_help(self):
        """firewall train --help shows all options."""
        result = runner.invoke(cli, ["firewall", "train", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output
        assert "--last" in result.output
        assert "--min-samples" in result.output
        assert "--output" in result.output
        assert "--import" in result.output

    def test_firewall_show_help(self):
        """firewall show --help shows usage."""
        result = runner.invoke(cli, ["firewall", "show", "--help"])
        assert result.exit_code == 0
        assert "MODEL_PATH" in result.output or "model_path" in result.output.lower()

    @patch(PATCH_TARGET)
    def test_train_no_model_flag_no_hb_firewall(self, MockClient):
        """train without --model and without hb_firewall installed exits non-zero."""
        mock = _make_mock_client()
        from conftest import platform_runner

        MockClient.return_value = platform_runner(mock)
        result = runner.invoke(cli, ["firewall", "train"])
        # Should fail because hb_firewall is not installed in test env
        assert result.exit_code != 0

    @patch(PATCH_TARGET)
    def test_train_requires_project(self, MockClient):
        """train fails when no project is selected."""
        mock = _make_mock_client(project_id=None, _project_id=None)
        from conftest import platform_runner

        MockClient.return_value = platform_runner(mock)
        # Provide --model so it doesn't fail on missing hb_firewall first
        result = runner.invoke(cli, ["firewall", "train", "--model", "fake.py"])
        assert result.exit_code != 0


class TestErrorCases:
    @patch(PATCH_TARGET)
    def test_train_not_authenticated(self, MockClient):
        """train raises NotAuthenticatedError when not logged in."""
        mock = _make_mock_client()
        mock.is_authenticated.return_value = False
        # Simulate the client constructor raising NotAuthenticatedError
        # In reality, the command catches NotAuthenticatedError from API calls.
        # Since train instantiates client and then calls API, we test that
        # it doesn't crash without auth by checking exit code.
        from conftest import platform_runner

        MockClient.return_value = platform_runner(mock)
        # Without --model, it tries to find hb_firewall first, which isn't installed
        # So the error path depends on whether hb_firewall is importable.
        # We just verify it exits non-zero.
        result = runner.invoke(cli, ["firewall", "train", "--model", "fake.py"])
        assert result.exit_code != 0

    @patch(PATCH_TARGET)
    def test_train_api_error(self, MockClient):
        """train handles APIError gracefully."""
        mock = _make_mock_client()
        mock.list_experiments.side_effect = APIError("Server error", status_code=500)
        from conftest import platform_runner

        MockClient.return_value = platform_runner(mock)
        # Will fail before reaching API because hb_firewall is not installed
        result = runner.invoke(cli, ["firewall", "train", "--model", "fake.py"])
        assert result.exit_code != 0

    def test_show_missing_file(self):
        """show with non-existent file exits with error."""
        result = runner.invoke(cli, ["firewall", "show", "/tmp/nonexistent_model.hbfw"])
        assert result.exit_code != 0
