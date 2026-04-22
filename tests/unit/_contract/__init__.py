# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Contract-fidelity layer for CLI unit tests.

This package ships hand-authored Pydantic mirrors of the Humanbound API
response shapes that the CLI consumes over HTTP. Each mirror uses
``model_config = ConfigDict(extra="allow")`` so we catch missing required
fields and type mismatches without failing on benign additions.

The paired test ``tests/unit/test_contract_fidelity.py`` validates that
every mock response fixture in the test suite round-trips through its
mirror schema — failing loudly and precisely whenever a fixture drifts
from the declared API contract.

Each schema carries an ``__upstream_source__`` identifier that
maintainers use when periodically syncing mirrors against the upstream
Humanbound API; the sync process itself is internal to the maintainer
team and is not part of the public test suite.
"""
