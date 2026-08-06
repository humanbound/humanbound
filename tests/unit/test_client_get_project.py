# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""HumanboundClient.get_project — single-project GET endpoint."""

from unittest.mock import MagicMock

from humanbound_cli.client import HumanboundClient


def test_get_project_calls_correct_endpoint():
    client = HumanboundClient.__new__(HumanboundClient)  # bypass __init__
    client.get = MagicMock(return_value={"id": "p1", "name": "test"})

    result = client.get_project("p1")

    client.get.assert_called_once_with("projects/p1")
    assert result == {"id": "p1", "name": "test"}
