---
description: "Enable tab completion for the hb CLI in bash, zsh, or fish — install once and get flag and command suggestions in every new shell."
title: Shell Completion
---

# Shell Completion

Enable tab completion for the `hb` CLI in your shell. The `hb completion` command generates the appropriate completion script for bash, zsh, or fish.

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
