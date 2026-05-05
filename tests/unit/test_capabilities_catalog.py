# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Parametrized coverage for every signal in the pattern registry.

Each row asserts: a tiny synthetic source string matches the pattern
and (for python) the AST verifier accepts it.
"""

from __future__ import annotations

import pytest

from humanbound_cli.extractors.capabilities.patterns import PATTERNS

CASES = [
    # (capability, language, source, signal_substring)
    # ---- tools ----
    ("tools", "python", "from langchain_core.tools import tool\n@tool\ndef x(): pass\n", "@tool"),
    (
        "tools",
        "python",
        "from mcp.server.fastmcp import FastMCP\nmcp=FastMCP('a')\n@mcp.tool()\ndef y(): pass\n",
        "mcp.tool",
    ),
    (
        "tools",
        "python",
        "from agents import function_tool\n@function_tool\ndef z(): pass\n",
        "function_tool",
    ),
    (
        "tools",
        "python",
        "from langchain_core.tools import StructuredTool\nt=StructuredTool(name='a', func=lambda:1, description='')\n",
        "StructuredTool",
    ),
    (
        "tools",
        "python",
        "from openai import OpenAI\nOpenAI().chat.completions.create(model='gpt-4', messages=[], tools=[{'type':'function'}])\n",
        "tools=[...]",
    ),
    (
        "tools",
        "typescript",
        "import { tool } from 'ai';\nconst t = tool({ name: 'x', execute: async () => 'y' });\n",
        "tool({",
    ),
    (
        "tools",
        "typescript",
        "import { tool } from '@langchain/core/tools';\nconst t = tool(...);\n",
        "@langchain/core/tools",
    ),
    (
        "tools",
        "typescript",
        "import { Server } from '@modelcontextprotocol/sdk/server/index.js';\nserver.setRequestHandler('tools/call', async () => {});\n",
        "tools/call",
    ),
    # ---- memory ----
    ("memory", "python", "import chromadb\nchromadb.PersistentClient()\n", "chromadb"),
    ("memory", "python", "import pinecone\npinecone.init()\n", "pinecone"),
    (
        "memory",
        "python",
        "from langchain_community.vectorstores import Chroma\nChroma()\n",
        "vectorstores",
    ),
    (
        "memory",
        "python",
        "from langchain.memory import ConversationBufferMemory\nConversationBufferMemory()\n",
        "langchain.memory",
    ),
    (
        "memory",
        "typescript",
        "import { Pinecone } from '@pinecone-database/pinecone';\nconst p = new Pinecone();\n",
        "@pinecone-database/pinecone",
    ),
    # ---- inter_agent ----
    (
        "inter_agent",
        "python",
        "from crewai import Agent, Crew\nCrew(agents=[Agent(role='a', goal='b', backstory='c')])\n",
        "crewai",
    ),
    (
        "inter_agent",
        "python",
        "from langgraph.graph import Graph\ng=Graph()\ng.add_node('x', lambda s: s)\n",
        "langgraph",
    ),
    (
        "inter_agent",
        "python",
        "from autogen import AssistantAgent\nAssistantAgent(name='a')\n",
        "autogen",
    ),
    # ---- reasoning_model ----
    (
        "reasoning_model",
        "python",
        "from openai import OpenAI\nOpenAI().chat.completions.create(model='o1-preview', messages=[])\n",
        "o1",
    ),
    (
        "reasoning_model",
        "python",
        "from openai import OpenAI\nOpenAI().chat.completions.create(model='o3-mini', messages=[], reasoning_effort='high')\n",
        "reasoning_effort",
    ),
    (
        "reasoning_model",
        "python",
        "from anthropic import Anthropic\nAnthropic().messages.create(model='claude-sonnet-4-6', thinking={'type':'enabled','budget_tokens':1024}, messages=[])\n",
        "thinking=",
    ),
    (
        "reasoning_model",
        "typescript",
        "import { generateText } from 'ai';\nawait generateText({ model: 'o1-preview', messages: [] });\n",
        "o1",
    ),
]


@pytest.mark.parametrize("capability,language,source,signal_substring", CASES)
def test_signal_matches_at_least_one_pattern(capability, language, source, signal_substring):
    """For each canonical example, at least one registered pattern matches
    and (where applicable) the AST verifier accepts."""
    matched = False
    for pat in PATTERNS:
        if pat.capability != capability or pat.language != language:
            continue
        if pat.regex.search(source) is None:
            continue
        if pat.language == "python" and pat.ast_verify is not None:
            if not pat.ast_verify(source):
                continue
        matched = True
        break
    assert matched, (
        f"No pattern in registry matched the canonical {capability!r} "
        f"example for {language!r}. Add a pattern containing {signal_substring!r}."
    )
