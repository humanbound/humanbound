"""Unit tests for the `hb guardrails` command.

All mocked — no live API. Command accesses the API via `get_runner().client`,
so we patch `get_runner` and wire in a mock client via `platform_runner`.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.exceptions import APIError
from humanbound_cli.main import cli

from .conftest import (
    MOCK_GUARDRAILS,
    assert_exit_error,
    assert_exit_ok,
    local_runner,
    platform_runner,
)

runner = CliRunner()

RUNNER_PATCH = "humanbound_cli.commands.guardrails.get_runner"


def _make_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = True
    m.organisation_id = "org-123"
    m.project_id = "proj-456"
    m._organisation_id = "org-123"
    m._project_id = "proj-456"
    m.base_url = "http://test.local/api"
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


class TestHappyPath:
    @patch(RUNNER_PATCH)
    def test_guardrails_default_humanbound_json(self, mock_get_runner):
        client = _make_client()
        client.get.return_value = MOCK_GUARDRAILS
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["guardrails"])

        assert_exit_ok(result)
        data = json.loads(result.output.strip())
        assert data["version"] == "1.0"
        assert len(data["rules"]) == 1
        client.get.assert_called_once_with(
            "projects/proj-456/guardrails/export/humanbound",
            params={},
            include_project=True,
        )

    @patch(RUNNER_PATCH)
    def test_guardrails_vendor_openai(self, mock_get_runner):
        client = _make_client()
        client.get.return_value = MOCK_GUARDRAILS
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["guardrails", "--vendor", "openai"])

        assert_exit_ok(result)
        client.get.assert_called_once_with(
            "projects/proj-456/guardrails/export/openai",
            params={},
            include_project=True,
        )

    @patch(RUNNER_PATCH)
    def test_guardrails_format_yaml(self, mock_get_runner):
        client = _make_client()
        client.get.return_value = MOCK_GUARDRAILS
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["guardrails", "--format", "yaml"])

        assert_exit_ok(result)
        assert "version" in result.output
        assert "rules" in result.output

    @patch(RUNNER_PATCH)
    def test_guardrails_output_to_file(self, mock_get_runner, tmp_path):
        client = _make_client()
        client.get.return_value = MOCK_GUARDRAILS
        mock_get_runner.return_value = platform_runner(client)

        outfile = str(tmp_path / "guardrails.json")
        result = runner.invoke(cli, ["guardrails", "-o", outfile])

        assert_exit_ok(result)
        assert "exported" in result.output.lower() or "Guardrails" in result.output
        data = json.loads((tmp_path / "guardrails.json").read_text())
        assert data["version"] == "1.0"

    @patch(RUNNER_PATCH)
    def test_guardrails_with_model(self, mock_get_runner):
        client = _make_client()
        client.get.return_value = MOCK_GUARDRAILS
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["guardrails", "--model", "gpt-4o-mini"])

        assert_exit_ok(result)
        client.get.assert_called_once_with(
            "projects/proj-456/guardrails/export/humanbound",
            params={"model": "gpt-4o-mini"},
            include_project=True,
        )

    @patch(RUNNER_PATCH)
    def test_guardrails_include_reasoning(self, mock_get_runner):
        client = _make_client()
        client.get.return_value = MOCK_GUARDRAILS
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["guardrails", "--include-reasoning"])

        assert_exit_ok(result)
        client.get.assert_called_once_with(
            "projects/proj-456/guardrails/export/humanbound",
            params={"include_reasoning": "true"},
            include_project=True,
        )


class TestLocalGuardrails:
    @patch(RUNNER_PATCH)
    def test_exports_failed_insights_from_results_metadata(self, mock_get_runner):
        mock_get_runner.return_value = local_runner()

        with runner.isolated_filesystem():
            experiment_dir = Path(".humanbound/results/20260803-guardrails")
            experiment_dir.mkdir(parents=True)
            (experiment_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "results": {
                            "insights": [
                                {
                                    "result": "fail",
                                    "category": "prompt_injection",
                                    "explanation": "The bot followed an injected instruction.",
                                    "severity": "high",
                                }
                            ]
                        }
                    }
                )
            )

            result = runner.invoke(cli, ["guardrails"])

        assert_exit_ok(result)
        data = json.loads(result.output)
        assert data["metadata"]["total_rules"] == 1
        assert data["rules"] == [
            {
                "id": "gr-001",
                "threat_class": "prompt_injection",
                "pattern": "The bot followed an injected instruction.",
                "action": "block",
                "severity": "high",
                "source": "20260803-guardrails",
            }
        ]

    @patch(RUNNER_PATCH)
    def test_uses_top_level_insights_as_legacy_fallback(self, mock_get_runner):
        mock_get_runner.return_value = local_runner()

        with runner.isolated_filesystem():
            experiment_dir = Path(".humanbound/results/legacy-result")
            experiment_dir.mkdir(parents=True)
            (experiment_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "insights": [
                            {
                                "result": "fail",
                                "category": "legacy",
                            }
                        ]
                    }
                )
            )

            result = runner.invoke(cli, ["guardrails"])

        assert_exit_ok(result)
        data = json.loads(result.output)
        assert data["metadata"]["total_rules"] == 1
        assert data["rules"][0]["threat_class"] == "legacy"


class TestErrorCases:
    @patch(RUNNER_PATCH)
    def test_not_authenticated(self, mock_get_runner):
        client = _make_client()
        client.is_authenticated.return_value = False
        from humanbound_cli.exceptions import NotAuthenticatedError

        client.get.side_effect = NotAuthenticatedError()
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["guardrails"])

        assert_exit_error(result)
        assert "Not authenticated" in result.output

    @patch(RUNNER_PATCH)
    def test_no_project(self, mock_get_runner):
        client = _make_client(project_id=None, _project_id=None)
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["guardrails"])

        assert_exit_error(result)
        assert "No project selected" in result.output

    @patch(RUNNER_PATCH)
    def test_api_error(self, mock_get_runner):
        client = _make_client()
        client.get.side_effect = APIError("No guardrails available", 404)
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["guardrails"])

        assert_exit_error(result)
        assert "No guardrails available" in result.output


class TestFlags:
    @patch(RUNNER_PATCH)
    def test_vendor_and_model_combined(self, mock_get_runner):
        client = _make_client()
        client.get.return_value = MOCK_GUARDRAILS
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(
            cli,
            [
                "guardrails",
                "--vendor",
                "openai",
                "--model",
                "gpt-4o",
            ],
        )

        assert_exit_ok(result)
        client.get.assert_called_once_with(
            "projects/proj-456/guardrails/export/openai",
            params={"model": "gpt-4o"},
            include_project=True,
        )

    @patch(RUNNER_PATCH)
    def test_output_valid_json_default(self, mock_get_runner):
        client = _make_client()
        client.get.return_value = MOCK_GUARDRAILS
        mock_get_runner.return_value = platform_runner(client)

        result = runner.invoke(cli, ["guardrails"])

        data = json.loads(result.output.strip())
        assert "rules" in data
