"""Configuration management for the Organizr Tab Controller.

Settings are loaded from (highest priority wins):
1. Environment variables  (``ORGANIZR_*``)
2. Kubernetes Secret mount (``/var/run/secrets/organizr/api-key``)
3. Defaults
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

from organizr_tab_controller.models import SyncPolicy

# Default path where a K8s-mounted secret would appear
_DEFAULT_SECRET_PATH = "/var/run/secrets/organizr/api-key"


class ControllerSettings(BaseSettings):
    """All configurable knobs for the controller.

    Values can be set via environment variables with the ``ORGANIZR_`` prefix,
    e.g. ``ORGANIZR_API_URL``, ``ORGANIZR_API_KEY``, etc.
    """

    # Organizr connection -------------------------------------------------------
    api_url: str = Field(
        ...,
        description="Base URL of the Organizr instance (e.g. https://organizr.expectedbehaviors.com)",
    )
    api_key: str = Field(
        default="",
        description="Organizr API key. If empty, the controller tries to read from the secret file path.",
    )
    api_key_file: str = Field(
        default=_DEFAULT_SECRET_PATH,
        description="Path to a file containing the Organizr API key (K8s Secret mount).",
    )
    api_version: str = Field(
        default="v2",
        description="Organizr API version to use (v2 preferred, v1 as fallback).",
    )
    api_timeout: float = Field(
        default=30.0,
        description="HTTP timeout in seconds for Organizr API calls.",
    )

    # Kubernetes watching -------------------------------------------------------
    watch_namespaces: list[str] = Field(
        default_factory=list,
        description=(
            "Namespaces to watch. Empty list means watch all namespaces. "
            "Comma-separated string also accepted via env var."
        ),
    )
    watch_resource_types: list[str] = Field(
        default_factory=lambda: [
            "ingresses",
            "services",
            "deployments",
            "statefulsets",
            "daemonsets",
        ],
        description="Kubernetes resource types to watch for annotations.",
    )

    # Reconciliation ------------------------------------------------------------
    sync_policy: SyncPolicy = Field(
        default=SyncPolicy.UPSERT,
        description="Sync policy: 'upsert' (create/update only) or 'sync' (create/update/delete).",
    )
    reconcile_interval: int = Field(
        default=60,
        ge=10,
        description="Seconds between full reconciliation sweeps.",
    )

    # HA / leader election ------------------------------------------------------
    enable_leader_election: bool = Field(
        default=False,
        description="Enable leader election for HA deployments (multiple replicas).",
    )
    leader_election_namespace: str = Field(
        default="default",
        description="Namespace for the leader-election Lease object.",
    )
    leader_election_name: str = Field(
        default="organizr-tab-controller-leader",
        description="Name of the leader-election Lease object.",
    )

    # Logging -------------------------------------------------------------------
    log_level: str = Field(
        default="INFO",
        description="Log level (DEBUG, INFO, WARNING, ERROR).",
    )
    log_format: str = Field(
        default="json",
        description="Log format: 'json' (structured) or 'console' (human-readable).",
    )

    # ---- Validators -----------------------------------------------------------

    @field_validator("watch_namespaces", mode="before")
    @classmethod
    def _parse_comma_separated(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [ns.strip() for ns in v.split(",") if ns.strip()]
        return v

    @field_validator("watch_resource_types", mode="before")
    @classmethod
    def _parse_resource_types(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [rt.strip() for rt in v.split(",") if rt.strip()]
        return v

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, v: str) -> str:
        return v.upper()

    # ---- Post-init: resolve API key from file if needed -----------------------

    def model_post_init(self, _context: object) -> None:
        """If ``api_key`` is empty, attempt to read it from the secret file."""
        if not self.api_key:
            self.api_key = self._read_api_key_file()

    def _read_api_key_file(self) -> str:
        path = Path(self.api_key_file)
        if path.is_file():
            return path.read_text().strip()
        return ""

    # ---- Pydantic-settings config ---------------------------------------------

    model_config = {
        "env_prefix": "ORGANIZR_",
        "env_nested_delimiter": "__",
        "case_sensitive": False,
    }


def load_settings() -> ControllerSettings:
    """Load and validate controller settings from the environment.

    Returns
    -------
    ControllerSettings
        Fully-resolved configuration.

    Raises
    ------
    pydantic.ValidationError
        If required settings are missing or invalid.
    """
    # Allow ORGANIZR_API_URL to also be read from ORGANIZR_URL for convenience
    if "ORGANIZR_API_URL" not in os.environ and "ORGANIZR_URL" in os.environ:
        os.environ["ORGANIZR_API_URL"] = os.environ["ORGANIZR_URL"]

    return ControllerSettings()  # type: ignore[call-arg]
