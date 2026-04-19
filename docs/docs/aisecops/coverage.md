# Test Coverage

Track which attack categories, techniques, and vectors have been tested against your AI agent. Coverage information helps identify blind spots in your security testing.

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
