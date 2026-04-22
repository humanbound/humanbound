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

The `humanbound-cli` package on PyPI now resolves to a transitional stub that
depends on `humanbound` and emits a `DeprecationWarning` on import. This stub
will be yanked on or after **2026-06-20**. Please migrate before then.

See the [CHANGELOG](https://github.com/humanbound/humanbound/blob/main/CHANGELOG.md)
for details on the rename.
