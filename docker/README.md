# Docker images

Contributor notes for the container images. **User-facing docs live at
[docs/docs/integrations/docker.md](../docs/docs/integrations/docker.md)**
(published at https://docs.humanbound.ai).

## Files

| File | Image | Extras |
|---|---|---|
| `Dockerfile` | `ghcr.io/humanbound/humanbound` — the default CLI image | `[engine]` |

Future variants follow the `Dockerfile.<variant>` convention
(e.g. `Dockerfile.mcp`, `Dockerfile.firewall`).

## Building locally

The build context is the **repo root** (the wheel is built from source in
stage 1), so always pass `-f`:

```bash
docker build -f docker/Dockerfile -t humanbound:dev .
```

The single `.dockerignore` lives at the repo root and is shared by all
variants.

## Smoke test

```bash
docker run --rm humanbound:dev --version
docker run --rm --entrypoint python humanbound:dev -c "import openai, anthropic, google.generativeai"
```

## CI

- PRs to `main` touching `docker/**`, `.dockerignore`, `pyproject.toml`, or
  the workflow file itself trigger a build + smoke test
  (`.github/workflows/docker.yml`).
- Version tags (`v*`) publish multi-arch (amd64 + arm64) images to GHCR with
  `:X.Y.Z`, `:X.Y`, `:X`, and `:latest` tags (`.github/workflows/release.yml`).
