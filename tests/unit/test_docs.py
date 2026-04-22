"""
Unit tests for `hb docs` command.

No HumanboundClient needed — docs doesn't require auth.
We patch webbrowser.open to prevent actual browser launches.
"""

from unittest.mock import patch

from click.testing import CliRunner

from humanbound_cli.main import cli

runner = CliRunner()

BROWSER_PATCH = "humanbound_cli.commands.docs.webbrowser.open"


class TestHappyPath:
    def test_docs_help(self):
        """docs --help shows usage and topics."""
        result = runner.invoke(cli, ["docs", "--help"])
        assert result.exit_code == 0
        assert "TOPIC" in result.output or "topic" in result.output.lower()
        assert "--list" in result.output
        assert "--no-browser" in result.output

    @patch(BROWSER_PATCH)
    def test_docs_default_opens_home(self, mock_browser):
        """docs without args opens the home documentation."""
        result = runner.invoke(cli, ["docs"])
        assert result.exit_code == 0
        mock_browser.assert_called_once()
        url_arg = mock_browser.call_args[0][0]
        assert "docs.humanbound.ai" in url_arg

    @patch(BROWSER_PATCH)
    def test_docs_cli_topic(self, mock_browser):
        """docs cli opens CLI reference."""
        result = runner.invoke(cli, ["docs", "cli"])
        assert result.exit_code == 0
        mock_browser.assert_called_once()
        url_arg = mock_browser.call_args[0][0]
        assert "cli" in url_arg

    def test_docs_cli_no_browser(self):
        """docs cli --no-browser shows URL without opening browser."""
        result = runner.invoke(cli, ["docs", "cli", "--no-browser"])
        assert result.exit_code == 0
        assert "docs.humanbound.ai/cli" in result.output

    def test_docs_api_no_browser(self):
        """docs api --no-browser shows API docs URL."""
        result = runner.invoke(cli, ["docs", "api", "--no-browser"])
        assert result.exit_code == 0
        assert "docs.humanbound.ai/api" in result.output

    def test_docs_list(self):
        """docs --list shows all topics in a table."""
        result = runner.invoke(cli, ["docs", "--list"])
        assert result.exit_code == 0
        assert "home" in result.output.lower()
        assert "cli" in result.output.lower()
        assert "api" in result.output.lower()
        assert "quickstart" in result.output.lower()
        assert "owasp" in result.output.lower()
        assert "firewall" in result.output.lower()

    @patch(BROWSER_PATCH)
    def test_docs_all_topics_valid(self, mock_browser):
        """Each known topic opens without error."""
        topics = ["home", "quickstart", "cli", "api", "owasp", "firewall", "examples", "github"]
        for topic in topics:
            mock_browser.reset_mock()
            result = runner.invoke(cli, ["docs", topic])
            assert result.exit_code == 0, f"Topic '{topic}' failed: {result.output}"
            mock_browser.assert_called_once()

    @patch(BROWSER_PATCH)
    def test_docs_browser_error_shows_url(self, mock_browser):
        """If browser.open raises, the URL is still shown."""
        mock_browser.side_effect = Exception("No display")
        result = runner.invoke(cli, ["docs", "cli"])
        assert result.exit_code == 0
        # Should show the URL as fallback
        assert "docs.humanbound.ai" in result.output


class TestErrorCases:
    def test_docs_unknown_topic(self):
        """docs with unknown topic exits with error."""
        result = runner.invoke(cli, ["docs", "nonexistent_topic_xyz"])
        assert result.exit_code != 0
        assert "Unknown topic" in result.output or "unknown" in result.output.lower()

    def test_docs_another_unknown_topic(self):
        """docs with another unknown topic exits with error."""
        result = runner.invoke(cli, ["docs", "foobar"])
        assert result.exit_code != 0
