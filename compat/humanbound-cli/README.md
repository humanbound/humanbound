# humanbound-cli — DEPRECATED

This package has been **renamed** to [`humanbound`](https://pypi.org/project/humanbound/).

Please migrate:

```bash
pip uninstall humanbound-cli
pip install humanbound
```

The `hb` CLI command is unchanged. The Python import path is unchanged
(`humanbound_cli` internals remain; the new `humanbound` public SDK adds a
stable library surface — see [the main repo](https://github.com/humanbound/humanbound)).

The `humanbound-cli` package on PyPI is a transitional stub that depends on
`humanbound`. **Version 1.2.2 is the final release** — no further updates will
be published. Existing `humanbound-cli` installs continue to pull in the
current `humanbound` package, but new development tracks the renamed package
only. Please migrate.

See the [CHANGELOG](https://github.com/humanbound/humanbound/blob/main/CHANGELOG.md)
for details on the rename.
