"""Unit tests for the `hb test` command.

All mocked — no live API. The command goes through ``get_runner().start(config)``,
so we patch ``get_runner`` and assert on the ``TestConfig`` passed to
``runner.start(...)``.
"""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from conftest import (
    MOCK_PROJECT,
    MOCK_PROVIDER,
    assert_exit_error,
    assert_exit_ok,
    local_runner,
    platform_runner,
)

from humanbound_cli.exceptions import APIError, NotAuthenticatedError
from humanbound_cli.main import cli

RUNNER_PATCH = "humanbound_cli.commands.test.get_runner"
runner = CliRunner()


def _make_client(**overrides):
    m = MagicMock()
    m.is_authenticated.return_value = True
    m.organisation_id = "org-123"
    m.project_id = "proj-456"
    m._organisation_id = "org-123"
    m._project_id = "proj-456"
    m.base_url = "http://test.local/api"
    m.list_providers.return_value = [MOCK_PROVIDER]
    m.get.return_value = MOCK_PROJECT
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


def _started_config(runner_mock):
    """Extract the TestConfig argument passed to runner.start(config)."""
    assert runner_mock.start.called, "runner.start() was not called"
    return runner_mock.start.call_args[0][0]


# ─────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────


class TestHappyPath:
    @patch(RUNNER_PATCH)
    def test_basic_invocation(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client, experiment_id="exp-new")
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test"])

        assert_exit_ok(result)
        r.start.assert_called_once()
        assert "exp-new" in result.output

    @patch(RUNNER_PATCH)
    def test_deep_flag_sets_system_level(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--deep"])

        assert_exit_ok(result)
        assert _started_config(r).testing_level == "system"

    @patch(RUNNER_PATCH)
    def test_full_flag_sets_acceptance_level(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--full"])

        assert_exit_ok(result)
        assert _started_config(r).testing_level == "acceptance"

    @patch(RUNNER_PATCH)
    def test_quick_flag_keeps_unit_level(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--quick"])

        assert_exit_ok(result)
        assert _started_config(r).testing_level == "unit"

    @patch(RUNNER_PATCH)
    def test_quick_does_not_downgrade_explicit_level(self, mock_get_runner):
        """--quick maps to the default unit depth; an explicit --testing-level
        must win rather than being silently downgraded to unit."""
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--testing-level", "system", "--quick"])

        assert_exit_ok(result)
        assert _started_config(r).testing_level == "system"

    @patch(RUNNER_PATCH)
    def test_conflicting_depth_flags_quick_wins(self, mock_get_runner):
        """Depth shortcuts resolve first-match-wins (quick > deep > full), so
        combining all three deterministically yields the quick/unit level."""
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--quick", "--deep", "--full"])

        assert_exit_ok(result)
        assert _started_config(r).testing_level == "unit"

    @patch(RUNNER_PATCH)
    def test_no_auto_start(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--no-auto-start"])

        assert_exit_ok(result)
        assert _started_config(r).auto_start is False


# ─────────────────────────────────────────────────────────────────────────
# Error cases
# ─────────────────────────────────────────────────────────────────────────


class TestErrorCases:
    @patch(RUNNER_PATCH)
    def test_api_error_on_creation(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        r.start.side_effect = APIError("Quota exceeded", 402)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test"])

        assert_exit_error(result)


# ─────────────────────────────────────────────────────────────────────────
# Flag propagation
# ─────────────────────────────────────────────────────────────────────────


class TestFlags:
    @patch(RUNNER_PATCH)
    def test_test_category_flag(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(
            cli,
            [
                "test",
                "--test-category",
                "humanbound/behavioral/qa",
            ],
        )

        assert_exit_ok(result)
        assert _started_config(r).test_category == "humanbound/behavioral/qa"

    @patch(RUNNER_PATCH)
    def test_omitted_flags_are_none_so_backend_default_applies(self, mock_get_runner):
        """`hb test` with no category/level/lang flags must hand the runner a
        TestConfig with those fields as None, so the request body omits them
        and the platform-side default is used."""
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test"])

        assert_exit_ok(result)
        cfg = _started_config(r)
        assert cfg.test_category is None
        assert cfg.testing_level is None
        assert cfg.lang is None

    @patch(RUNNER_PATCH)
    def test_testing_level_flag(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--testing-level", "system"])

        assert_exit_ok(result)
        assert _started_config(r).testing_level == "system"

    @patch(RUNNER_PATCH)
    def test_name_flag(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--name", "nightly-smoke"])

        assert_exit_ok(result)
        assert _started_config(r).name == "nightly-smoke"

    @patch(RUNNER_PATCH)
    def test_description_flag(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(
            cli,
            [
                "test",
                "--description",
                "Smoke test after deploy",
            ],
        )

        assert_exit_ok(result)
        assert _started_config(r).description == "Smoke test after deploy"

    @patch(RUNNER_PATCH)
    def test_lang_flag_passed_through(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--lang", "de"])

        assert_exit_ok(result)
        # The config carries whatever the CLI resolved; tolerate either the
        # code ('de') or the fully-qualified name ('german').
        lang = _started_config(r).lang.lower()
        assert lang in {"de", "german", "deutsch"}

    @patch(RUNNER_PATCH)
    def test_context_string_passed(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        result = runner.invoke(
            cli,
            [
                "test",
                "--context",
                "Tenant: acme-corp",
            ],
        )

        assert_exit_ok(result)
        assert _started_config(r).context == "Tenant: acme-corp"

    @patch(RUNNER_PATCH)
    def test_context_long_literal_does_not_crash(self, mock_get_runner):
        """Regression: long multi-line --context strings used to crash at
        `Path(context).is_file()` with OSError: File name too long (errno 63).
        The fix wraps the stat call in try/except and treats an OSError as
        'not a path'."""
        client = _make_client()
        r = platform_runner(client)
        mock_get_runner.return_value = r

        long_context = (
            "Authenticated as Bob Smith (CUST-002), premium segment, KYC verified.\n"
            "Account: ACC-002, Card ID: CARD-002\n\n"
            "Boundary test data:\n"
            "- ACC-001 belongs to Alice Johnson (should be inaccessible)\n"
            "- ACC-003 belongs to Charlie Davis (should be inaccessible)\n"
            "- Bob's daily transfer limit: 5,000 EUR"
        )

        result = runner.invoke(cli, ["test", "--context", long_context])

        assert_exit_ok(result)
        assert _started_config(r).context == long_context


class TestExitCodeContract:
    @patch(RUNNER_PATCH)
    def test_exit_code_contract_unchanged_without_flag(self, mock_get_runner):
        """No-op proof: identical to test_basic_invocation — plain `hb test`
        must still run immediate mode and hit the normal exit-code contract."""
        client = _make_client()
        r = platform_runner(client, experiment_id="exp-new")
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test"])

        assert_exit_ok(result)
        r.start.assert_called_once()
        assert "exp-new" in result.output
        assert "staged" not in result.output.lower()


class TestPostureFetch:
    @pytest.mark.parametrize(
        "error",
        [
            APIError("Internal Server Error", status_code=500),
            NotAuthenticatedError("Not authenticated. Please run 'hb login' first."),
            APIError("Internal error [/data] missing", status_code=500),
        ],
    )
    @patch("humanbound_cli.commands.test.time.sleep")
    @patch(RUNNER_PATCH)
    def test_posture_fetch_failure_is_reported(self, mock_get_runner, _sleep, error):
        r = platform_runner(_make_client(), experiment_id="exp-new")
        r.get_posture.side_effect = error
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--wait"])

        assert_exit_ok(result)
        assert "Could not fetch posture from the platform" in result.output
        assert "Experiment Complete" in result.output


# ─────────────────────────────────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────────────────────────────────


class TestOutputFormat:
    def test_help_text(self):
        # --help short-circuits before get_runner is built.
        result = runner.invoke(cli, ["test", "--help"])
        assert_exit_ok(result)
        assert "security tests" in result.output.lower() or "test" in result.output.lower()

    @patch(RUNNER_PATCH)
    def test_output_includes_experiment_id(self, mock_get_runner):
        client = _make_client()
        r = platform_runner(client, experiment_id="exp-abc123")
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--no-auto-start"])

        assert_exit_ok(result)
        assert "exp-abc123" in result.output


# ─────────────────────────────────────────────────────────────────────────
# Arena targets (hb test --target arena://<id>)
# ─────────────────────────────────────────────────────────────────────────

RESOLVE_PATCH = "humanbound_cli.arena.target.resolve_target"
RESET_PATCH = "humanbound_cli.arena.target.reset_via_gateway"
BASELINE_PATCH = "humanbound_cli.arena.target.enforce_baseline"
ARENA_GATEWAY = "http://127.0.0.1:8475"
ARENA_TOKEN = "arena-gateway-token-SECRET-never-saved-0000"


def _arena_target(tmp_path, context="You are Pricer; prices are public.", whitebox=True):
    from humanbound_cli.arena.target import ArenaTarget, bot_config

    scope = tmp_path / "scope.yaml"
    scope.write_text("permitted: []\nrestricted: []\n")
    return ArenaTarget(
        agent_id="pricer",
        gateway=ARENA_GATEWAY,
        bot_config=bot_config("pricer", ARENA_GATEWAY, token=ARENA_TOKEN),
        scope_path=scope,
        context=context,
        whitebox=whitebox,
        version="1.2.0",
    )


@pytest.fixture(autouse=True)
def _baseline_met(monkeypatch):
    """Arena runs never reach Docker here: the container baseline is met unless a test says
    otherwise (it patches BASELINE_PATCH or the runtime underneath). Returns the real check."""
    from humanbound_cli.arena import target

    real = target.enforce_baseline
    monkeypatch.setattr(target, "enforce_baseline", lambda arena: None)
    return real


def _local_runner_mock():
    r = local_runner()
    r.start.return_value = None
    return r


class TestArenaTarget:
    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_target_forces_local_and_builds_whitebox_config(
        self, mock_get_runner, mock_resolve, mock_reset, tmp_path
    ):
        target = _arena_target(tmp_path)
        mock_resolve.return_value = target
        r = _local_runner_mock()
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--target", "arena://pricer"])

        mock_get_runner.assert_called_once_with(force_local=True)
        mock_resolve.assert_called_once_with("arena://pricer")
        config = _started_config(r)
        assert config.endpoint == target.bot_config
        assert config.scope_path == str(target.scope_path)
        assert config.context == target.context
        assert "whitebox" in result.output
        mock_reset.assert_called_once_with("pricer", ARENA_GATEWAY)
        # What a benchmark needs to know about the tested agent (saved in meta.json).
        assert config.target == {
            "kind": "arena",
            "agent_id": "pricer",
            "agent_version": "1.2.0",
            "gateway": ARENA_GATEWAY,
            "whitebox": True,
        }

    @pytest.mark.parametrize(
        "default_catalog, props",
        [(True, {"agent": "pricer", "version": "1.2.0"}), (False, {"agent": "custom"})],
    )
    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_arena_test_event_names_only_default_catalog_agents(
        self,
        mock_get_runner,
        mock_resolve,
        mock_reset,
        default_catalog,
        props,
        tmp_path,
        monkeypatch,
    ):
        import dataclasses

        captured = []
        monkeypatch.setattr(
            "humanbound_cli.telemetry.capture",
            lambda event, props=None: captured.append((event, props)),
        )
        mock_resolve.return_value = dataclasses.replace(
            _arena_target(tmp_path), default_catalog=default_catalog
        )
        mock_get_runner.return_value = _local_runner_mock()

        runner.invoke(cli, ["test", "--target", "arena://pricer"])

        assert ("arena_test", props) in captured
        assert ARENA_TOKEN not in repr(captured)  # the gateway token never reaches telemetry

    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_agent_without_tool_calls_is_labelled_blackbox(
        self, mock_get_runner, mock_resolve, mock_reset, tmp_path
    ):
        mock_resolve.return_value = _arena_target(tmp_path, whitebox=False)
        mock_get_runner.return_value = _local_runner_mock()

        result = runner.invoke(cli, ["test", "--target", "arena://pricer"])

        assert "blackbox" in result.output
        assert "whitebox" not in result.output

    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_manifest_context_is_used_literally(
        self, mock_get_runner, mock_resolve, mock_reset, tmp_path
    ):
        # A manifest context that happens to be the path of an existing file
        # must NOT be read as a file.
        existing = tmp_path / "secret.txt"
        existing.write_text("FILE CONTENTS")
        target = _arena_target(tmp_path, context=str(existing))
        mock_resolve.return_value = target
        r = _local_runner_mock()
        mock_get_runner.return_value = r

        runner.invoke(cli, ["test", "--target", "arena://pricer"])

        assert _started_config(r).context == str(existing)

    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_user_context_file_is_still_read(
        self, mock_get_runner, mock_resolve, mock_reset, tmp_path
    ):
        mock_resolve.return_value = _arena_target(tmp_path)
        r = _local_runner_mock()
        mock_get_runner.return_value = r
        ctx_file = tmp_path / "ctx.txt"
        ctx_file.write_text("  from the user file  ")

        runner.invoke(cli, ["test", "--target", "arena://pricer", "--context", str(ctx_file)])

        assert _started_config(r).context == "from the user file"

    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_explicit_scope_wins(self, mock_get_runner, mock_resolve, mock_reset, tmp_path):
        mock_resolve.return_value = _arena_target(tmp_path)
        r = _local_runner_mock()
        mock_get_runner.return_value = r
        own = tmp_path / "own-scope.yaml"
        own.write_text("permitted: []\n")

        runner.invoke(cli, ["test", "--target", "arena://pricer", "--scope", str(own)])

        assert _started_config(r).scope_path == str(own)

    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_reset_failure_exits_2(self, mock_get_runner, mock_resolve, mock_reset, tmp_path):
        from humanbound_cli.arena.target import TargetError

        mock_resolve.return_value = _arena_target(tmp_path)
        mock_reset.side_effect = TargetError("reset endpoint exploded")
        r = _local_runner_mock()
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--target", "arena://pricer"])

        assert_exit_error(result, 2)
        assert "reset endpoint exploded" in result.output
        r.start.assert_not_called()

    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_not_running_exits_2_with_hint(self, mock_get_runner, mock_resolve):
        from humanbound_cli.arena.target import TargetError

        mock_resolve.side_effect = TargetError("pricer is not running → hb arena run pricer")

        result = runner.invoke(cli, ["test", "--target", "arena://pricer"])

        assert_exit_error(result, 2)
        assert "hb arena run pricer" in result.output
        mock_get_runner.assert_not_called()

    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_target_and_endpoint_conflict(self, mock_get_runner, mock_resolve):
        result = runner.invoke(cli, ["test", "--target", "arena://pricer", "--endpoint", "{}"])

        assert_exit_error(result, 2)
        assert "--target or --endpoint" in result.output
        mock_resolve.assert_not_called()
        mock_get_runner.assert_not_called()

    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_non_arena_target_rejected(self, mock_get_runner, mock_resolve):
        result = runner.invoke(cli, ["test", "--target", "http://example.com/agent"])

        assert_exit_error(result, 2)
        assert "arena://" in result.output
        mock_resolve.assert_not_called()
        mock_get_runner.assert_not_called()


class TestArenaBaseline:
    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_baseline_is_checked_after_the_reset_and_before_the_experiment(
        self, mock_get_runner, mock_resolve, mock_reset, tmp_path, monkeypatch
    ):
        from humanbound_cli.arena import target

        order = []
        mock_resolve.return_value = _arena_target(tmp_path)
        mock_reset.side_effect = lambda *a: order.append("reset")
        monkeypatch.setattr(target, "enforce_baseline", lambda t: order.append(("check", t)))
        r = _local_runner_mock()
        r.start.side_effect = lambda config: order.append("start")
        mock_get_runner.return_value = r

        runner.invoke(cli, ["test", "--target", "arena://pricer"])

        assert order == ["reset", ("check", mock_resolve.return_value), "start"]

    @pytest.mark.parametrize("flag", ["--no-reset", "--no-auto-start"])
    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_baseline_is_checked_without_a_reset_too(
        self, mock_get_runner, mock_resolve, mock_reset, flag, tmp_path, monkeypatch
    ):
        from humanbound_cli.arena import target

        checked = []
        mock_resolve.return_value = _arena_target(tmp_path)
        monkeypatch.setattr(target, "enforce_baseline", lambda t: checked.append(t.agent_id))
        r = _local_runner_mock()
        mock_get_runner.return_value = r

        runner.invoke(cli, ["test", "--target", "arena://pricer", flag])

        mock_reset.assert_not_called()
        assert checked == ["pricer"]
        r.start.assert_called_once()

    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_baseline_violations_stop_the_agent_and_exit_2(
        self, mock_get_runner, mock_resolve, mock_reset, tmp_path, monkeypatch, _baseline_met
    ):
        from humanbound_cli.arena import runtime, target
        from humanbound_cli.arena.baseline import Violation

        # the real check (not the autouse fixture's stand-in), on faked Docker data
        monkeypatch.setattr(target, "enforce_baseline", _baseline_met)
        violations = [
            Violation("arena-x-pricer", "non-root", "runs as root (Config.User is 'root')"),
            Violation("arena-x-pricer-db-1", "host-mounts", "mounts the host path /etc"),
        ]
        stopped = []
        monkeypatch.setattr(runtime, "check_baseline", lambda agent_id: violations)
        monkeypatch.setattr(
            runtime, "stop", lambda agent_id, kind, **kw: stopped.append((agent_id, kind))
        )
        mock_resolve.return_value = _arena_target(tmp_path)
        r = _local_runner_mock()
        mock_get_runner.return_value = r

        result = runner.invoke(cli, ["test", "--target", "arena://pricer"])

        assert_exit_error(result, 2)
        for v in violations:
            assert str(v) in result.output
        assert "container baseline" in result.output
        assert stopped == [("pricer", "image")]
        r.start.assert_not_called()


class TestLocalRunJoin:
    @patch("humanbound_cli.commands.test._display_results")
    @patch("humanbound_cli.commands.test._wait_for_completion", return_value="Finished")
    @patch("humanbound_cli.commands.test._join_local_run")
    @patch(RESET_PATCH)
    @patch(RESOLVE_PATCH)
    @patch(RUNNER_PATCH)
    def test_local_worker_is_joined_before_results_are_read(
        self,
        mock_get_runner,
        mock_resolve,
        mock_reset,
        mock_join,
        mock_wait,
        mock_display,
        tmp_path,
    ):
        from humanbound_cli.engine.runner import TestResult

        order = []
        mock_resolve.return_value = _arena_target(tmp_path)
        r = local_runner()
        r.start.return_value = "exp-1"
        r.get_result.side_effect = lambda eid: (
            order.append("result")
            or TestResult(
                experiment_id=eid, name="x", status="Finished", stats={"pass": 1, "total": 1}
            )
        )
        mock_join.side_effect = lambda run, eid: order.append(("join", eid))
        mock_get_runner.return_value = r

        runner.invoke(cli, ["test", "--target", "arena://pricer"])

        assert order[:2] == [("join", "exp-1"), "result"]
