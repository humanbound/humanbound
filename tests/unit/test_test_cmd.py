"""Unit tests for the `hb test` command.

All mocked — no live API. The command goes through ``get_runner().start(config)``,
so we patch ``get_runner`` and assert on the ``TestConfig`` passed to
``runner.start(...)``.
"""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from conftest import (
    MOCK_PROJECT,
    MOCK_PROVIDER,
    assert_exit_error,
    assert_exit_ok,
    platform_runner,
)

from humanbound_cli.exceptions import APIError
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
