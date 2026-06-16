"""`hb experiments show --config` — print the configuration an experiment ran with.

The platform stores the full configuration (bot integration endpoints, scope,
context) on every experiment. The CLI prints it back verbatim so users can see
exactly which bot config a run used and reuse it (pipe to a file, re-run
`hb test`). No masking: the API already returns the configuration unmasked to
any authenticated project member, so the CLI hiding values would only break
reuse without protecting anything.
"""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.main import cli

PATCH = "humanbound_cli.commands.experiments.HumanboundClient"
runner = CliRunner()


def _experiment():
    return {
        "id": "exp-789",
        "name": "quick",
        "status": "Finished",
        "test_category": "humanbound/adversarial/owasp_agentic",
        "lang": "el",
        "testing_level": "unit",
        "configuration": {
            "integration": {
                "streaming": False,
                "thread_auth": {
                    "endpoint": "https://qa.example.bank.gr/auth",
                    "headers": {"Authorization": "Bearer sk-secret-123"},
                    "payload": {"username": "svc-user", "password": "hunter2"},
                },
                "thread_init": {
                    "endpoint": "https://qa.example.bank.gr/sessions",
                    "headers": {"X-Session-Key": "sess-secret-456"},
                    "payload": {"messageType": "greeting"},
                },
                "chat_completion": {
                    "endpoint": "https://qa.example.bank.gr/messages",
                    "headers": {},
                    "payload": {},
                },
            },
            "scope": {
                "overall_business_scope": "Retail banking customer support",
                "intents": {"permitted": ["balance"], "restricted": ["approve_loan"]},
            },
            "context": "Authenticated as test customer",
        },
        "results": {"stats": {"total": 97, "pass": 80, "fail": 7}, "insights": []},
    }


def _invoke(args, experiment=None):
    client = MagicMock()
    client.project_id = "proj-456"
    client.get_experiment.return_value = experiment or _experiment()
    with patch(PATCH, return_value=client):
        return runner.invoke(cli, args)


class TestConfigFlag:
    def test_prints_endpoints_scope_and_context(self):
        r = _invoke(["experiments", "show", "exp-789", "--config"])
        assert r.exit_code == 0
        assert "https://qa.example.bank.gr/messages" in r.output
        assert "Retail banking customer support" in r.output
        assert "approve_loan" in r.output
        assert "Authenticated as test customer" in r.output

    def test_configuration_printed_verbatim_for_reuse(self):
        r = _invoke(["experiments", "show", "exp-789", "--config"])
        assert "Authorization" in r.output
        assert "Bearer sk-secret-123" in r.output
        assert "sess-secret-456" in r.output
        assert "hunter2" in r.output
        assert "greeting" in r.output

    def test_no_configuration_stored(self):
        experiment = _experiment()
        experiment["configuration"] = {}
        r = _invoke(["experiments", "show", "exp-789", "--config"], experiment)
        assert r.exit_code == 0
        assert "No configuration stored" in r.output

    def test_default_output_unchanged(self):
        r = _invoke(["experiments", "show", "exp-789"])
        assert r.exit_code == 0
        assert "https://qa.example.bank.gr" not in r.output


class TestEndpointRoundTrip:
    """A file produced by `hb experiments show --config` must be directly
    reusable as `hb test --endpoint <file>` — the loader unwraps the full
    configuration object down to its integration block."""

    def test_full_configuration_unwraps_to_integration(self, tmp_path):
        import json

        from humanbound_cli.commands.test import _load_integration

        config = _experiment()["configuration"]
        config_file = tmp_path / "bot-config.json"
        config_file.write_text(json.dumps(config))

        loaded = _load_integration(str(config_file))
        assert loaded == config["integration"]

    def test_plain_integration_still_loads_verbatim(self, tmp_path):
        import json

        from humanbound_cli.commands.test import _load_integration

        integration = _experiment()["configuration"]["integration"]
        config_file = tmp_path / "bot-config.json"
        config_file.write_text(json.dumps(integration))

        loaded = _load_integration(str(config_file))
        assert loaded == integration
