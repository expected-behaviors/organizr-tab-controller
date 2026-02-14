"""Tab reconciler — converts K8s resource refs into desired Organizr tabs and
diffs them against the actual state to produce create / update / delete actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from organizr_tab_controller.icon_matcher import match_icon
from organizr_tab_controller.models import (
    ANNOTATION_PREFIX,
    K8sResourceRef,
    SyncPolicy,
    Tab,
    TabType,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Reconciliation actions
# ---------------------------------------------------------------------------


@dataclass
class ReconcileActions:
    """The set of API calls the controller should make after a reconciliation."""

    to_create: list[Tab] = field(default_factory=list)
    to_update: list[Tab] = field(default_factory=list)
    to_delete: list[Tab] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.to_create and not self.to_update and not self.to_delete

    def summary(self) -> str:
        return f"create={len(self.to_create)} update={len(self.to_update)} delete={len(self.to_delete)}"


# ---------------------------------------------------------------------------
# Tab builder — annotations + passive derivation
# ---------------------------------------------------------------------------


def _ann(key: str) -> str:
    """Fully-qualified annotation key."""
    return f"{ANNOTATION_PREFIX}/{key}"


def _bool_ann(annotations: dict[str, str], key: str, default: bool) -> bool:
    """Parse a boolean annotation value."""
    raw = annotations.get(_ann(key), "").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    return default


def _int_ann(annotations: dict[str, str], key: str, default: int | None) -> int | None:
    """Parse an integer annotation value."""
    raw = annotations.get(_ann(key), "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid_int_annotation", key=key, value=raw)
        return default


def build_desired_tab(ref: K8sResourceRef) -> Tab:
    """Construct a desired :class:`Tab` from a Kubernetes resource reference.

    Uses explicit annotations where set, then falls back to passive derivation.

    Default scheme conventions:
    - External URL (``url``): **https** (Ingress host or external-dns hostname)
    - Local URL (``url_local``): **http** (Service name + namespace internal DNS)
    """
    ann = ref.annotations

    # ---- Name (passive: from label or resource name) --------------------------
    name = ann.get(_ann("name"), "").strip()
    if not name:
        name = ref.labels.get("app.kubernetes.io/name", "") or ref.name
        name = name.replace("-", " ").replace("_", " ").title()

    # ---- URL — external address (https by default) ----------------------------
    # Priority: explicit annotation > Ingress host > external-dns hostname > fallback
    url = ann.get(_ann("url"), "").strip()
    if not url:
        if ref.ingress_hosts:
            # Ingress: use the exact host from the Ingress spec
            url = f"https://{ref.ingress_hosts[0]}"
        else:
            # Non-Ingress: try external-dns hostname annotation
            ext_hostname = ann.get("external-dns.alpha.kubernetes.io/hostname", "")
            if ext_hostname:
                url = f"https://{ext_hostname}"
            else:
                # Last resort: construct from resource name + namespace
                url = f"https://{ref.name}.{ref.namespace}"

    # ---- URL local — internal cluster address (http by default) ---------------
    # Priority: explicit annotation > Ingress backend service > Service itself
    url_local = ann.get(_ann("url-local"), "").strip() or None
    if url_local is None:
        if ref.kind.lower() == "ingress" and ref.ingress_backend_service_name:
            # Ingress: use the backend service name from the Ingress spec
            svc_name = ref.ingress_backend_service_name
            port = ref.ingress_backend_service_port or 80
            url_local = f"http://{svc_name}.{ref.namespace}.svc.cluster.local:{port}"
        elif ref.kind.lower() == "service":
            # Service: use the service's own name and namespace
            port = ref.service_ports[0] if ref.service_ports else 80
            url_local = f"http://{ref.name}.{ref.namespace}.svc.cluster.local:{port}"

    # ---- Ping URL (host:port, no scheme) --------------------------------------
    # Priority: explicit annotation > backend service > Service itself > Ingress host
    ping_url = ann.get(_ann("ping-url"), "").strip() or None
    if ping_url is None:
        if ref.kind.lower() == "ingress" and ref.ingress_backend_service_name:
            # Ingress: ping the backend service inside the cluster
            svc_name = ref.ingress_backend_service_name
            port = ref.ingress_backend_service_port or 80
            ping_url = f"{svc_name}.{ref.namespace}:{port}"
        elif ref.kind.lower() == "service" and ref.service_ports:
            # Service: ping the service itself
            ping_url = f"{ref.name}.{ref.namespace}:{ref.service_ports[0]}"

    # ---- Image (passive: icon matching by app name) ---------------------------
    image_ann = ann.get(_ann("image"), "").strip()
    if image_ann:
        # Could be a known name or a URL; match_icon handles both
        image = match_icon(image_ann) or image_ann
    else:
        # Try matching from the app label or resource name
        app_name = ref.labels.get("app.kubernetes.io/name", "") or ref.name
        image = match_icon(app_name)

    # ---- Tab type -------------------------------------------------------------
    type_ann = ann.get(_ann("type"), "").strip()
    if type_ann:
        tab_type = TabType.from_annotation(type_ann)
    else:
        tab_type = TabType.IFRAME

    # ---- Other fields ---------------------------------------------------------
    group_id = _int_ann(ann, "group-id", 1) or 1
    category_id = _int_ann(ann, "category-id", None)
    order = _int_ann(ann, "order", None)
    is_default = _bool_ann(ann, "default", False)
    active = _bool_ann(ann, "active", True)
    splash = _bool_ann(ann, "splash", False)
    ping_enabled = _bool_ann(ann, "ping", ping_url is not None)
    preload = _bool_ann(ann, "preload", False)

    return Tab(
        name=name,
        url=url,
        url_local=url_local,
        ping_url=ping_url,
        image=image,
        tab_type=tab_type,
        group_id=group_id,
        category_id=category_id,
        order=order,
        default=is_default,
        active=active,
        splash=splash,
        ping=ping_enabled,
        preload=preload,
        managed_by=ref.tracking_key,
    )


# ---------------------------------------------------------------------------
# Reconciler
# ---------------------------------------------------------------------------


# Controller uses a URL-based naming convention to store the tracking key.
# Since Organizr doesn't have a custom "managed_by" field, we correlate
# tabs by their URL (primary) and name (secondary).


def _match_tab_by_url(desired: Tab, actual_tabs: list[Tab]) -> Tab | None:
    """Find an existing Organizr tab whose URL matches the desired tab."""
    for existing in actual_tabs:
        if existing.url == desired.url:
            return existing
    return None


def _match_tab_by_name(desired: Tab, actual_tabs: list[Tab]) -> Tab | None:
    """Fallback: match by tab name (case-insensitive)."""
    desired_lower = desired.name.lower()
    for existing in actual_tabs:
        if existing.name.lower() == desired_lower:
            return existing
    return None


def reconcile(
    desired_refs: list[K8sResourceRef],
    actual_tabs: list[Tab],
    sync_policy: SyncPolicy,
) -> ReconcileActions:
    """Compute the set of API actions needed to reconcile desired state with actual.

    Parameters
    ----------
    desired_refs:
        Kubernetes resources annotated with Organizr tab config.
    actual_tabs:
        Current tabs fetched from the Organizr API.
    sync_policy:
        ``upsert`` or ``sync``.

    Returns
    -------
    ReconcileActions
        The creates, updates, and deletes to execute.
    """
    actions = ReconcileActions()

    # Build desired tabs
    desired_tabs: list[Tab] = []
    for ref in desired_refs:
        try:
            desired_tabs.append(build_desired_tab(ref))
        except Exception:
            logger.exception("build_tab_error", resource=ref.tracking_key)

    # Track which actual tabs are "claimed" by a desired tab
    claimed_ids: set[int] = set()

    for desired in desired_tabs:
        # Try to find a matching existing tab
        existing = _match_tab_by_url(desired, actual_tabs) or _match_tab_by_name(desired, actual_tabs)

        if existing and existing.id is not None:
            claimed_ids.add(existing.id)
            # Check if an update is needed
            if not desired.content_matches(existing):
                # Carry over the existing ID and order if not explicitly set
                updated = desired.model_copy(
                    update={
                        "id": existing.id,
                        "order": desired.order if desired.order is not None else existing.order,
                    }
                )
                actions.to_update.append(updated)
                logger.info(
                    "tab_needs_update",
                    name=desired.name,
                    id=existing.id,
                    managed_by=desired.managed_by,
                )
            else:
                logger.debug("tab_up_to_date", name=desired.name, id=existing.id)
        else:
            # New tab
            actions.to_create.append(desired)
            logger.info("tab_needs_create", name=desired.name, managed_by=desired.managed_by)

    # Deletions (only in sync mode)
    if sync_policy == SyncPolicy.SYNC:
        for existing in actual_tabs:
            if existing.id is not None and existing.id not in claimed_ids:
                # Don't delete internal Organizr tabs (Homepage, Settings)
                if existing.tab_type == TabType.INTERNAL:
                    logger.debug("skipping_internal_tab", name=existing.name, id=existing.id)
                    continue
                actions.to_delete.append(existing)
                logger.info("tab_needs_delete", name=existing.name, id=existing.id)

    logger.info("reconcile_complete", **{"actions": actions.summary()})
    return actions
