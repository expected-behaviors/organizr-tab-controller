# Hardened Python base (Chainguard: distroless, minimal attack surface, non-root).
# Python images in this project use a locked-down base by default.
# https://www.chainguard.dev/chainguard-images/reference/python

ARG BASE=cgr.dev/chainguard/python:latest
ARG BASE_DEV=cgr.dev/chainguard/python:latest-dev

# ---- Builder: venv for clean prefix to copy ----
FROM ${BASE_DEV} AS builder
USER root
WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .

# ---- Runtime: distroless, no shell, non-root ----
FROM ${BASE}

LABEL maintainer="Jacob Dresdale"
LABEL description="Kubernetes controller that manages Organizr tabs via annotations"
LABEL org.opencontainers.image.source="https://github.com/jd4883/organizr-tab-controller"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv

USER nonroot
WORKDIR /app

ENTRYPOINT ["python", "-m", "organizr_tab_controller"]
