# Stage 1 (builder): install the app and its locked dependencies into a virtual environment.
FROM python:3.12-slim AS builder

# uv binary copied from its official image, pinned to the version this project uses.
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /bin/uv

# Use the Python that ships in this image; never download a different one.
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies first, in their own layer: Docker reuses it from cache until
# pyproject.toml or uv.lock changes. --locked fails the build if uv.lock is out of date.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then the app itself. README.md is required by the package metadata.
# --no-editable copies the code into the virtual environment, so the runtime
# stage only needs /app/.venv.
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable


# Stage 2 (runtime): Python plus the virtual environment. No uv, no source tree, no tests.
FROM python:3.12-slim

# Unprivileged system user: no home directory, no login shell.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

# Copied as root-owned: the app user can read and run the code but cannot modify it.
COPY --from=builder /app/.venv /app/.venv

# SQLite needs a writable directory. This is the only path the app user can write to.
RUN mkdir /app/data && chown appuser /app/data

# PATH: use the virtual environment's python and uvicorn.
# PYTHONUNBUFFERED: logs go straight to stdout, so `docker logs` shows them immediately.
# DATABASE_URL: local SQLite default (four slashes = absolute path). In the cloud the
# platform sets DATABASE_URL instead.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL="sqlite:////app/data/incidents.db"

USER appuser

# Documents the port the app listens on; `docker run -p` does the actual mapping.
EXPOSE 8080

# 0.0.0.0 = listen on all network interfaces, so traffic from outside the container arrives.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
