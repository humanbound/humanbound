# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Local runner — runs the engine in-process."""

from humanbound_cli.engine.local_runner import LocalTestRunner as LocalRunner  # noqa: F401

__all__ = ["LocalRunner"]
