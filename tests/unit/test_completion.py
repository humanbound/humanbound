"""
Unit tests for `hb completion` command.

No HumanboundClient needed — completion doesn't require auth.
We patch subprocess.run to avoid actually invoking the shell.
"""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from humanbound_cli.main import cli

runner = CliRunner()

SUBPROCESS_PATCH = "humanbound_cli.commands.completion.subprocess.run"

MOCK_BASH_COMPLETION = """
_hb_completion() {
    local IFS=$'\\n'
    COMPREPLY=( $(compgen -W "$(echo "$1")" -- "$2") )
}
complete -o default -F _hb_completion hb
"""

MOCK_ZSH_COMPLETION = """
#compdef hb
_hb() {
    eval $(env _HB_COMPLETE=zsh_source hb)
}
compdef _hb hb
"""


class TestHappyPath:
    def test_completion_help(self):
        """completion --help shows usage and shell choices."""
        result = runner.invoke(cli, ["completion", "--help"])
        assert result.exit_code == 0
        assert "bash" in result.output.lower()
        assert "zsh" in result.output.lower()
        assert "fish" in result.output.lower()

    @patch(SUBPROCESS_PATCH)
    def test_completion_bash(self, mock_run):
        """completion bash outputs bash completion script."""
        mock_result = MagicMock()
        mock_result.stdout = MOCK_BASH_COMPLETION
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = runner.invoke(cli, ["completion", "bash"])
        assert result.exit_code == 0
        assert "_hb_completion" in result.output or "hb" in result.output
        mock_run.assert_called_once()
        # Verify the env var was set for bash
        call_kwargs = mock_run.call_args
        env = call_kwargs[1].get("env") or call_kwargs.kwargs.get("env", {})
        assert env.get("_HB_COMPLETE") == "bash_source"

    @patch(SUBPROCESS_PATCH)
    def test_completion_zsh(self, mock_run):
        """completion zsh outputs zsh completion script."""
        mock_result = MagicMock()
        mock_result.stdout = MOCK_ZSH_COMPLETION
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = runner.invoke(cli, ["completion", "zsh"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        env = call_kwargs[1].get("env") or call_kwargs.kwargs.get("env", {})
        assert env.get("_HB_COMPLETE") == "zsh_source"

    @patch(SUBPROCESS_PATCH)
    def test_completion_fish(self, mock_run):
        """completion fish outputs fish completion script."""
        mock_result = MagicMock()
        mock_result.stdout = "complete -c hb -f"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = runner.invoke(cli, ["completion", "fish"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        env = call_kwargs[1].get("env") or call_kwargs.kwargs.get("env", {})
        assert env.get("_HB_COMPLETE") == "fish_source"

    @patch(SUBPROCESS_PATCH)
    @patch.dict("os.environ", {"SHELL": "/bin/bash"})
    def test_completion_auto_detect_bash(self, mock_run):
        """completion without arg auto-detects bash from $SHELL."""
        mock_result = MagicMock()
        mock_result.stdout = MOCK_BASH_COMPLETION
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = runner.invoke(cli, ["completion"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch(SUBPROCESS_PATCH)
    @patch.dict("os.environ", {"SHELL": "/bin/zsh"})
    def test_completion_auto_detect_zsh(self, mock_run):
        """completion without arg auto-detects zsh from $SHELL."""
        mock_result = MagicMock()
        mock_result.stdout = MOCK_ZSH_COMPLETION
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = runner.invoke(cli, ["completion"])
        assert result.exit_code == 0
        mock_run.assert_called_once()


class TestErrorCases:
    @patch(SUBPROCESS_PATCH)
    def test_completion_empty_output_fails(self, mock_run):
        """completion fails when subprocess returns no output."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = runner.invoke(cli, ["completion", "bash"])
        assert result.exit_code != 0
        assert "Failed" in result.output or "Error" in result.output

    @patch.dict("os.environ", {"SHELL": "/usr/bin/unknown_shell"}, clear=False)
    def test_completion_no_shell_detected(self):
        """completion without arg fails when shell cannot be detected."""
        # Temporarily override SHELL to something unrecognizable
        import os

        old_shell = os.environ.get("SHELL")
        os.environ["SHELL"] = "/usr/bin/unknown_shell"
        try:
            result = runner.invoke(cli, ["completion"])
            assert result.exit_code != 0
            assert "Could not detect shell" in result.output or "detect" in result.output.lower()
        finally:
            if old_shell:
                os.environ["SHELL"] = old_shell
            elif "SHELL" in os.environ:
                del os.environ["SHELL"]

    def test_completion_invalid_shell_choice(self):
        """completion with invalid shell name exits with error."""
        result = runner.invoke(cli, ["completion", "powershell"])
        assert result.exit_code != 0
        assert (
            "Invalid value" in result.output
            or "invalid" in result.output.lower()
            or "Choice" in result.output
        )
