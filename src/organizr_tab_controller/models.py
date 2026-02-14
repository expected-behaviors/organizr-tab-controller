"""Data models for Organizr Tab Controller."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Annotation constants
# ---------------------------------------------------------------------------

ANNOTATION_PREFIX = "organizr.expectedbehaviors.com"
"""Annotation prefix used on Kubernetes resources to declare Organizr tab config."""


def ann(key: str) -> str:
    """Return the fully-qualified annotation key for a short key name."""
    return f"{ANNOTATION_PREFIX}/{key}"


# All recognised annotation suffixes
ANNOTATION_ENABLED = "enabled"
ANNOTATION_NAME = "name"
ANNOTATION_URL = "url"
ANNOTATION_URL_LOCAL = "url-local"
ANNOTATION_PING_URL = "ping-url"
ANNOTATION_IMAGE = "image"
ANNOTATION_TYPE = "type"
ANNOTATION_GROUP_ID = "group-id"
ANNOTATION_CATEGORY_ID = "category-id"
ANNOTATION_ORDER = "order"
ANNOTATION_DEFAULT = "default"
ANNOTATION_ACTIVE = "active"
ANNOTATION_SPLASH = "splash"
ANNOTATION_PING = "ping"
ANNOTATION_PRELOAD = "preload"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TabType(int, Enum):
    """Organizr tab type (maps to the integer the API expects)."""

    INTERNAL = 0
    IFRAME = 1
    NEW_WINDOW = 2

    @classmethod
    def from_annotation(cls, value: str) -> TabType:
        """Parse a human-friendly annotation value into a TabType."""
        mapping: dict[str, TabType] = {
            "internal": cls.INTERNAL,
            "iframe": cls.IFRAME,
            "new-window": cls.NEW_WINDOW,
            "new_window": cls.NEW_WINDOW,
            "newwindow": cls.NEW_WINDOW,
            # Also accept raw ints as strings
            "0": cls.INTERNAL,
            "1": cls.IFRAME,
            "2": cls.NEW_WINDOW,
        }
        normalised = value.strip().lower()
        if normalised not in mapping:
            raise ValueError(f"Unknown tab type annotation value: {value!r}")
        return mapping[normalised]


class SyncPolicy(str, Enum):
    """How the controller reconciles tabs with Organizr."""

    UPSERT = "upsert"
    """Create / update only. Never delete tabs."""

    SYNC = "sync"
    """Full reconciliation: create, update, and delete orphaned tabs."""


# ---------------------------------------------------------------------------
# Tab model
# ---------------------------------------------------------------------------


class Tab(BaseModel):
    """Represents a single Organizr tab (desired or actual state)."""

    # Identity ------------------------------------------------------------------
    id: int | None = Field(default=None, description="Organizr-assigned tab ID (None for desired state)")
    name: str = Field(..., min_length=1, description="Tab display name")

    # URLs ----------------------------------------------------------------------
    url: str = Field(..., description="Primary tab URL (must include scheme)")
    url_local: str | None = Field(default=None, description="Local/RFC1918 URL override")
    ping_url: str | None = Field(default=None, description="host:port for ping checks (no scheme)")

    # Display -------------------------------------------------------------------
    image: str | None = Field(default=None, description="Icon identifier or full image URL")
    tab_type: TabType = Field(default=TabType.IFRAME, description="How the tab opens")

    # Access / grouping ---------------------------------------------------------
    group_id: int = Field(default=1, description="Minimum Organizr group that can see this tab")
    category_id: int | None = Field(default=None, description="Organizr category ID")

    # Ordering / flags ----------------------------------------------------------
    order: int | None = Field(default=None, description="Tab order (position)")
    default: bool = Field(default=False, description="Whether this is the default tab on login")
    active: bool = Field(default=True, description="Whether the tab is enabled")
    splash: bool = Field(default=False, description="Show on splash/login screen")
    ping: bool = Field(default=True, description="Enable ping health check")
    preload: bool = Field(default=False, description="Preload the tab on login")

    # Tracking ------------------------------------------------------------------
    managed_by: str | None = Field(
        default=None,
        description="Controller-assigned tracking key (e.g. namespace/resource-kind/name) to correlate with K8s source",
    )

    # Helpers -------------------------------------------------------------------

    def to_api_payload(self) -> dict[str, Any]:
        """Serialize to the dict expected by the Organizr v2 API."""
        payload: dict[str, Any] = {
            "name": self.name,
            "url": self.url,
            "url_local": self.url_local or "",
            "ping_url": self.ping_url or "",
            "image": self.image or "",
            "type": self.tab_type.value,
            "group_id": self.group_id,
            "category_id": self.category_id if self.category_id is not None else 0,
            "default": 1 if self.default else 0,
            "enabled": 1 if self.active else 0,
            "splash": 1 if self.splash else 0,
            "ping": 1 if self.ping else 0,
            "preload": 1 if self.preload else 0,
        }
        if self.order is not None:
            payload["order"] = self.order
        if self.id is not None:
            payload["id"] = self.id
        return payload

    def to_v1_payload(self, action: str = "addNewTab") -> dict[str, str]:
        """Serialize to the ``data[key]`` format expected by the Organizr v1 API.

        Parameters
        ----------
        action:
            One of ``addNewTab``, ``editTab``, ``changeType``.
        """
        payload: dict[str, str] = {
            "data[action]": action,
            "data[tabName]": self.name,
            "data[tabURL]": self.url,
            "data[tabLocalURL]": self.url_local or "null",
            "data[pingURL]": self.ping_url or "null",
            "data[tabImage]": self.image or "",
            "data[tabType]": str(self.tab_type.value),
            "data[tabGroupID]": str(self.group_id),
            "data[tabCategoryID]": str(self.category_id or 0),
            "data[default]": "1" if self.default else "0",
            "data[enabled]": "1" if self.active else "0",
            "data[splash]": "1" if self.splash else "0",
            "data[ping]": "1" if self.ping else "0",
            "data[preload]": "1" if self.preload else "0",
        }
        if self.order is not None:
            payload["data[tabOrder]"] = str(self.order)
        if self.id is not None:
            payload["data[id]"] = str(self.id)
        return payload

    def content_matches(self, other: Tab) -> bool:
        """Check whether two tabs are semantically equal (ignoring ``id`` and ``order``)."""
        return (
            self.name == other.name
            and self.url == other.url
            and (self.url_local or "") == (other.url_local or "")
            and (self.ping_url or "") == (other.ping_url or "")
            and (self.image or "") == (other.image or "")
            and self.tab_type == other.tab_type
            and self.group_id == other.group_id
            and (self.category_id or 0) == (other.category_id or 0)
            and self.default == other.default
            and self.active == other.active
            and self.splash == other.splash
            and self.ping == other.ping
            and self.preload == other.preload
        )


# ---------------------------------------------------------------------------
# Kubernetes resource reference (lightweight)
# ---------------------------------------------------------------------------


class K8sResourceRef(BaseModel):
    """Minimal reference to a Kubernetes resource that has Organizr annotations."""

    api_version: str
    kind: str
    namespace: str
    name: str
    uid: str
    annotations: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)

    # Ingress-specific helpers (populated only for Ingress resources)
    ingress_hosts: list[str] = Field(default_factory=list)

    # Service-specific helpers
    service_cluster_ip: str | None = None
    service_ports: list[int] = Field(default_factory=list)

    @property
    def tracking_key(self) -> str:
        """Stable key used to correlate this K8s resource with an Organizr tab."""
        return f"{self.namespace}/{self.kind.lower()}/{self.name}"
