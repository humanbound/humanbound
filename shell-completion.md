# Shell Completion

The `hb completion` command emits a shell completion script for bash, zsh, or fish — append it to your shell's rc file once and every subsequent shell gets tab completion for `hb` commands and flags. If you don't pass a shell argument, the CLI auto-detects from `$SHELL`. Setup takes one line per shell; restart your shell or source the rc file for changes to take effect.

## Setup

```bash
# Bash
hb completion bash >> ~/.bashrc

# Zsh
hb completion zsh >> ~/.zshrc

# Fish
hb completion fish > ~/.config/fish/completions/hb.fish
```

If no shell argument is provided, the CLI auto-detects your current shell from the `$SHELL` environment variable.

!!! info "Note"
    After adding the completion script, restart your shell or run `source ~/.bashrc` (or equivalent) for changes to take effect.
