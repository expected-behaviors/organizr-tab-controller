# ---- Build stage: install dependencies in a venv ----
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml .
COPY src/ src/
RUN /opt/venv/bin/pip install --no-cache-dir .

# ---- Runtime stage: minimal image ----
FROM python:3.12-slim AS runtime

LABEL maintainer="Jacob Dresdale"
LABEL description="Kubernetes controller that manages Organizr tabs via annotations"
LABEL org.opencontainers.image.source="https://github.com/jd4883/organizr-tab-controller"

# Create non-root user
RUN groupadd -r controller && useradd -r -g controller -d /home/controller -s /sbin/nologin controller

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Security: read-only root filesystem friendly
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

USER controller
WORKDIR /home/controller

ENTRYPOINT ["python", "-m", "organizr_tab_controller"]
