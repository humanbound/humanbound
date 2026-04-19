"""CLI command modules."""

from . import (
    auth, orgs, projects, experiments, test, logs, posture,
    guardrails, docs, providers, findings, api_keys, members,
    campaigns, upload_logs, sentinel,
    completion, connect, report, monitor,
    webhooks, assessments, firewall, config_cmd,
)

# MCP command is optional — only available when mcp SDK is installed
try:
    from . import mcp
except ImportError:
    mcp = None

__all__ = [
    "auth",
    "orgs",
    "projects",
    "experiments",
    "test",
    "logs",
    "posture",
    "guardrails",
    "docs",
    "providers",
    "findings",
    "api_keys",
    "members",
    "campaigns",
    "upload_logs",
    "sentinel",
    "completion",
    "connect",
    "report",
    "monitor",
    "webhooks",
    "assessments",
    "firewall",
    "mcp",
]
