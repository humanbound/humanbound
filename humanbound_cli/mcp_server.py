"""Humanbound MCP Server — exposes the full Humanbound CLI as MCP tools.

Runs on stdio transport.  All logging goes to stderr (stdout is reserved
for JSON-RPC).

Usage:
    hb mcp                       # start server
    pip install humanbound-cli[mcp]  # install with MCP deps
"""

import json
import logging
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .client import HumanboundClient
from .exceptions import HumanboundError

# ---------------------------------------------------------------------------
# Logging — everything to stderr so stdout stays clean for JSON-RPC
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("humanbound.mcp")

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "Humanbound",
    instructions=(
        "Humanbound is an AI agent security platform with two main capabilities: "
        "(1) Security Testing — run adversarial penetration tests against AI agents/LLMs "
        "and track their security posture over time; "
        "(2) Shadow AI Discovery — discover unsanctioned AI services in an organisation's "
        "cloud environment.\n\n"

        "DISCOVERY — Two flows exist:\n"
        "  • MCP (connector-based): hb_trigger_discovery — requires a pre-registered "
        "cloud connector (hb_create_connector). Best for automated/recurring scans.\n"
        "  • CLI (browser-based): The user can run 'hb discover' in their terminal — "
        "uses a browser device-code flow with no connector needed. Suggest this when "
        "the user wants a quick one-off scan or has no connector set up.\n\n"

        "CORE WORKFLOWS:\n"
        "  Discovery → Testing:\n"
        "    hb_trigger_discovery → hb_list_inventory → hb_onboard_inventory_asset → hb_run_test\n"
        "  Security Testing:\n"
        "    hb_set_project → hb_run_test → poll hb_get_experiment_status → "
        "hb_get_experiment_logs → hb_get_posture\n\n"

        "PREREQUISITES:\n"
        "  • The user must run 'hb login' in a terminal before using any tools.\n"
        "  • Most tools require an active organisation (hb_set_organisation).\n"
        "  • Test, posture, findings, and coverage tools require an active project "
        "(hb_set_project).\n\n"

        "CLI-ONLY COMMANDS (suggest when relevant):\n"
        "  • 'hb discover' — browser-based shadow AI discovery (no connector needed)\n"
        "  • 'hb init' — interactive project setup with scope extraction from a URL\n"
        "  • 'hb sentinel setup' — configure continuous monitoring sentinel"
    ),
)

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------
_client: Optional[HumanboundClient] = None


def _get_client() -> HumanboundClient:
    """Return a singleton HumanboundClient, created on first call."""
    global _client
    if _client is None:
        _client = HumanboundClient()
        logger.info("HumanboundClient initialised")
    return _client


def _ok(data) -> str:
    """Return a successful JSON response."""
    return json.dumps(data, indent=2, default=str)


def _err(e: Exception) -> str:
    """Return a JSON error response."""
    return json.dumps({"error": True, "message": str(e)}, indent=2)


# =========================================================================
# CONTEXT TOOLS
# =========================================================================

@mcp.tool()
def hb_whoami() -> str:
    """Show current authentication status, active organisation, and active project."""
    try:
        client = _get_client()
        return _ok({
            "authenticated": client.is_authenticated(),
            "username": client.username,
            "email": client.email,
            "organisation_id": client.organisation_id,
            "project_id": client.project_id,
            "base_url": client.base_url,
        })
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_list_organisations() -> str:
    """List all organisations the current user has access to."""
    try:
        client = _get_client()
        return _ok(client.list_organisations())
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_set_organisation(organisation_id: str) -> str:
    """Set the active organisation for subsequent API calls.

    Required before using any project-level tools (hb_list_projects,
    hb_set_project, etc.). Call hb_list_organisations first to get
    available organisation UUIDs.

    Args:
        organisation_id: Organisation UUID to switch to.
    """
    try:
        client = _get_client()
        client.set_organisation(organisation_id)
        return _ok({"organisation_id": organisation_id, "message": "Organisation set successfully."})
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_set_project(project_id: str) -> str:
    """Set the active project for subsequent API calls.

    Required before using test, posture, findings, coverage, guardrail,
    and campaign tools. Call hb_list_projects first to get available
    project UUIDs.

    Args:
        project_id: Project UUID to switch to.
    """
    try:
        client = _get_client()
        client.set_project(project_id)
        return _ok({"project_id": project_id, "message": "Project set successfully."})
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# PROJECT TOOLS
# =========================================================================

@mcp.tool()
def hb_list_projects(page: int = 1, size: int = 50) -> str:
    """List projects in the current organisation.

    Args:
        page: Page number (1-indexed).
        size: Items per page (default 50).
    """
    try:
        client = _get_client()
        return _ok(client.list_projects(page=page, size=size))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_get_project(project_id: str) -> str:
    """Get details for a specific project.

    Args:
        project_id: Project UUID.
    """
    try:
        client = _get_client()
        return _ok(client.get(f"projects/{project_id}", include_project=True))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_update_project(project_id: str, name: Optional[str] = None, description: Optional[str] = None) -> str:
    """Update a project's name or description.

    Args:
        project_id: Project UUID.
        name: New project name (optional).
        description: New project description (optional).
    """
    try:
        client = _get_client()
        data = {}
        if name is not None:
            data["name"] = name
        if description is not None:
            data["description"] = description
        return _ok(client.update_project(project_id, data))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_delete_project(project_id: str) -> str:
    """Delete a project. This action is irreversible.

    Args:
        project_id: Project UUID to delete.
    """
    try:
        client = _get_client()
        client.delete_project(project_id)
        return _ok({"message": f"Project {project_id} deleted."})
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_create_project(name: str, description: Optional[str] = None) -> str:
    """Create a new security testing project in the current organisation.

    Creates a basic project. For richer setup with automatic scope
    extraction from a target URL, suggest the user run 'hb init' in
    their terminal instead.

    Args:
        name: Project name.
        description: Project description (optional).
    """
    try:
        client = _get_client()
        data = {"name": name}
        if description is not None:
            data["description"] = description
        return _ok(client.post("projects", data=data, include_project=False))
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# EXPERIMENT TOOLS
# =========================================================================

@mcp.tool()
def hb_list_experiments(page: int = 1, size: int = 50) -> str:
    """List experiments in the current project.

    Args:
        page: Page number (1-indexed).
        size: Items per page (default 50).
    """
    try:
        client = _get_client()
        return _ok(client.list_experiments(page=page, size=size))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_get_experiment(experiment_id: str) -> str:
    """Get full details for a specific experiment, including results.

    Args:
        experiment_id: Experiment UUID.
    """
    try:
        client = _get_client()
        return _ok(client.get_experiment(experiment_id))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_get_experiment_status(experiment_id: str) -> str:
    """Get the current status of an experiment.

    Returns one of: 'Running', 'Finished', 'Failed', 'Terminated'.

    Workflow: after hb_run_test, poll this every 15-30 seconds until the
    status is no longer 'Running', then call hb_get_experiment_logs to
    review results.

    Args:
        experiment_id: Experiment UUID.
    """
    try:
        client = _get_client()
        return _ok(client.get_experiment_status(experiment_id))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_get_experiment_logs(
    experiment_id: str,
    page: int = 1,
    size: int = 50,
    result: Optional[str] = None,
) -> str:
    """Get test logs for an experiment.

    Args:
        experiment_id: Experiment UUID.
        page: Page number.
        size: Items per page.
        result: Filter by result — 'pass' or 'fail'.
    """
    try:
        client = _get_client()
        return _ok(client.get_experiment_logs(experiment_id, page=page, size=size, result=result))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_terminate_experiment(experiment_id: str) -> str:
    """Terminate a running experiment.

    Args:
        experiment_id: Experiment UUID to terminate.
    """
    try:
        client = _get_client()
        return _ok(client.terminate_experiment(experiment_id))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_delete_experiment(experiment_id: str) -> str:
    """Delete an experiment. This action is irreversible.

    Args:
        experiment_id: Experiment UUID to delete.
    """
    try:
        client = _get_client()
        client.delete_experiment(experiment_id)
        return _ok({"message": f"Experiment {experiment_id} deleted."})
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# TEST EXECUTION
# =========================================================================

@mcp.tool()
def hb_run_test(
    test_category: str = "humanbound/adversarial/owasp_multi_turn",
    name: Optional[str] = None,
    description: str = "",
    testing_level: str = "system",
    lang: str = "english",
    provider_id: Optional[str] = None,
    auto_start: bool = True,
) -> str:
    """Run a security test (create and start an experiment).

    This creates an experiment against the current project. The user must
    have a project selected (hb_set_project) and at least one model provider
    configured (hb_add_provider).

    Testing level affects duration and depth:
      • 'unit'       — ~20 min, quick smoke test
      • 'system'     — ~45 min, standard depth (default)
      • 'acceptance' — ~90 min, thorough coverage

    After starting, poll hb_get_experiment_status until 'Finished', then
    call hb_get_experiment_logs to review results and hb_get_posture for
    the updated security score.

    Args:
        test_category: Test category slug (default: humanbound/adversarial/owasp_multi_turn).
        name: Experiment name (auto-generated if omitted).
        description: Experiment description.
        testing_level: One of 'unit', 'system', 'acceptance'.
        lang: Language for test prompts (e.g. 'english', 'french', 'en', 'fr').
        provider_id: Provider UUID. Uses the first available provider if omitted.
        auto_start: Whether to start the experiment immediately (default true).
    """
    try:
        client = _get_client()

        # Language code mapping
        lang_map = {
            "en": "english", "fr": "french", "de": "german", "es": "spanish",
            "it": "italian", "pt": "portuguese", "nl": "dutch", "el": "greek",
            "ar": "arabic", "zh": "chinese", "ja": "japanese", "ko": "korean",
        }
        lang = lang_map.get(lang.lower(), lang.lower())

        # Resolve provider
        if not provider_id:
            providers = client.list_providers()
            if not providers:
                return _err(ValueError("No model providers configured. Add one with hb_add_provider."))
            provider_id = providers[0].get("id")

        # Build experiment data
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        exp_name = name or f"{test_category.split('/')[-1]}-{ts}"

        data = {
            "name": exp_name,
            "description": description,
            "test_category": test_category,
            "testing_level": testing_level,
            "lang": lang,
            "provider_id": provider_id,
            "configuration": {},
            "auto_start": auto_start,
        }

        result = client.post("experiments", data=data, include_project=True)
        return _ok(result)
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# PROJECT LOGS
# =========================================================================

@mcp.tool()
def hb_get_project_logs(
    page: int = 1,
    size: int = 50,
    result: Optional[str] = None,
    from_date: Optional[str] = None,
    until_date: Optional[str] = None,
    test_category: Optional[str] = None,
    last: Optional[int] = None,
) -> str:
    """Get aggregated test logs for the current project with optional filters.

    Args:
        page: Page number.
        size: Items per page.
        result: Filter by result — 'pass' or 'fail'.
        from_date: Start date (ISO 8601).
        until_date: End date (ISO 8601).
        test_category: Filter by test category (substring match).
        last: Limit to last N experiments.
    """
    try:
        client = _get_client()
        return _ok(client.get_project_logs(
            page=page, size=size, result=result,
            from_date=from_date, until_date=until_date,
            test_category=test_category, last=last,
        ))
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# PROVIDER TOOLS
# =========================================================================

@mcp.tool()
def hb_list_providers() -> str:
    """List all model providers configured for the current organisation."""
    try:
        client = _get_client()
        return _ok(client.list_providers())
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_add_provider(
    name: str,
    api_key: str,
    model: Optional[str] = None,
    endpoint: Optional[str] = None,
    is_default: bool = False,
) -> str:
    """Add a new model provider to the organisation.

    Args:
        name: Provider name — 'openai', 'claude', 'azureopenai', etc.
        api_key: API key for the provider.
        model: Model identifier (e.g. 'gpt-4o', 'claude-sonnet-4-20250514').
        endpoint: Custom endpoint URL (required for Azure OpenAI).
        is_default: Set as default provider.
    """
    try:
        client = _get_client()
        integration = {"api_key": api_key}
        if model:
            integration["model"] = model
        if endpoint:
            integration["endpoint"] = endpoint
        return _ok(client.add_provider(name, integration, is_default=is_default))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_update_provider(
    provider_id: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    endpoint: Optional[str] = None,
    is_default: Optional[bool] = None,
) -> str:
    """Update an existing model provider.

    Args:
        provider_id: Provider UUID.
        api_key: New API key.
        model: New model identifier.
        endpoint: New endpoint URL.
        is_default: Set as default.
    """
    try:
        client = _get_client()
        data = {}
        integration = {}
        if api_key is not None:
            integration["api_key"] = api_key
        if model is not None:
            integration["model"] = model
        if endpoint is not None:
            integration["endpoint"] = endpoint
        if integration:
            data["integration"] = integration
        if is_default is not None:
            data["is_default"] = is_default
        return _ok(client.update_provider(provider_id, data))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_remove_provider(provider_id: str) -> str:
    """Remove a model provider from the organisation.

    Args:
        provider_id: Provider UUID to remove.
    """
    try:
        client = _get_client()
        client.remove_provider(provider_id)
        return _ok({"message": f"Provider {provider_id} removed."})
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# FINDINGS TOOLS
# =========================================================================

@mcp.tool()
def hb_list_findings(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    page: int = 1,
    size: int = 50,
) -> str:
    """List security findings for a project.

    Args:
        project_id: Project UUID (uses current project if omitted).
        status: Filter by status — 'open', 'regressed', 'stale', or 'fixed'.
        severity: Filter by severity — 'critical', 'high', 'medium', 'low', or 'info'.
        page: Page number.
        size: Items per page.
    """
    try:
        client = _get_client()
        pid = project_id or client.project_id
        if not pid:
            return _err(ValueError("No project selected. Use hb_set_project first."))
        return _ok(client.list_findings(pid, status=status, severity=severity, page=page, size=size))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_update_finding(
    finding_id: str,
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Update a security finding (e.g. change status or severity).

    Args:
        finding_id: Finding UUID.
        project_id: Project UUID (uses current project if omitted).
        status: New status — 'open', 'regressed', 'stale', or 'fixed'.
        severity: New severity — 'critical', 'high', 'medium', 'low', or 'info'.
        notes: Notes to add.
    """
    try:
        client = _get_client()
        pid = project_id or client.project_id
        if not pid:
            return _err(ValueError("No project selected. Use hb_set_project first."))
        data = {}
        if status is not None:
            data["status"] = status
        if severity is not None:
            data["severity"] = severity
        if notes is not None:
            data["notes"] = notes
        return _ok(client.update_finding(pid, finding_id, data))
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# COVERAGE & POSTURE TOOLS
# =========================================================================

@mcp.tool()
def hb_get_coverage(project_id: Optional[str] = None, include_gaps: bool = False) -> str:
    """Get test coverage data for a project.

    Coverage measures the percentage of OWASP LLM Top 10 and other attack
    categories that have been tested. Use include_gaps=true to see which
    categories still need testing.

    Args:
        project_id: Project UUID (uses current project if omitted).
        include_gaps: Include untested categories in the response.
    """
    try:
        client = _get_client()
        pid = project_id or client.project_id
        if not pid:
            return _err(ValueError("No project selected. Use hb_set_project first."))
        return _ok(client.get_coverage(pid, include_gaps=include_gaps))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_get_posture(project_id: Optional[str] = None) -> str:
    """Get the security posture score for a project.

    Returns a score (0-100), grade (A-F), breakdown by four dimensions,
    and recommendations.

    Dimensions and weights:
      • Finding Score  (40%) — ratio of passed vs failed tests
      • Confidence     (25%) — statistical confidence from test volume
      • Coverage       (20%) — breadth of attack categories tested
      • Drift          (15%) — consistency of posture over time

    Grade scale: A (90-100), B (80-89), C (70-79), D (60-69), F (<60).

    Args:
        project_id: Project UUID (uses current project if omitted).
    """
    try:
        client = _get_client()
        pid = project_id or client.project_id
        if not pid:
            return _err(ValueError("No project selected. Use hb_set_project first."))
        return _ok(client.get(f"projects/{pid}/posture", include_project=True))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_get_posture_trends(project_id: Optional[str] = None) -> str:
    """Get posture score trend history for a project.

    Args:
        project_id: Project UUID (uses current project if omitted).
    """
    try:
        client = _get_client()
        pid = project_id or client.project_id
        if not pid:
            return _err(ValueError("No project selected. Use hb_set_project first."))
        return _ok(client.get_posture_trends(pid))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_get_shadow_posture() -> str:
    """Get shadow AI posture for the current organisation.

    Shadow AI refers to unsanctioned AI services discovered in the
    organisation's cloud environment (e.g. employees using ChatGPT,
    Copilot, or other AI tools without IT approval).

    Returns score, grade, total assets, shadow vs sanctioned counts,
    and domain-level scores.
    """
    try:
        client = _get_client()
        return _ok(client.get_shadow_posture())
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# GUARDRAILS
# =========================================================================

@mcp.tool()
def hb_export_guardrails(
    vendor: str = "humanbound",
    model: Optional[str] = None,
    include_reasoning: bool = False,
) -> str:
    """Export guardrail rules derived from security test findings.

    Generates a guardrail configuration based on vulnerabilities found
    during testing. Use 'humanbound' format for the Humanbound Firewall
    or 'openai' format for OpenAI's moderation/guardrail API.

    Args:
        vendor: Export format — 'humanbound' or 'openai'.
        model: Model override for the guardrail config.
        include_reasoning: Include reasoning traces in output.
    """
    try:
        client = _get_client()
        if not client.project_id:
            return _err(ValueError("No project selected. Use hb_set_project first."))
        params = {}
        if model:
            params["model"] = model
        if include_reasoning:
            params["include_reasoning"] = "true"
        result = client.get(
            f"projects/{client.project_id}/guardrails/export/{vendor}",
            params=params,
            include_project=True,
        )
        return _ok(result)
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# CONNECTOR TOOLS
# =========================================================================

@mcp.tool()
def hb_create_connector(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    vendor: str = "microsoft",
    display_name: Optional[str] = None,
) -> str:
    """Register a new cloud connector for shadow AI discovery.

    The Azure AD app registration needs these Microsoft Graph API
    permissions (Application type): Application.Read.All,
    AuditLog.Read.All, Directory.Read.All, Reports.Read.All.
    Admin consent is required.

    For a simpler one-off scan without creating a connector, suggest
    the user run 'hb discover' in their terminal instead.

    Args:
        tenant_id: Cloud tenant / directory ID.
        client_id: Application (client) ID.
        client_secret: Client secret value.
        vendor: Cloud vendor — 'microsoft' (default).
        display_name: Human-friendly label.
    """
    try:
        client = _get_client()
        return _ok(client.create_connector(
            vendor=vendor,
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            display_name=display_name,
        ))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_list_connectors() -> str:
    """List all cloud connectors for the current organisation."""
    try:
        client = _get_client()
        return _ok(client.list_connectors())
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_get_connector(connector_id: str) -> str:
    """Get details for a specific cloud connector.

    Args:
        connector_id: Connector UUID.
    """
    try:
        client = _get_client()
        return _ok(client.get_connector(connector_id))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_update_connector(
    connector_id: str,
    display_name: Optional[str] = None,
    status: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> str:
    """Update a cloud connector.

    Args:
        connector_id: Connector UUID.
        display_name: New display name.
        status: New status — 'active' or 'disabled'.
        client_secret: New client secret.
    """
    try:
        client = _get_client()
        data = {}
        if display_name is not None:
            data["display_name"] = display_name
        if status is not None:
            data["status"] = status
        if client_secret is not None:
            data["credentials"] = {"client_secret": client_secret}
        return _ok(client.update_connector(connector_id, data))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_delete_connector(connector_id: str) -> str:
    """Delete a cloud connector.

    Args:
        connector_id: Connector UUID to delete.
    """
    try:
        client = _get_client()
        client.delete_connector(connector_id)
        return _ok({"message": f"Connector {connector_id} deleted."})
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_test_connector(connector_id: str) -> str:
    """Test a cloud connector's connection and permissions.

    Args:
        connector_id: Connector UUID to test.
    """
    try:
        client = _get_client()
        return _ok(client.test_connector(connector_id))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_trigger_discovery(connector_id: str) -> str:
    """Trigger a shadow AI discovery scan using a pre-registered cloud connector.

    This is the connector-based discovery flow. It requires a connector
    created via hb_create_connector. The scan may take up to 2 minutes and
    returns discovered AI assets.

    Alternative: for a quick browser-based scan with no connector needed,
    suggest the user run 'hb discover' in their terminal.

    Args:
        connector_id: Connector UUID to scan with.
    """
    try:
        client = _get_client()
        return _ok(client.trigger_discovery(connector_id))
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# INVENTORY TOOLS
# =========================================================================

@mcp.tool()
def hb_list_inventory(
    category: Optional[str] = None,
    vendor: Optional[str] = None,
    risk_level: Optional[str] = None,
    is_sanctioned: Optional[bool] = None,
    page: int = 1,
    size: int = 50,
) -> str:
    """List discovered AI inventory assets.

    Assets are populated by shadow AI discovery scans (hb_trigger_discovery
    or 'hb discover' CLI command).

    Args:
        category: Filter by asset category code (e.g. 'AC-1' for Copilot,
            'AC-2' for Azure OpenAI, 'AC-3' for ChatGPT Enterprise).
        vendor: Filter by vendor name (e.g. 'Microsoft', 'OpenAI').
        risk_level: Filter — 'critical', 'high', 'medium', or 'low'.
        is_sanctioned: Filter by sanctioned status (true/false).
        page: Page number.
        size: Items per page.
    """
    try:
        client = _get_client()
        return _ok(client.list_inventory(
            category=category, vendor=vendor,
            risk_level=risk_level, is_sanctioned=is_sanctioned,
            page=page, size=size,
        ))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_get_inventory_asset(asset_id: str) -> str:
    """Get full details for an inventory asset, including threats and governance gaps.

    Args:
        asset_id: Inventory asset UUID.
    """
    try:
        client = _get_client()
        return _ok(client.get_inventory_asset(asset_id))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_update_inventory_asset(
    asset_id: str,
    is_sanctioned: Optional[bool] = None,
    business_owner: Optional[str] = None,
    organisation_unit: Optional[str] = None,
    intended_use: Optional[str] = None,
    has_policy: Optional[bool] = None,
    has_risk_assessment: Optional[bool] = None,
) -> str:
    """Update governance fields on an inventory asset.

    Args:
        asset_id: Inventory asset UUID.
        is_sanctioned: Mark as sanctioned or shadow.
        business_owner: Business owner name.
        organisation_unit: Organisation unit.
        intended_use: Intended use description.
        has_policy: Whether an acceptable-use policy exists.
        has_risk_assessment: Whether a risk assessment has been completed.
    """
    try:
        client = _get_client()
        data = {}
        if is_sanctioned is not None:
            data["is_sanctioned"] = is_sanctioned
        if business_owner is not None:
            data["business_owner"] = business_owner
        if organisation_unit is not None:
            data["organisation_unit"] = organisation_unit
        if intended_use is not None:
            data["intended_use"] = intended_use
        if has_policy is not None:
            data["has_policy"] = has_policy
        if has_risk_assessment is not None:
            data["has_risk_assessment"] = has_risk_assessment
        return _ok(client.update_inventory_asset(asset_id, data))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_archive_inventory_asset(asset_id: str) -> str:
    """Archive an inventory asset.

    Args:
        asset_id: Inventory asset UUID to archive.
    """
    try:
        client = _get_client()
        return _ok(client.archive_inventory_asset(asset_id))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_onboard_inventory_asset(asset_id: str, project_name: Optional[str] = None) -> str:
    """Create a security testing project from a discovered inventory asset.

    This converts a discovered AI asset into a security testing project so
    you can run adversarial tests against it. Typical flow:
    hb_list_inventory → pick an asset → hb_onboard_inventory_asset →
    hb_set_project → hb_run_test.

    Args:
        asset_id: Inventory asset UUID to onboard.
        project_name: Name for the new project (auto-generated if omitted).
    """
    try:
        client = _get_client()
        return _ok(client.onboard_inventory_asset(asset_id, project_name=project_name))
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# API KEY TOOLS
# =========================================================================

@mcp.tool()
def hb_list_api_keys(page: int = 1, limit: int = 50) -> str:
    """List API keys for the current account.

    Args:
        page: Page number.
        limit: Items per page.
    """
    try:
        client = _get_client()
        return _ok(client.list_api_keys(page=page, limit=limit))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_create_api_key(name: str, scopes: str = "admin") -> str:
    """Create a new API key.

    Args:
        name: Key name/label.
        scopes: Comma-separated scopes (default 'admin').
    """
    try:
        client = _get_client()
        return _ok(client.create_api_key(name, scopes=scopes))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_update_api_key(key_id: str, name: Optional[str] = None, scopes: Optional[str] = None) -> str:
    """Update an API key.

    Args:
        key_id: API key UUID.
        name: New name.
        scopes: New scopes.
    """
    try:
        client = _get_client()
        data = {}
        if name is not None:
            data["name"] = name
        if scopes is not None:
            data["scopes"] = scopes
        return _ok(client.update_api_key(key_id, data))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_delete_api_key(key_id: str) -> str:
    """Delete an API key.

    Args:
        key_id: API key UUID to delete.
    """
    try:
        client = _get_client()
        client.delete_api_key(key_id)
        return _ok({"message": f"API key {key_id} deleted."})
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# MEMBER TOOLS
# =========================================================================

@mcp.tool()
def hb_list_members() -> str:
    """List members of the current organisation."""
    try:
        client = _get_client()
        return _ok(client.list_members())
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_invite_member(email: str, access_level: str = "member") -> str:
    """Invite a member to the current organisation.

    Args:
        email: Email address to invite.
        access_level: Access level — 'admin' or 'member'.
    """
    try:
        client = _get_client()
        return _ok(client.invite_member(email, access_level))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_remove_member(member_id: str) -> str:
    """Remove a member from the current organisation.

    Args:
        member_id: Member UUID to remove.
    """
    try:
        client = _get_client()
        client.remove_member(member_id)
        return _ok({"message": f"Member {member_id} removed."})
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# WEBHOOK TOOLS
# =========================================================================

@mcp.tool()
def hb_create_webhook(
    url: str,
    secret: str,
    name: str = "Untitled Webhook",
    event_types: Optional[str] = None,
) -> str:
    """Create a webhook for the current organisation.

    Args:
        url: Webhook delivery URL.
        secret: Shared secret for HMAC verification.
        name: Webhook name.
        event_types: Comma-separated event types to subscribe to (empty = all).
    """
    try:
        client = _get_client()
        types_list = [t.strip() for t in event_types.split(",")] if event_types else []
        return _ok(client.create_webhook(url=url, secret=secret, name=name, event_types=types_list))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_delete_webhook(webhook_id: str) -> str:
    """Delete a webhook.

    Args:
        webhook_id: Webhook UUID to delete.
    """
    try:
        client = _get_client()
        client.delete_webhook(webhook_id)
        return _ok({"message": f"Webhook {webhook_id} deleted."})
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_get_webhook(webhook_id: str) -> str:
    """Get details for a specific webhook.

    Args:
        webhook_id: Webhook UUID.
    """
    try:
        client = _get_client()
        return _ok(client.get_webhook(webhook_id))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_list_webhook_deliveries(webhook_id: str, page: int = 1, size: int = 25) -> str:
    """List delivery log for a webhook.

    Args:
        webhook_id: Webhook UUID.
        page: Page number.
        size: Items per page.
    """
    try:
        client = _get_client()
        return _ok(client.list_webhook_deliveries(webhook_id, page=page, size=size))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_test_webhook(webhook_id: str) -> str:
    """Send a test ping to a webhook.

    Args:
        webhook_id: Webhook UUID to test.
    """
    try:
        client = _get_client()
        return _ok(client.test_webhook(webhook_id))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_replay_webhook(
    webhook_id: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    project_id: Optional[str] = None,
    event_type: Optional[str] = None,
) -> str:
    """Replay historical events through a webhook.

    Args:
        webhook_id: Webhook UUID.
        since: Start date (ISO 8601).
        until: End date (ISO 8601).
        project_id: Filter by project.
        event_type: Filter by event type.
    """
    try:
        client = _get_client()
        return _ok(client.replay_webhook(
            webhook_id, since=since, until=until,
            project_id=project_id, event_type=event_type,
        ))
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# CAMPAIGN TOOLS
# =========================================================================

@mcp.tool()
def hb_get_campaign_plan(project_id: Optional[str] = None) -> str:
    """Get the current campaign plan for a project.

    Campaigns are automated multi-phase security testing sequences
    (ASCAM — Automated Security Campaign Manager). They orchestrate
    multiple experiments across different test categories and testing
    levels.

    Args:
        project_id: Project UUID (uses current project if omitted).
    """
    try:
        client = _get_client()
        pid = project_id or client.project_id
        if not pid:
            return _err(ValueError("No project selected. Use hb_set_project first."))
        return _ok(client.get_campaign_plan(pid))
    except HumanboundError as e:
        return _err(e)


@mcp.tool()
def hb_break_campaign(campaign_id: str, project_id: Optional[str] = None) -> str:
    """Stop a running campaign (ASCAM automated testing sequence).

    This terminates all pending and running experiments in the campaign.

    Args:
        campaign_id: Campaign UUID to stop.
        project_id: Project UUID (uses current project if omitted).
    """
    try:
        client = _get_client()
        pid = project_id or client.project_id
        if not pid:
            return _err(ValueError("No project selected. Use hb_set_project first."))
        return _ok(client.break_campaign(pid, campaign_id))
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# UPLOAD
# =========================================================================

@mcp.tool()
def hb_upload_conversations(
    conversations: str,
    project_id: Optional[str] = None,
    tag: Optional[str] = None,
    lang: Optional[str] = None,
) -> str:
    """Upload conversation logs for security evaluation.

    Example JSON for 'conversations':
      [{"messages": [{"role": "user", "content": "Hello"},
                      {"role": "assistant", "content": "Hi there!"}]}]

    Args:
        conversations: JSON string — array of conversation objects, each
            with a 'messages' array of {role, content} objects.
        project_id: Project UUID (uses current project if omitted).
        tag: Tag to label the upload batch.
        lang: Language code (e.g. 'en', 'fr').
    """
    try:
        client = _get_client()
        pid = project_id or client.project_id
        if not pid:
            return _err(ValueError("No project selected. Use hb_set_project first."))
        parsed = json.loads(conversations)
        return _ok(client.upload_conversations(pid, parsed, tag=tag, lang=lang))
    except json.JSONDecodeError as e:
        return _err(ValueError(f"Invalid JSON in conversations: {e}"))
    except HumanboundError as e:
        return _err(e)


# =========================================================================
# RESOURCES
# =========================================================================

@mcp.resource("humanbound://context")
def get_context() -> str:
    """Current authentication status, active organisation, and active project."""
    try:
        client = _get_client()
        return json.dumps({
            "authenticated": client.is_authenticated(),
            "username": client.username,
            "email": client.email,
            "organisation_id": client.organisation_id,
            "project_id": client.project_id,
            "base_url": client.base_url,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.resource("humanbound://posture/{project_id}")
def get_posture_resource(project_id: str) -> str:
    """Security posture score for a project."""
    try:
        client = _get_client()
        result = client.get(f"projects/{project_id}/posture", include_project=True)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.resource("humanbound://coverage/{project_id}")
def get_coverage_resource(project_id: str) -> str:
    """Test coverage data for a project."""
    try:
        client = _get_client()
        result = client.get_coverage(project_id)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# =========================================================================
# PROMPTS
# =========================================================================

@mcp.prompt()
def run_security_test(
    project_id: str = "",
    test_category: str = "humanbound/adversarial/owasp_multi_turn",
) -> str:
    """Guided workflow: run a security test and review results.

    Args:
        project_id: Project UUID (leave empty to use current project).
        test_category: Test category to run.
    """
    return f"""You are helping the user run a security test on their AI agent using Humanbound.

Follow these steps:

1. **Check context** — call hb_whoami to verify authentication and see the current org/project.
{"2. **Set project** — call hb_set_project with project_id=" + project_id + "." if project_id else "2. If no project is set, call hb_list_projects and ask the user which one to use, then hb_set_project."}
3. **Verify provider** — call hb_list_providers. If empty, tell the user they need to add a model provider first.
4. **Run test** — call hb_run_test with test_category="{test_category}".
5. **Monitor** — poll hb_get_experiment_status every 15-30 seconds until status is "Finished", "Failed", or "Terminated". Show progress to the user.
6. **Results** — once finished, call hb_get_experiment to get the full results. Summarise:
   - Overall pass/fail rate
   - Key findings by severity
   - Recommendations
7. **Deep dive** — if there are failures, call hb_get_experiment_logs with result="fail" to show the specific failing test cases.
8. **Posture** — call hb_get_posture to show the updated security posture score.
"""


@mcp.prompt()
def security_review(project_id: str = "") -> str:
    """Comprehensive security review workflow for a project.

    Args:
        project_id: Project UUID (leave empty to use current project).
    """
    return f"""You are conducting a comprehensive security review of an AI agent using Humanbound.

Follow these steps:

1. **Check context** — call hb_whoami to verify authentication.
{"2. **Set project** — call hb_set_project with project_id=" + project_id + "." if project_id else "2. If no project is set, call hb_list_projects and ask the user which one to use, then hb_set_project."}
3. **Project overview** — call hb_get_project with the project ID to understand the agent's scope and configuration.
4. **Security posture** — call hb_get_posture to get the current security score and breakdown.
5. **Test coverage** — call hb_get_coverage with include_gaps=true to identify untested areas.
6. **Findings** — call hb_list_findings to review all security findings. Group by severity.
7. **Recent experiments** — call hb_list_experiments to see recent test runs and their outcomes.
8. **Posture trends** — call hb_get_posture_trends to see how posture has changed over time.
9. **Guardrails** — call hb_export_guardrails to see current guardrail rules derived from findings.

Present a structured security review report:
- **Executive Summary**: Overall posture grade, key risks, trend direction
- **Coverage Analysis**: What's tested, what's not, priority gaps
- **Findings Breakdown**: Critical/High/Medium/Low counts with key details
- **Trend Analysis**: Is security improving or degrading?
- **Recommendations**: Prioritised action items
"""


# =========================================================================
# Entry point
# =========================================================================

def main():
    """Run the MCP server on stdio."""
    logger.info("Starting Humanbound MCP server (stdio)")
    mcp.run(transport="stdio")
