---
description: "Test coverage tracks which attack categories and techniques have run against your agent, surfacing blind spots in your security testing plan."
keywords:
  - test coverage
  - hb coverage command
  - coverage gaps
  - attack category coverage
  - AFL-style coverage
  - security testing blind spots
---

# Test Coverage

The `hb coverage` command shows which attack categories and techniques have run against your agent, and which haven't — making it easy to spot blind spots in the security testing plan. Use `hb coverage --gaps` to list the untested categories and `hb coverage --json` for machine-readable output. Coverage tracking uses an AFL-style (American Fuzzy Lop) coverage-guided approach with 5 priority levels, so high-impact vulnerabilities are tested first.

## View Coverage Summary

```bash
hb coverage
```

## Show Untested Categories

```bash
hb coverage --gaps
```

## Export as JSON

```bash
hb coverage --json
```

Coverage tracking follows an AFL-style (American Fuzzy Lop) coverage-guided approach with 5 priority levels, ensuring high-impact vulnerabilities are tested first.
