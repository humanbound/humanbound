# syntax=docker/dockerfile:1
# Build from source: wheel in stage 1, slim runtime in stage 2.
# Build from the REPO ROOT:  docker build -f docker/Dockerfile -t humanbound:dev .

FROM python:3.12-slim AS builder
WORKDIR /src
COPY . .
RUN pip install --no-cache-dir build \
    && python -m build --wheel --outdir /wheels

FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/humanbound/humanbound" \
    org.opencontainers.image.description="Humanbound CLI - open-source adversarial testing engine for AI agents" \
    org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONUNBUFFERED=1 \
    HOME=/home/hb
RUN useradd --create-home --uid 1000 hb \
    && mkdir -p /workspace \
    && chown hb:hb /workspace
COPY --from=builder /wheels /tmp/wheels
# discovery documents: ~99MB of unused Google API catalogs (fetched on demand if needed)
RUN pip install --no-cache-dir "$(ls /tmp/wheels/humanbound-*.whl)[engine]" \
    && rm -rf /tmp/wheels \
    /usr/local/lib/python3.12/site-packages/googleapiclient/discovery_cache/documents \
    && pip uninstall -y pip
USER hb
WORKDIR /workspace
ENTRYPOINT ["hb"]
CMD ["--help"]
