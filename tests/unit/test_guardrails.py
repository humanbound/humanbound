"""Unit tests for the `hb guardrails` command.

All mocked — no live API. Command accesses the API via `get_runner().client`,
so we patch `get_runner` and wire in a mock client via `platform_runner`.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
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


LOCAL_SCOPE = {
    "overall_business_scope": "Price quotes for B2B customers",
    "intents": {
        "permitted": ["Quote a list price"],
        "restricted": ["Quote below the floor price"],
    },
    "more_info": "EUR only.",
    "capabilities": {"tools": True, "memory": False},
}

SCOPE_FILE = """\
business_scope: Price quotes for B2B customers
permitted: [Quote a list price]
restricted: [Quote below the floor price]
capabilities: {tools: true, memory: false}
"""


def _write_run(name, meta):
    run = Path(".humanbound/results") / name
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps(meta))


class TestLocalAgentYaml:
    """Not logged in, --format yaml writes the humanbound-firewall agent.yaml."""

    @patch(RUNNER_PATCH)
    def test_builds_agent_yaml_from_latest_run_scope(self, mock_get_runner):
        mock_get_runner.return_value = local_runner()

        with runner.isolated_filesystem():
            _write_run("exp-1-old", {"scope": {"overall_business_scope": "old"}})
            _write_run("exp-2-new", {"results": {}, "scope": LOCAL_SCOPE})
            result = runner.invoke(cli, ["guardrails", "--format", "yaml"])

        assert_exit_ok(result)
        assert "local run exp-2-new" in result.output
        assert yaml.safe_load(result.output) == {
            "version": "1.0",
            "scope": {"business": "Price quotes for B2B customers", "more_info": "EUR only."},
            "intents": {
                "permitted": ["Quote a list price"],
                "restricted": ["Quote below the floor price"],
            },
            "capabilities": ["tools"],
        }

    @patch(RUNNER_PATCH)
    def test_scope_file_builds_agent_yaml(self, mock_get_runner, tmp_path):
        mock_get_runner.return_value = local_runner()
        scope = tmp_path / "scope.yaml"
        scope.write_text(SCOPE_FILE)

        result = runner.invoke(cli, ["guardrails", "-f", "yaml", "--scope", str(scope)])

        assert_exit_ok(result)
        doc = yaml.safe_load(result.output)
        assert doc["scope"]["business"] == "Price quotes for B2B customers"
        assert doc["intents"]["restricted"] == ["Quote below the floor price"]
        assert doc["capabilities"] == ["tools"]

    @patch(RUNNER_PATCH)
    def test_run_without_saved_scope_asks_for_test_or_scope(self, mock_get_runner):
        """Runs from before the scope was saved: run a test, or pass --scope."""
        mock_get_runner.return_value = local_runner()

        with runner.isolated_filesystem():
            _write_run("exp-1", {"results": {"insights": []}})
            result = runner.invoke(cli, ["guardrails", "--format", "yaml"])

        assert_exit_error(result)
        assert "hb test" in result.output
        assert "--scope" in result.output

    @patch(RUNNER_PATCH)
    def test_no_local_results_asks_for_test_or_scope(self, mock_get_runner):
        mock_get_runner.return_value = local_runner()

        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["guardrails", "--format", "yaml"])

        assert_exit_error(result)
        assert "--scope" in result.output

    @patch(RUNNER_PATCH)
    def test_unknown_capability_in_scope_file_is_an_error(self, mock_get_runner, tmp_path):
        mock_get_runner.return_value = local_runner()
        scope = tmp_path / "scope.yaml"
        scope.write_text(SCOPE_FILE.replace("memory: false", "vision: true"))

        result = runner.invoke(cli, ["guardrails", "-f", "yaml", "--scope", str(scope)])

        assert_exit_error(result)
        assert "vision" in result.output

    @patch(RUNNER_PATCH)
    def test_unparseable_scope_file_is_an_error(self, mock_get_runner, tmp_path):
        mock_get_runner.return_value = local_runner()
        scope = tmp_path / "scope.yaml"
        scope.write_text("business_scope: [unclosed")

        result = runner.invoke(cli, ["guardrails", "-f", "yaml", "--scope", str(scope)])

        assert_exit_error(result)
        assert "Could not parse scope file" in result.output

    @patch(RUNNER_PATCH)
    def test_json_stays_the_rules_list(self, mock_get_runner):
        mock_get_runner.return_value = local_runner()

        with runner.isolated_filesystem():
            _write_run("exp-1", {"results": {"insights": []}, "scope": LOCAL_SCOPE})
            result = runner.invoke(cli, ["guardrails"])

        assert_exit_ok(result)
        assert "rules" in json.loads(result.output)

    @patch(RUNNER_PATCH)
    def test_agent_yaml_loads_in_the_firewall(self, mock_get_runner, tmp_path):
        config = pytest.importorskip("humanbound_firewall.config")
        mock_get_runner.return_value = local_runner()
        scope = tmp_path / "scope.yaml"
        scope.write_text(SCOPE_FILE)
        out = tmp_path / "agent.yaml"

        result = runner.invoke(
            cli, ["guardrails", "-f", "yaml", "--scope", str(scope), "-o", str(out)]
        )

        assert_exit_ok(result)
        loaded = config.load_config(out)
        assert loaded.business_scope == "Price quotes for B2B customers"
        assert loaded.permitted_intents == ["Quote a list price"]
        assert loaded.restricted_intents == ["Quote below the floor price"]
        assert loaded.capabilities == ["tools"]


# GET projects/{id}/guardrails/export/humanbound, in the agent.yaml layout
PLATFORM_AGENT_YAML = {
    "name": "PriceBot",
    "version": "1.0",
    "scope": {"business": "Price quotes for B2B customers", "more_info": "EUR only."},
    "intents": {
        "permitted": ["Quote a list price"],
        "restricted": ["Quote below the floor price"],
    },
    "capabilities": ["tools"],
}


class TestPlatformYaml:
    """Logged in, the export is saved as the platform returns it."""

    @patch(RUNNER_PATCH)
    def test_logged_in_yaml_loads_in_the_firewall(self, mock_get_runner, tmp_path):
        config = pytest.importorskip("humanbound_firewall.config")
        client = _make_client()
        client.get.return_value = PLATFORM_AGENT_YAML
        mock_get_runner.return_value = platform_runner(client)
        out = tmp_path / "agent.yaml"

        result = runner.invoke(cli, ["guardrails", "-f", "yaml", "-o", str(out)])

        assert_exit_ok(result)
        assert yaml.safe_load(out.read_text()) == PLATFORM_AGENT_YAML
        loaded = config.load_config(out)
        assert loaded.name == "PriceBot"
        assert loaded.business_scope == "Price quotes for B2B customers"
        assert loaded.permitted_intents == ["Quote a list price"]
        assert loaded.restricted_intents == ["Quote below the floor price"]
        assert loaded.capabilities == ["tools"]

    @patch(RUNNER_PATCH)
    def test_logged_in_yaml_is_the_platform_export_as_is(self, mock_get_runner, tmp_path):
        client = _make_client()
        client.get.return_value = MOCK_GUARDRAILS
        mock_get_runner.return_value = platform_runner(client)
        scope = tmp_path / "scope.yaml"
        scope.write_text(SCOPE_FILE)

        result = runner.invoke(cli, ["guardrails", "-f", "yaml", "--scope", str(scope)])

        assert_exit_ok(result)
        assert "ignoring it" in result.output
        body = result.output[result.output.index("version") :]
        assert yaml.safe_load(body) == MOCK_GUARDRAILS
