# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""CLI command modules."""

from . import (
    api_keys,
    assessments,
    auth,
    campaigns,
    completion,
    config_cmd,
    connect,
    docs,
    experiments,
    findings,
    firewall,
    guardrails,
    logs,
    members,
    monitor,
    orgs,
    posture,
    projects,
    providers,
    report,
    sentinel,
    test,
    upload_logs,
    webhooks,
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
