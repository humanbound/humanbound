"""
Unit tests for the `hb connect` command.

Mocks HumanboundClient at the wire level (HTTP) and LLMPinger at the ping()
method, so `_connect_agent_platform` and `_connect_agent_local` execute their
bodies end-to-end. This is deliberate — earlier versions mocked the helper
functions themselves, which let NameErrors and other intra-function regressions
ship unnoticed.
"""

import os
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from conftest import MOCK_PROVIDER, assert_exit_ok

from humanbound_cli.main import cli

PATCH_CLIENT = "humanbound_cli.commands.connect.HumanboundClient"
runner = CliRunner()


def _make_authenticated_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = True
    m.organisation_id = "org-123"
    m.project_id = "proj-456"
    m._organisation_id = "org-123"
    m._project_id = "proj-456"
    m.base_url = "http://test.local/api"
    m.list_providers.return_value = [MOCK_PROVIDER]
    # Canned /scan response so _connect_agent_platform body can run
    m.post.return_value = {
        "scope": {
            "overall_business_scope": "Test agent",
            "intents": {"permitted": ["p1"], "restricted": ["r1"]},
        },
        "risk_profile": {
            "risk_level": "LOW",
            "industry": "testing",
            "handles_pii": False,
        },
        "default_integration": None,
    }
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


def _make_unauthenticated_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = False
    m.organisation_id = None
    m._organisation_id = None
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Help / flag surface
# ---------------------------------------------------------------------------


class TestHelpSurface:
    @patch(PATCH_CLIENT)
    def test_help_text(self, MockCls):
        result = runner.invoke(cli, ["connect", "--help"])
        assert_exit_ok(result)
        assert "connect" in result.output.lower()
        assert "--endpoint" in result.output

    @patch(PATCH_CLIENT)
    def test_flag_surface_stable(self, MockCls):
        """Lock down the flags we publicly document."""
        result = runner.invoke(cli, ["connect", "--help"])
        for flag in ("--name", "--level", "--yes", "--context", "--endpoint"):
            assert flag in result.output, f"missing flag: {flag}"

    @patch(PATCH_CLIENT)
    def test_no_flags_shows_usage(self, MockCls):
        MockCls.return_value = _make_authenticated_client()
        result = runner.invoke(cli, ["connect"])
        assert result.exit_code != 0
        assert "endpoint" in result.output.lower()


# ---------------------------------------------------------------------------
# Platform flow (authenticated): exercises _connect_agent_platform body
# ---------------------------------------------------------------------------


class TestPlatformFlow:
    @patch(PATCH_CLIENT)
    def test_authenticated_hits_scan_and_creates_project(self, MockCls):
        """--endpoint + auth → POST /scan runs + POST /projects runs."""
        client = _make_authenticated_client()
        # Differentiate scan vs projects in the canned responses
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "Customer support agent",
                    "intents": {"permitted": ["help users"], "restricted": ["leak secrets"]},
                },
                "risk_profile": {"risk_level": "MEDIUM", "industry": "tech"},
                "default_integration": None,
            }
            if path == "scan"
            else {"id": "proj-new"}
        )
        MockCls.return_value = client

        endpoint_json = '{"chat_completion":{"endpoint":"https://bot.example.com"}}'
        with (
            patch("humanbound_cli.commands.connect._auto_test"),
            patch("humanbound_cli.commands.connect._recommend_monitoring"),
        ):
            result = runner.invoke(
                cli, ["connect", "--endpoint", endpoint_json, "--yes", "--name", "bot"]
            )

        assert result.exit_code == 0, result.output
        # /scan was called with sources — not mocked away
        scan_calls = [c for c in client.post.call_args_list if c.args[0] == "scan"]
        assert scan_calls, "POST /scan should have been invoked"
        # /projects was called with scope
        project_calls = [c for c in client.post.call_args_list if c.args[0] == "projects"]
        assert project_calls, "POST /projects should have been invoked"


# ---------------------------------------------------------------------------
# Local flow (unauthenticated): exercises _connect_agent_local body
# ---------------------------------------------------------------------------


class StubPinger:
    """Fake LLMPinger that returns a canned JSON scope."""

    def __init__(self, response):
        self.response = response
        self.calls = 0

    def ping(self, system_p, user_p, max_tokens, temperature):
        self.calls += 1
        return self.response


class TestLocalFlow:
    @patch(PATCH_CLIENT)
    def test_no_auth_routes_to_local(self, MockCls, tmp_path):
        """Unauthenticated + --prompt → local flow runs LLM and writes scope.yaml."""
        MockCls.return_value = _make_unauthenticated_client()

        prompt_file = tmp_path / "system.txt"
        prompt_file.write_text(
            "You are a customer service agent for Acme Bank. You help customers check balances."
        )

        # Canned banking-flavored LLM response
        stub_json = """
        {
          "overall_business_scope": "Customer service for Acme Bank retail banking",
          "permitted": ["Check balance"],
          "restricted": ["Disclose passwords"]
        }
        """
        pinger = StubPinger(stub_json)

        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with (
                patch(
                    "humanbound_cli.engine.local_runner._resolve_provider",
                    return_value={"name": "stub", "integration": {}},
                ),
                patch("humanbound_cli.engine.llm.get_llm_pinger", return_value=pinger),
            ):
                result = runner.invoke(cli, ["connect", "--prompt", str(prompt_file), "--yes"])
        finally:
            os.chdir(cwd)

        assert result.exit_code == 0, result.output
        assert pinger.calls >= 1, "LLM should have been called for scope extraction"
        assert "(not authenticated — running local scope extraction)" in result.output
        assert "scope.yaml" in result.output
        # Compliance overlay detected banking domain from the text
        assert "Banking" in result.output
        # scope.yaml was actually written
        scope_file = tmp_path / "scope.yaml"
        assert scope_file.exists()
        content = scope_file.read_text()
        assert "business_scope:" in content
        assert "permitted:" in content
        assert "restricted:" in content

    @patch(PATCH_CLIENT)
    def test_no_auth_no_llm_provider_errors_cleanly(self, MockCls, tmp_path):
        """Unauthenticated + no LLM → clear error with remediation options."""
        MockCls.return_value = _make_unauthenticated_client()

        prompt_file = tmp_path / "system.txt"
        prompt_file.write_text("Test agent")

        # _resolve_provider raises ValueError when no provider is configured
        with patch.dict("os.environ", {"HB_PROVIDER": "", "HB_API_KEY": ""}, clear=False):
            result = runner.invoke(cli, ["connect", "--prompt", str(prompt_file), "--yes"])

        assert result.exit_code != 0
        assert "No LLM provider configured" in result.output
        # The error block lists the 4 config options
        assert "HB_PROVIDER" in result.output

    @patch(PATCH_CLIENT)
    def test_no_auth_no_org_still_goes_local(self, MockCls, tmp_path):
        """Authenticated=True but no org → treated as non-Platform, routes local."""
        client = _make_unauthenticated_client()
        client.is_authenticated.return_value = True
        client.organisation_id = None
        MockCls.return_value = client

        prompt_file = tmp_path / "system.txt"
        prompt_file.write_text("Test agent")

        pinger = StubPinger('{"overall_business_scope":"x","permitted":[],"restricted":[]}')
        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with (
                patch(
                    "humanbound_cli.engine.local_runner._resolve_provider",
                    return_value={"name": "stub", "integration": {}},
                ),
                patch("humanbound_cli.engine.llm.get_llm_pinger", return_value=pinger),
            ):
                result = runner.invoke(cli, ["connect", "--prompt", str(prompt_file), "--yes"])
        finally:
            os.chdir(cwd)

        assert result.exit_code == 0, result.output
        assert "running local scope extraction" in result.output


# ---------------------------------------------------------------------------
# Regression guards (would have caught the v2.0.0 NameError shipment)
# ---------------------------------------------------------------------------


class TestRegressionGuards:
    @patch(PATCH_CLIENT)
    def test_all_helpers_defined_in_connect_module(self, MockCls):
        """Names referenced inside _connect_agent_platform must exist in connect.py."""
        from humanbound_cli.commands import connect

        for name in (
            "_SCAN_PHASES",
            "_scan_with_progress",
            "_display_scope",
            "_display_dashboard",
            "_get_source_description",
            "_load_integration",
            "_connect_agent",
            "_connect_agent_platform",
            "_connect_agent_local",
            "_write_scope_yaml",
            "_print_platform_note",
        ):
            assert hasattr(connect, name), f"missing: connect.{name}"

    @patch(PATCH_CLIENT)
    def test_compliance_module_is_callable(self, MockCls):
        """engine.compliance exports detect_domain + apply_template."""
        from humanbound_cli.engine import compliance

        assert callable(compliance.detect_domain)
        assert callable(compliance.apply_template)
        assert callable(compliance.apply_eu_ai_act_only)
        assert callable(compliance.load_template)
        # Bundled templates must be shippable
        for domain in ("banking", "insurance", "healthcare", "legal", "ecommerce", "eu-ai-act"):
            assert compliance.load_template(domain), f"missing template: {domain}"
