# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Pattern registry for capability detection.

Each Pattern is one signal: a regex that, if matched in a source file
of the right language, contributes to setting a capability flag.

For Python patterns, an optional ``ast_verify`` callable is invoked on
the parsed source. It returns True if the imported symbol has a real
use site (not just a lone import). Non-Python patterns rely on regex
only (documented v1 limitation).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from .python_ast import has_use_site


@dataclass(frozen=True)
class Pattern:
    capability: str  # one of CAPABILITY_KEYS
    language: str  # "python" | "typescript"
    regex: re.Pattern
    signal: str  # human-readable label shown in evidence
    ast_verify: Callable[[str], bool] | None = None


def _use(name: str) -> Callable[[str], bool]:
    """Build an ast_verify that requires `name` to have a use site."""
    return lambda src: has_use_site(src, name)


PATTERNS: list[Pattern] = [
    # ---------- tools (Python) ----------
    Pattern(
        "tools", "python", re.compile(r"^\s*@tool\b", re.MULTILINE), "@tool decorator", _use("tool")
    ),
    Pattern(
        "tools", "python", re.compile(r"@\w+\.tool\b"), "@<server>.tool decorator (MCP/FastMCP)"
    ),
    Pattern(
        "tools",
        "python",
        re.compile(r"^\s*@function_tool\b", re.MULTILINE),
        "@function_tool decorator (OpenAI Agents SDK)",
        _use("function_tool"),
    ),
    Pattern(
        "tools",
        "python",
        re.compile(r"\bStructuredTool\("),
        "StructuredTool(...) instantiation (LangChain)",
        _use("StructuredTool"),
    ),
    Pattern(
        "tools",
        "python",
        re.compile(r"\btools\s*=\s*\["),
        "tools=[...] kwarg (OpenAI/Anthropic JSON tool schemas)",
    ),
    # ---------- tools (TypeScript) ----------
    Pattern("tools", "typescript", re.compile(r"from\s+['\"]ai['\"]"), "Vercel AI SDK import"),
    Pattern(
        "tools", "typescript", re.compile(r"@langchain/core/tools"), "LangChainJS tools import"
    ),
    Pattern("tools", "typescript", re.compile(r"@modelcontextprotocol/sdk"), "MCP TS SDK import"),
    Pattern(
        "tools",
        "typescript",
        re.compile(r"['\"]tools/call['\"]"),
        "MCP setRequestHandler('tools/call', ...)",
    ),
    # ---------- memory (Python) ----------
    Pattern(
        "memory",
        "python",
        re.compile(r"\bimport\s+chromadb\b"),
        "chromadb import",
        _use("chromadb"),
    ),
    Pattern(
        "memory",
        "python",
        re.compile(r"\bimport\s+pinecone\b"),
        "pinecone import",
        _use("pinecone"),
    ),
    Pattern(
        "memory",
        "python",
        re.compile(r"\bimport\s+weaviate\b"),
        "weaviate import",
        _use("weaviate"),
    ),
    Pattern(
        "memory",
        "python",
        re.compile(r"\bimport\s+qdrant_client\b"),
        "qdrant import",
        _use("qdrant_client"),
    ),
    Pattern(
        "memory", "python", re.compile(r"\bimport\s+lancedb\b"), "lancedb import", _use("lancedb")
    ),
    Pattern("memory", "python", re.compile(r"\bimport\s+faiss\b"), "faiss import", _use("faiss")),
    Pattern(
        "memory",
        "python",
        re.compile(r"\bfrom\s+langchain_community\.vectorstores\s+import\s+(\w+)"),
        "langchain_community.vectorstores import",
    ),
    Pattern(
        "memory",
        "python",
        re.compile(r"\bfrom\s+langchain\.memory\s+import\s+(\w+)"),
        "langchain.memory import",
    ),
    # ---------- memory (TypeScript) ----------
    Pattern(
        "memory",
        "typescript",
        re.compile(r"@pinecone-database/pinecone"),
        "@pinecone-database/pinecone import",
    ),
    Pattern(
        "memory",
        "typescript",
        re.compile(r"@qdrant/js-client-rest"),
        "@qdrant/js-client-rest import",
    ),
    Pattern("memory", "typescript", re.compile(r"['\"]chromadb['\"]"), "chromadb (TS) import"),
    # ---------- inter_agent (Python) ----------
    Pattern("inter_agent", "python", re.compile(r"\bfrom\s+crewai\b"), "crewai import"),
    Pattern("inter_agent", "python", re.compile(r"\bfrom\s+autogen\b"), "autogen import"),
    Pattern("inter_agent", "python", re.compile(r"\bfrom\s+langgraph\."), "langgraph import"),
    Pattern("inter_agent", "python", re.compile(r"\.add_node\("), "langgraph add_node call"),
    # ---------- inter_agent (TypeScript) ----------
    Pattern(
        "inter_agent",
        "typescript",
        re.compile(r"@langchain/langgraph"),
        "@langchain/langgraph import",
    ),
    # ---------- reasoning_model (Python) ----------
    Pattern(
        "reasoning_model",
        "python",
        re.compile(r"model\s*=\s*['\"]o[134][\w.-]*['\"]"),
        "OpenAI reasoning model (o1/o3/o4)",
    ),
    Pattern(
        "reasoning_model",
        "python",
        re.compile(r"model\s*=\s*['\"]deepseek-r1[\w.-]*['\"]"),
        "DeepSeek-R1 model",
    ),
    Pattern(
        "reasoning_model", "python", re.compile(r"\breasoning_effort\s*="), "reasoning_effort kwarg"
    ),
    Pattern(
        "reasoning_model",
        "python",
        re.compile(r"\bthinking\s*=\s*\{"),
        "Anthropic extended thinking kwarg",
    ),
    # ---------- reasoning_model (TypeScript) ----------
    Pattern(
        "reasoning_model",
        "typescript",
        re.compile(r"model:\s*['\"]o[134][\w.-]*['\"]"),
        "OpenAI reasoning model (o1/o3/o4) — TS",
    ),
    Pattern(
        "reasoning_model",
        "typescript",
        re.compile(r"reasoning_effort\s*:"),
        "reasoning_effort field — TS",
    ),
]
