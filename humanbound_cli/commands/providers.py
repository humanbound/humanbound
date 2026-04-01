"""Provider management commands."""

import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm

from ..client import HumanboundClient
from ..exceptions import NotAuthenticatedError, APIError

console = Console()
console_err = Console(stderr=True)

# Supported provider names
SUPPORTED_PROVIDERS = ["openai", "claude", "azureopenai", "gemini", "grok", "custom"]


@click.group("providers", invoke_without_command=True)
@click.pass_context
def providers_group(ctx):
    """Model provider management. Run without subcommand to list providers."""
    if ctx.invoked_subcommand is not None:
        return
    _list_providers()


@providers_group.command("list")
def list_providers_cmd():
    """List configured model providers."""
    _list_providers()


def _list_providers():
    """List configured model providers."""
    client = HumanboundClient()

    if not client.is_authenticated():
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console_err.print("[yellow]No organisation selected.[/yellow]")
        console_err.print("Use 'hb switch <id>' to select an organisation first.")
        raise SystemExit(1)

    try:
        providers = client.list_providers()

        if not providers:
            console.print("[yellow]No providers configured.[/yellow]")
            console.print("\n[dim]Use 'hb providers add' to configure a model provider.[/dim]")
            return

        table = Table(title="Model Providers")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Model", width=25)
        table.add_column("Default", justify="center")

        for provider in providers:
            is_default = "[green]✓[/green]" if provider.get("is_default") else ""
            integration = provider.get("integration", {})
            model = integration.get("model", "")

            provider_id = provider.get("id", "")

            table.add_row(
                provider_id,
                provider.get("name", "").upper(),
                model or "[dim]auto[/dim]",
                is_default,
            )

        console.print(table)

    except NotAuthenticatedError:
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@providers_group.command("create")
@click.option(
    "--name", "-n",
    type=click.Choice(SUPPORTED_PROVIDERS, case_sensitive=False),
    help="Provider name (openai, claude, azureopenai, gemini, grok, custom)"
)
@click.option(
    "--api-key", "-k",
    help="API key for the provider"
)
@click.option(
    "--endpoint", "-e",
    help="API endpoint (required for azureopenai and custom)"
)
@click.option(
    "--model", "-m",
    help="Model name (optional, auto-detected for most providers)"
)
@click.option(
    "--default", "is_default",
    is_flag=True,
    default=False,
    help="Set as default provider"
)
@click.option(
    "--interactive", "-i",
    is_flag=True,
    default=False,
    help="Use interactive mode to configure provider"
)
def add_provider(name: str, api_key: str, endpoint: str, model: str, is_default: bool, interactive: bool):
    """Add a new model provider.

    Configure an LLM provider for running security tests. Supported providers:

    \b
    - openai: OpenAI GPT models (requires sk-... API key)
    - claude: Anthropic Claude models (requires sk-ant-... API key)
    - azureopenai: Azure OpenAI Service (requires endpoint URL)
    - gemini: Google Gemini models
    - grok: xAI Grok models
    - custom: Custom OpenAI-compatible endpoints

    \b
    Examples:
      hb providers add --name openai --api-key sk-...
      hb providers add --name azureopenai --api-key ... --endpoint https://...
      hb providers add -i  # Interactive mode
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console_err.print("[yellow]No organisation selected.[/yellow]")
        console_err.print("Use 'hb switch <id>' to select an organisation first.")
        raise SystemExit(1)

    # Interactive mode
    if interactive or not name:
        console.print("[bold]Configure Model Provider[/bold]\n")

        if not name:
            console.print("Available providers:")
            for i, p in enumerate(SUPPORTED_PROVIDERS, 1):
                console.print(f"  {i}. {p.upper()}")
            name = Prompt.ask(
                "\nSelect provider",
                choices=SUPPORTED_PROVIDERS,
                default="openai"
            )

        if not api_key:
            api_key = Prompt.ask("API Key", password=True)

        needs_endpoint = name.lower() in ["azureopenai", "custom"]
        if needs_endpoint and not endpoint:
            endpoint = Prompt.ask("API Endpoint URL")

        if not model and name.lower() in ["azureopenai", "custom"]:
            model = Prompt.ask("Model name", default="")

        if not is_default:
            is_default = Confirm.ask("Set as default provider?", default=False)

    # Validate required fields
    if not name:
        console_err.print("[red]Error:[/red] Provider name is required.")
        raise SystemExit(1)

    if not api_key:
        console_err.print("[red]Error:[/red] API key is required.")
        raise SystemExit(1)

    if name.lower() in ["azureopenai", "custom"] and not endpoint:
        console_err.print(f"[red]Error:[/red] Endpoint is required for {name}.")
        raise SystemExit(1)

    # Build integration config
    integration = {"api_key": api_key}
    if endpoint:
        integration["endpoint"] = endpoint
    if model:
        integration["model"] = model

    try:
        with console.status("Adding provider...", spinner="dots"):
            result = client.add_provider(
                name=name.lower(),
                integration=integration,
                is_default=is_default
            )

        console.print(f"[green]Provider added successfully![/green]")
        console.print(f"[dim]ID: {result.get('id')}[/dim]")

        if is_default:
            console.print(f"[dim]Set as default provider[/dim]")

    except NotAuthenticatedError:
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@providers_group.command("delete")
@click.argument("provider_id")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
def remove_provider(provider_id: str, force: bool):
    """Remove a model provider.

    PROVIDER_ID: Provider UUID (can use partial ID).
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console_err.print("[yellow]No organisation selected.[/yellow]")
        console_err.print("Use 'hb switch <id>' to select an organisation first.")
        raise SystemExit(1)

    try:
        # Resolve partial ID
        providers = client.list_providers()
        matched = None
        for p in providers:
            if p.get("id", "").startswith(provider_id):
                matched = p
                break

        if not matched:
            console_err.print(f"[red]Provider not found:[/red] {provider_id}")
            raise SystemExit(1)

        full_id = matched.get("id")
        provider_name = matched.get("name", "").upper()

        if not force:
            if not Confirm.ask(f"Remove provider [bold]{provider_name}[/bold] ({full_id})?"):
                console.print("[dim]Cancelled.[/dim]")
                return

        with console.status("Removing provider...", spinner="dots"):
            client.remove_provider(full_id)

        console.print(f"[green]Provider removed:[/green] {provider_name}")

    except NotAuthenticatedError:
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)


@providers_group.command("update")
@click.argument("provider_id")
@click.option("--api-key", "-k", help="New API key")
@click.option("--endpoint", "-e", help="New endpoint URL")
@click.option("--model", "-m", help="New model name")
@click.option("--default/--no-default", default=None, help="Set/unset as default")
def update_provider(provider_id: str, api_key: str, endpoint: str, model: str, default: bool):
    """Update a model provider configuration.

    PROVIDER_ID: Provider UUID (can use partial ID).

    \b
    Examples:
      hb providers update abc123 --api-key sk-new-key
      hb providers update abc123 --default
    """
    client = HumanboundClient()

    if not client.is_authenticated():
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)

    if not client.organisation_id:
        console_err.print("[yellow]No organisation selected.[/yellow]")
        console_err.print("Use 'hb switch <id>' to select an organisation first.")
        raise SystemExit(1)

    # Check at least one option provided
    if not any([api_key, endpoint, model, default is not None]):
        console_err.print("[yellow]No updates specified.[/yellow]")
        console_err.print("Use --api-key, --endpoint, --model, or --default options.")
        raise SystemExit(1)

    try:
        # Resolve partial ID
        providers = client.list_providers()
        matched = None
        for p in providers:
            if p.get("id", "").startswith(provider_id):
                matched = p
                break

        if not matched:
            console_err.print(f"[red]Provider not found:[/red] {provider_id}")
            raise SystemExit(1)

        full_id = matched.get("id")

        # Build update payload
        update_data = {}

        if api_key or endpoint or model:
            integration = matched.get("integration", {}).copy()
            if api_key:
                integration["api_key"] = api_key
            if endpoint:
                integration["endpoint"] = endpoint
            if model:
                integration["model"] = model
            update_data["integration"] = integration

        if default is not None:
            update_data["is_default"] = default

        with console.status("Updating provider...", spinner="dots"):
            client.update_provider(full_id, update_data)

        console.print(f"[green]Provider updated![/green]")

    except NotAuthenticatedError:
        console_err.print("[red]Not authenticated.[/red] Run 'hb login' first.")
        raise SystemExit(1)
    except APIError as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)
