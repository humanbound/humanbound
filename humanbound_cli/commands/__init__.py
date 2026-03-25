"""CLI command modules."""

from . import (
    auth, orgs, projects, experiments, init, test, logs, posture,
    guardrails, docs, providers, findings, api_keys, members,
    coverage, campaigns, upload_logs, sentinel, discover,
    connectors, inventory, completion, connect, report, monitor,
    webhooks, assessments, firewall,
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
    "init",
    "test",
    "logs",
    "posture",
    "guardrails",
    "docs",
    "providers",
    "findings",
    "api_keys",
    "members",
    "coverage",
    "campaigns",
    "upload_logs",
    "sentinel",
    "discover",
    "connectors",
    "inventory",
    "completion",
    "connect",
    "report",
    "monitor",
    "webhooks",
    "assessments",
    "firewall",
    "mcp",
]
