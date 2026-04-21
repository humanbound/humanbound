# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Shell tab-completion setup for the hb CLI."""

import os
import subprocess

import click


_SHELL_ENV_VARS = {
    "bash": "_HB_COMPLETE=bash_source",
    "zsh": "_HB_COMPLETE=zsh_source",
    "fish": "_HB_COMPLETE=fish_source",
}

_INSTALL_HINTS = {
    "bash": 'eval "$(hb completion bash)"  # or: hb completion bash >> ~/.bashrc',
    "zsh": 'eval "$(hb completion zsh)"   # or: hb completion zsh >> ~/.zshrc',
    "fish": "hb completion fish > ~/.config/fish/completions/hb.fish",
}


def _detect_shell() -> str | None:
    """Detect the current shell from $SHELL."""
    shell_path = os.environ.get("SHELL", "")
    basename = os.path.basename(shell_path)
    if basename in _SHELL_ENV_VARS:
        return basename
    return None


@click.command("completion")
@click.argument("shell", required=False, type=click.Choice(["bash", "zsh", "fish"]))
def completion_command(shell: str | None):
    """Enable shell tab completion for hb.

    Prints the completion script for your shell. Add it to your profile:

    \b
      hb completion bash >> ~/.bashrc
      hb completion zsh  >> ~/.zshrc
      hb completion fish > ~/.config/fish/completions/hb.fish
    """
    if not shell:
        shell = _detect_shell()
        if not shell:
            raise click.ClickException(
                "Could not detect shell. Specify one explicitly: hb completion bash|zsh|fish"
            )

    env_var = _SHELL_ENV_VARS[shell]
    key, value = env_var.split("=", 1)

    env = {**os.environ, key: value}
    result = subprocess.run(
        ["hb"],
        env=env,
        capture_output=True,
        text=True,
    )

    if result.stdout:
        click.echo(result.stdout)
    else:
        raise click.ClickException(
            f"Failed to generate {shell} completion script. "
            "Make sure 'hb' is installed and on your PATH."
        )

    click.echo(f"# Add to your profile: {_INSTALL_HINTS[shell]}", err=True)
