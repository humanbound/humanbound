# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Config command — view and edit local provider configuration.

Reads/writes ~/.humanbound/config.yaml. No database, no API calls.
This is the local-mode provider configuration — separate from platform providers.
"""

import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

CONFIG_DIR = Path.home() / ".humanbound"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

VALID_PROVIDERS = ["openai", "claude", "gemini", "grok", "azureopenai", "ollama"]
VALID_KEYS = ["provider", "api-key", "api_key", "model", "endpoint"]


def _read_config():
    if not CONFIG_FILE.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(CONFIG_FILE.read_text()) or {}
    except ImportError:
        # Fallback YAML parser
        config = {}
        for line in CONFIG_FILE.read_text().strip().split("\n"):
            if ":" in line and not line.strip().startswith("#"):
                key, value = line.split(":", 1)
                config[key.strip()] = value.strip()
        return config


def _write_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        CONFIG_FILE.write_text(yaml.dump(config, default_flow_style=False))
    except ImportError:
        # Fallback YAML writer
        lines = []
        for k, v in config.items():
            lines.append(f"{k}: {v}")
        CONFIG_FILE.write_text("\n".join(lines) + "\n")


@click.group("config", invoke_without_command=True)
@click.pass_context
def config_group(ctx):
    """View or edit local configuration.

    \b
    Examples:
      hb config                           # Show current config
      hb config set provider openai       # Set LLM provider
      hb config set api-key sk-...        # Set API key
      hb config set model gpt-4.1         # Set model
      hb config set provider ollama       # Full local isolation
      hb config set model llama3.1:8b     # Set ollama model
    """
    if ctx.invoked_subcommand is not None:
        return

    config = _read_config()

    if not config:
        console.print("[yellow]No local configuration found.[/yellow]")
        console.print()
        console.print("Set up a provider:")
        console.print("  hb config set provider openai")
        console.print("  hb config set api-key sk-...")
        console.print()
        console.print("Or use ollama for full isolation:")
        console.print("  hb config set provider ollama")
        console.print("  hb config set model llama3.1:8b")
        return

    # Display config
    provider = config.get("provider", "not set")
    model = config.get("model", "default")
    api_key = config.get("api_key", "")
    endpoint = config.get("endpoint", "")

    # Mask API key
    key_display = f"{api_key[:7]}****" if api_key and len(api_key) > 7 else ("set" if api_key else "not set")

    table = Table(title="Local Configuration", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("Provider", provider)
    table.add_row("Model", model)
    table.add_row("API Key", key_display)
    if endpoint:
        table.add_row("Endpoint", endpoint)
    table.add_row("Config file", str(CONFIG_FILE))

    console.print(table)


@config_group.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a configuration value.

    \b
    Keys:
      provider    LLM provider (openai, claude, gemini, grok, azureopenai, ollama)
      api-key     API key for the provider
      model       Model name (e.g. gpt-4.1, llama3.1:8b)
      endpoint    Custom endpoint URL (e.g. for ollama: http://localhost:11434)
    """
    # Normalize key
    key = key.lower().replace("-", "_")

    if key not in [k.replace("-", "_") for k in VALID_KEYS]:
        console.print(f"[red]Unknown key: {key}[/red]")
        console.print(f"Valid keys: {', '.join(VALID_KEYS)}")
        raise SystemExit(1)

    if key == "provider" and value.lower() not in VALID_PROVIDERS:
        console.print(f"[red]Unknown provider: {value}[/red]")
        console.print(f"Supported: {', '.join(VALID_PROVIDERS)}")
        raise SystemExit(1)

    config = _read_config()
    config[key] = value
    _write_config(config)

    # Friendly feedback
    if key == "provider":
        console.print(f"[green]Provider set to:[/green] {value}")
        if value == "ollama":
            console.print("[dim]Full local isolation. Set model: hb config set model llama3.1:8b[/dim]")
        elif not config.get("api_key"):
            console.print(f"[dim]Set API key: hb config set api-key <your-key>[/dim]")
    elif key == "api_key":
        masked = f"{value[:7]}****" if len(value) > 7 else "****"
        console.print(f"[green]API key set:[/green] {masked}")
    elif key == "model":
        console.print(f"[green]Model set to:[/green] {value}")
    elif key == "endpoint":
        console.print(f"[green]Endpoint set to:[/green] {value}")


@config_group.command("get")
@click.argument("key")
def config_get(key):
    """Get a configuration value."""
    key = key.lower().replace("-", "_")
    config = _read_config()
    value = config.get(key, "")

    if key == "api_key" and value:
        value = f"{value[:7]}****" if len(value) > 7 else "****"

    if value:
        console.print(value)
    else:
        console.print(f"[yellow]{key} not set[/yellow]")
        raise SystemExit(1)
