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

import pytest
from click.testing import CliRunner
from conftest import MOCK_PROVIDER, assert_exit_ok

from humanbound_cli.main import cli

PATCH_CLIENT = "humanbound_cli.commands.connect.HumanboundClient"
runner = CliRunner()


def _write_scope_yaml(tmp_path, **overrides):
    """Write a minimal valid scope.yaml under tmp_path; return its str path.

    Default contents match the canonical scope shape; pass keyword args to
    override individual top-level keys.
    """
    import yaml

    doc = {
        "business_scope": (
            "Customer support agent for an online retailer. Handles order status, "
            "returns, and product questions."
        ),
        "permitted": [
            "Look up order status for the authenticated customer",
            "Initiate a return for an in-policy order",
            "Answer product specification questions",
        ],
        "restricted": [
            "Quote a refund amount before the return is inspected",
            "Disclose another customer's order details",
        ],
        "more_info": "Agent uses a vector store of product manuals.",
    }
    doc.update(overrides)
    path = tmp_path / "scope.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return str(path)


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
        for flag in (
            "--name",
            "--level",
            "--yes",
            "--context",
            "--endpoint",
            "--no-test",
            "--test-category",
            "--scope",
        ):
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


# ---------------------------------------------------------------------------
# Helper: _load_scope_file
# ---------------------------------------------------------------------------


class TestLoadScopeFile:
    def test_loads_valid_yaml(self, tmp_path):
        from humanbound_cli.commands.connect import _load_scope_file

        scope = _load_scope_file(_write_scope_yaml(tmp_path))
        assert scope["business_scope"].startswith("Customer support agent")
        assert len(scope["permitted"]) == 3
        assert len(scope["restricted"]) == 2
        assert "vector store" in scope["more_info"]

    def test_loads_valid_json(self, tmp_path):
        from humanbound_cli.commands.connect import _load_scope_file

        p = tmp_path / "scope.json"
        p.write_text('{"business_scope":"X","permitted":["a"],"restricted":["b"]}')
        scope = _load_scope_file(str(p))
        assert scope["business_scope"] == "X"
        assert scope["permitted"] == ["a"]
        assert scope["restricted"] == ["b"]
        assert scope.get("more_info", "") == ""

    def test_missing_permitted_raises(self, tmp_path):
        import yaml

        from humanbound_cli.commands.connect import _load_scope_file

        # Build a file with no `permitted` key.
        bad = tmp_path / "scope.yaml"
        bad.write_text(
            yaml.safe_dump(
                {
                    "business_scope": "X",
                    "restricted": ["r"],
                }
            )
        )
        with pytest.raises(ValueError, match="permitted"):
            _load_scope_file(str(bad))

    def test_empty_business_scope_raises(self, tmp_path):
        from humanbound_cli.commands.connect import _load_scope_file

        p = tmp_path / "scope.yaml"
        p.write_text("business_scope: ''\npermitted: [a]\nrestricted: [b]\n")
        with pytest.raises(ValueError, match="business_scope"):
            _load_scope_file(str(p))

    def test_permitted_non_list_raises(self, tmp_path):
        from humanbound_cli.commands.connect import _load_scope_file

        p = tmp_path / "scope.yaml"
        p.write_text("business_scope: 'X'\npermitted: 'not-a-list'\nrestricted: [b]\n")
        with pytest.raises(ValueError, match="permitted"):
            _load_scope_file(str(p))

    def test_unreadable_file_raises(self, tmp_path):
        from humanbound_cli.commands.connect import _load_scope_file

        with pytest.raises(FileNotFoundError):
            _load_scope_file(str(tmp_path / "does_not_exist.yaml"))


# ---------------------------------------------------------------------------
# Helper: _serialize_scope_to_text
# ---------------------------------------------------------------------------


class TestSerializeScopeToText:
    def test_basic_render(self):
        from humanbound_cli.commands.connect import _serialize_scope_to_text

        text = _serialize_scope_to_text(
            {
                "business_scope": "X agent",
                "permitted": ["p1", "p2"],
                "restricted": ["r1"],
                "more_info": "extra",
            }
        )
        assert "Business scope: X agent" in text
        assert "Permitted intents:" in text
        assert "- p1" in text
        assert "- p2" in text
        assert "Restricted intents:" in text
        assert "- r1" in text
        assert "Additional context: extra" in text

    def test_empty_more_info_omits_section(self):
        from humanbound_cli.commands.connect import _serialize_scope_to_text

        text = _serialize_scope_to_text(
            {
                "business_scope": "X",
                "permitted": ["p"],
                "restricted": ["r"],
                "more_info": "",
            }
        )
        assert "Additional context" not in text

    def test_clears_min_length_threshold(self):
        from humanbound_cli.commands.connect import _serialize_scope_to_text

        # BE's TextSourceData enforces >= 10 chars after strip()
        text = _serialize_scope_to_text(
            {
                "business_scope": "X",
                "permitted": ["p"],
                "restricted": ["r"],
                "more_info": "",
            }
        )
        assert len(text.strip()) >= 10


# ---------------------------------------------------------------------------
# Helper: _diff_scope
# ---------------------------------------------------------------------------


class TestDiffScope:
    def test_returns_only_new_items(self):
        from humanbound_cli.commands.connect import _diff_scope

        user = {"permitted": ["a", "b"], "restricted": ["x"]}
        analyzed = {
            "intents": {
                "permitted": ["a", "b", "c"],
                "restricted": ["x", "y"],
            }
        }
        diff = _diff_scope(user, analyzed)
        assert diff["permitted"] == ["c"]
        assert diff["restricted"] == ["y"]

    def test_no_additions_returns_empty_lists(self):
        from humanbound_cli.commands.connect import _diff_scope

        user = {"permitted": ["a"], "restricted": ["x"]}
        analyzed = {"intents": {"permitted": ["a"], "restricted": ["x"]}}
        diff = _diff_scope(user, analyzed)
        assert diff == {"permitted": [], "restricted": []}

    def test_normalises_case_and_whitespace(self):
        from humanbound_cli.commands.connect import _diff_scope

        user = {"permitted": ["  Look Up Orders  "], "restricted": ["X"]}
        analyzed = {"intents": {"permitted": ["look up orders"], "restricted": ["x"]}}
        diff = _diff_scope(user, analyzed)
        assert diff == {"permitted": [], "restricted": []}

    def test_handles_missing_analyzed_intents(self):
        from humanbound_cli.commands.connect import _diff_scope

        user = {"permitted": ["a"], "restricted": ["b"]}
        analyzed = {}  # malformed /scan response
        diff = _diff_scope(user, analyzed)
        assert diff == {"permitted": [], "restricted": []}


# ---------------------------------------------------------------------------
# --no-test flag
# ---------------------------------------------------------------------------


class TestNoTestFlag:
    @patch(PATCH_CLIENT)
    def test_no_test_skips_auto_test(self, MockCls):
        """--no-test → project still created, but _auto_test is not called."""
        client = _make_authenticated_client()
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "Test agent",
                    "intents": {"permitted": ["p"], "restricted": ["r"]},
                },
                "risk_profile": {"risk_level": "LOW", "industry": "tech"},
                "default_integration": None,
            }
            if path == "scan"
            else {"id": "proj-new"}
        )
        MockCls.return_value = client

        endpoint_json = '{"chat_completion":{"endpoint":"https://bot.example.com"}}'
        with patch("humanbound_cli.commands.connect._auto_test") as mock_auto_test:
            result = runner.invoke(
                cli,
                ["connect", "--endpoint", endpoint_json, "--yes", "--no-test"],
            )

        assert result.exit_code == 0, result.output
        mock_auto_test.assert_not_called()
        # Project IS created
        project_calls = [c for c in client.post.call_args_list if c.args[0] == "projects"]
        assert project_calls, "project should still be created"

    @patch(PATCH_CLIENT)
    def test_no_test_hint_omits_category_when_default(self, MockCls):
        """--no-test without --test-category → Next-hint shows plain 'hb test'."""
        client = _make_authenticated_client()
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "Test agent",
                    "intents": {"permitted": ["p"], "restricted": ["r"]},
                },
                "risk_profile": {"risk_level": "LOW", "industry": "tech"},
                "default_integration": None,
            }
            if path == "scan"
            else {"id": "proj-new"}
        )
        MockCls.return_value = client

        endpoint_json = '{"chat_completion":{"endpoint":"https://bot.example.com"}}'
        with patch("humanbound_cli.commands.connect._auto_test"):
            result = runner.invoke(
                cli,
                ["connect", "--endpoint", endpoint_json, "--yes", "--no-test"],
            )

        assert result.exit_code == 0, result.output
        # Plain `hb test` appears; no --test-category in the hint
        assert "hb test" in result.output
        assert "hb test --test-category" not in result.output

    @patch(PATCH_CLIENT)
    def test_no_test_hint_includes_category_when_passed(self, MockCls):
        """--no-test --test-category <path> → Next-hint includes the path the user passed."""
        client = _make_authenticated_client()
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "Test agent",
                    "intents": {"permitted": ["p"], "restricted": ["r"]},
                },
                "risk_profile": {"risk_level": "LOW", "industry": "tech"},
                "default_integration": None,
            }
            if path == "scan"
            else {"id": "proj-new"}
        )
        MockCls.return_value = client

        endpoint_json = '{"chat_completion":{"endpoint":"https://bot.example.com"}}'
        with patch("humanbound_cli.commands.connect._auto_test"):
            result = runner.invoke(
                cli,
                [
                    "connect",
                    "--endpoint",
                    endpoint_json,
                    "--yes",
                    "--no-test",
                    "--test-category",
                    "humanbound/adversarial/owasp_single_turn",
                ],
            )

        assert result.exit_code == 0, result.output
        # The Next-hint surfaces the user's choice (note: warning above also mentions it)
        assert "hb test --test-category humanbound/adversarial/owasp_single_turn" in result.output

    @patch(PATCH_CLIENT)
    def test_no_test_plus_category_warns(self, MockCls):
        """--no-test + --test-category should print a warning and continue."""
        client = _make_authenticated_client()
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "Test agent",
                    "intents": {"permitted": ["p"], "restricted": ["r"]},
                },
                "risk_profile": {"risk_level": "LOW", "industry": "tech"},
                "default_integration": None,
            }
            if path == "scan"
            else {"id": "proj-new"}
        )
        MockCls.return_value = client

        endpoint_json = '{"chat_completion":{"endpoint":"https://bot.example.com"}}'
        with patch("humanbound_cli.commands.connect._auto_test"):
            result = runner.invoke(
                cli,
                [
                    "connect",
                    "--endpoint",
                    endpoint_json,
                    "--yes",
                    "--no-test",
                    "--test-category",
                    "humanbound/adversarial/owasp_single_turn",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "--test-category is ignored when --no-test is set" in result.output


# ---------------------------------------------------------------------------
# --test-category resolution via the CLI
# ---------------------------------------------------------------------------


class TestTestCategoryCli:
    @patch(PATCH_CLIENT)
    def test_alias_single_reaches_experiment_payload(self, MockCls):
        client = _make_authenticated_client()
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "Test agent",
                    "intents": {"permitted": ["p"], "restricted": ["r"]},
                },
                "risk_profile": {"risk_level": "LOW", "industry": "tech"},
                "default_integration": {"chat_completion": {"endpoint": "https://x"}},
            }
            if path == "scan"
            else ({"id": "exp-1"} if path == "experiments" else {"id": "proj-new"})
        )
        MockCls.return_value = client

        endpoint_json = '{"chat_completion":{"endpoint":"https://bot.example.com"}}'
        with patch("humanbound_cli.commands.connect._recommend_monitoring"):
            result = runner.invoke(
                cli,
                [
                    "connect",
                    "--endpoint",
                    endpoint_json,
                    "--yes",
                    "--test-category",
                    "humanbound/adversarial/owasp_single_turn",
                ],
            )

        assert result.exit_code == 0, result.output
        exp_calls = [c for c in client.post.call_args_list if c.args[0] == "experiments"]
        assert exp_calls, "expected POST /experiments"
        payload = exp_calls[0].kwargs.get("data") or exp_calls[0].args[1]
        assert payload["test_category"] == "humanbound/adversarial/owasp_single_turn"


# ---------------------------------------------------------------------------
# --scope flag
# ---------------------------------------------------------------------------


class TestScopeFlag:
    @patch(PATCH_CLIENT)
    def test_scope_only_sends_text_source(self, MockCls, tmp_path):
        """--scope alone → /scan called with a single text source, project created."""
        client = _make_authenticated_client()
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "Customer support agent",
                    "intents": {
                        "permitted": [
                            "Look up order status for the authenticated customer",
                        ],
                        "restricted": [
                            "Quote a refund amount before the return is inspected",
                        ],
                    },
                },
                "risk_profile": {"risk_level": "LOW", "industry": "retail"},
                "default_integration": None,
            }
            if path == "scan"
            else {"id": "proj-new"}
        )
        MockCls.return_value = client

        with (
            patch("humanbound_cli.commands.connect._auto_test"),
            patch("humanbound_cli.commands.connect._recommend_monitoring"),
        ):
            result = runner.invoke(
                cli,
                ["connect", "--scope", _write_scope_yaml(tmp_path), "--yes"],
            )

        assert result.exit_code == 0, result.output
        scan_calls = [c for c in client.post.call_args_list if c.args[0] == "scan"]
        assert scan_calls, "POST /scan should have been invoked"
        scan_payload = scan_calls[0].kwargs.get("data") or scan_calls[0].args[1]
        sources = scan_payload["sources"]
        assert len(sources) == 1
        assert sources[0]["source"] == "text"
        # The text source must include the user's business scope
        assert "Customer support agent" in sources[0]["data"]["text"]

    @patch(PATCH_CLIENT)
    def test_scope_with_endpoint_excludes_endpoint_source(self, MockCls, tmp_path):
        """--scope + --endpoint → /scan still text-only; default_integration set locally."""
        client = _make_authenticated_client()
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "Customer support agent",
                    "intents": {"permitted": ["p"], "restricted": ["r"]},
                },
                "risk_profile": {"risk_level": "LOW", "industry": "retail"},
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
                cli,
                [
                    "connect",
                    "--scope",
                    _write_scope_yaml(tmp_path),
                    "--endpoint",
                    endpoint_json,
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        scan_calls = [c for c in client.post.call_args_list if c.args[0] == "scan"]
        scan_payload = scan_calls[0].kwargs.get("data") or scan_calls[0].args[1]
        sources = scan_payload["sources"]
        source_types = [s["source"] for s in sources]
        assert source_types == ["text"], f"expected ['text'], got {source_types}"

        # Project payload should carry default_integration from --endpoint
        project_calls = [c for c in client.post.call_args_list if c.args[0] == "projects"]
        proj_payload = project_calls[0].kwargs.get("data") or project_calls[0].args[1]
        assert (
            proj_payload["default_integration"]["chat_completion"]["endpoint"]
            == "https://bot.example.com"
        )

    @patch(PATCH_CLIENT)
    def test_scope_proposals_displayed_and_merged(self, MockCls, tmp_path):
        """When /scan returns additional intents, they're displayed and merged on accept."""
        client = _make_authenticated_client()
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "ignored",
                    "intents": {
                        # Adds one extra permitted, one extra restricted
                        "permitted": [
                            "Look up order status for the authenticated customer",
                            "Generate weekly summary reports",
                        ],
                        "restricted": [
                            "Quote a refund amount before the return is inspected",
                            "Disclose internal pricing models",
                        ],
                    },
                },
                "risk_profile": {"risk_level": "LOW", "industry": "retail"},
                "default_integration": None,
            }
            if path == "scan"
            else {"id": "proj-new"}
        )
        MockCls.return_value = client

        with (
            patch("humanbound_cli.commands.connect._auto_test"),
            patch("humanbound_cli.commands.connect._recommend_monitoring"),
        ):
            result = runner.invoke(
                cli,
                ["connect", "--scope", _write_scope_yaml(tmp_path), "--yes"],
            )

        assert result.exit_code == 0, result.output
        # Proposal panel appears
        assert "Generate weekly summary reports" in result.output
        assert "Disclose internal pricing models" in result.output

        # Merged scope arrives at /projects: user's items + accepted additions
        project_calls = [c for c in client.post.call_args_list if c.args[0] == "projects"]
        proj_payload = project_calls[0].kwargs.get("data") or project_calls[0].args[1]
        permitted = proj_payload["scope"]["intents"]["permitted"]
        restricted = proj_payload["scope"]["intents"]["restricted"]
        assert "Look up order status for the authenticated customer" in permitted
        assert "Generate weekly summary reports" in permitted
        assert "Disclose internal pricing models" in restricted
        # User's business_scope wins (from the helper-built scope)
        assert proj_payload["scope"]["overall_business_scope"].startswith(
            "Customer support agent for an online retailer"
        )

    @patch(PATCH_CLIENT)
    def test_scope_bad_file_exits_with_error(self, MockCls, tmp_path):
        """A scope file missing 'permitted' exits with code 1 and a clear message."""
        import yaml

        MockCls.return_value = _make_authenticated_client()
        bad = tmp_path / "scope.yaml"
        bad.write_text(
            yaml.safe_dump(
                {
                    "business_scope": "X",
                    "restricted": ["r"],
                }
            )
        )
        result = runner.invoke(
            cli,
            ["connect", "--scope", str(bad), "--yes"],
        )
        assert result.exit_code != 0
        assert "permitted" in result.output.lower()

    @patch(PATCH_CLIENT)
    def test_scope_plus_prompt_warns(self, MockCls, tmp_path):
        """--scope + --prompt → warning printed, --prompt ignored, flow proceeds."""
        client = _make_authenticated_client()
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "x",
                    "intents": {"permitted": ["p"], "restricted": ["r"]},
                },
                "risk_profile": {"risk_level": "LOW", "industry": "x"},
                "default_integration": None,
            }
            if path == "scan"
            else {"id": "proj-new"}
        )
        MockCls.return_value = client

        scope_file = _write_scope_yaml(tmp_path)
        with (
            patch("humanbound_cli.commands.connect._auto_test"),
            patch("humanbound_cli.commands.connect._recommend_monitoring"),
        ):
            result = runner.invoke(
                cli,
                [
                    "connect",
                    "--scope",
                    scope_file,
                    "--prompt",
                    scope_file,
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "--prompt" in result.output and "ignored" in result.output.lower()


# ---------------------------------------------------------------------------
# init telemetry payload
# ---------------------------------------------------------------------------


class TestInitTelemetry:
    @patch(PATCH_CLIENT)
    @patch("humanbound_cli.commands.connect.telemetry.capture")
    def test_init_event_includes_new_fields(self, mock_capture, MockCls):
        """init telemetry event should carry test_category, no_test, scope_provided."""
        client = _make_authenticated_client()
        client.post.side_effect = lambda path, **kwargs: (
            {
                "scope": {
                    "overall_business_scope": "Test agent",
                    "intents": {"permitted": ["p"], "restricted": ["r"]},
                },
                "risk_profile": {"risk_level": "LOW", "industry": "x"},
                "default_integration": None,
            }
            if path == "scan"
            else {"id": "proj-new"}
        )
        MockCls.return_value = client

        endpoint_json = '{"chat_completion":{"endpoint":"https://bot.example.com"}}'
        with patch("humanbound_cli.commands.connect._auto_test"):
            result = runner.invoke(
                cli,
                [
                    "connect",
                    "--endpoint",
                    endpoint_json,
                    "--yes",
                    "--no-test",
                    "--test-category",
                    "humanbound/adversarial/owasp_single_turn",
                ],
            )

        assert result.exit_code == 0, result.output
        init_calls = [c for c in mock_capture.call_args_list if c.args[0] == "init"]
        assert init_calls, "init telemetry event should fire"
        payload = init_calls[0].args[1]
        assert payload["no_test"] is True
        assert payload["test_category"] == "humanbound/adversarial/owasp_single_turn"
        assert payload["scope_provided"] is False
