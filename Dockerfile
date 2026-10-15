# Resolve tag updates deliberately; both upstream images are digest-pinned.
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS python

FROM python AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

# Dependency layers survive application edits. --locked rejects stale lockfiles.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --python /usr/local/bin/python

FROM python AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --gid 1000 triage \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin triage \
    && mkdir /app/results \
    && chown 1000:1000 /app/results

# Code and benchmark data remain root-owned. Only results are writable.
# A final held-out run needs a persistent host task directory, not this layer.
COPY --from=builder /app/.venv /app/.venv
COPY data/fixture ./data/fixture
COPY data/tasks.json ./data/tasks.json
USER 1000:1000
ENTRYPOINT ["dep-triage"]
CMD ["--help"]
