"""Kubernetes resource watcher.

Watches Ingresses, Services, Deployments, StatefulSets, DaemonSets (and any
other configured resource type) across one or more namespaces for the
``organizr.expectedbehaviors.com/enabled`` annotation.

The watcher produces :class:`K8sResourceRef` objects that downstream
components use to derive desired Organizr tabs.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import structlog
from kubernetes import client, config, watch

from organizr_tab_controller.models import ANNOTATION_PREFIX, K8sResourceRef

logger = structlog.get_logger(__name__)

# Maps user-friendly resource type names to (API group function, list method name)
_RESOURCE_TYPE_MAP: dict[str, tuple[str, str]] = {
    "ingresses": ("NetworkingV1Api", "list_ingress_for_all_namespaces"),
    "services": ("CoreV1Api", "list_service_for_all_namespaces"),
    "deployments": ("AppsV1Api", "list_deployment_for_all_namespaces"),
    "statefulsets": ("AppsV1Api", "list_stateful_set_for_all_namespaces"),
    "daemonsets": ("AppsV1Api", "list_daemon_set_for_all_namespaces"),
}

_RESOURCE_TYPE_NS_MAP: dict[str, tuple[str, str]] = {
    "ingresses": ("NetworkingV1Api", "list_namespaced_ingress"),
    "services": ("CoreV1Api", "list_namespaced_service"),
    "deployments": ("AppsV1Api", "list_namespaced_deployment"),
    "statefulsets": ("AppsV1Api", "list_namespaced_stateful_set"),
    "daemonsets": ("AppsV1Api", "list_namespaced_daemon_set"),
}


def load_k8s_config() -> None:
    """Load Kubernetes configuration (in-cluster preferred, fallback to kubeconfig)."""
    try:
        config.load_incluster_config()
        logger.info("k8s_config_loaded", source="in-cluster")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("k8s_config_loaded", source="kubeconfig")


def _extract_ref(item: Any, kind_hint: str) -> K8sResourceRef | None:
    """Convert a raw Kubernetes API object into a :class:`K8sResourceRef`.

    Returns ``None`` if the resource does not have the opt-in annotation.
    """
    metadata = item.metadata
    if metadata is None:
        return None

    annotations: dict[str, str] = metadata.annotations or {}
    enabled_key = f"{ANNOTATION_PREFIX}/enabled"
    if annotations.get(enabled_key, "").lower() != "true":
        return None

    labels: dict[str, str] = metadata.labels or {}

    # Derive kind from the object if available
    kind = getattr(item, "kind", None) or kind_hint

    ref = K8sResourceRef(
        api_version=getattr(item, "api_version", "") or "",
        kind=kind,
        namespace=metadata.namespace or "",
        name=metadata.name or "",
        uid=metadata.uid or "",
        annotations=annotations,
        labels=labels,
    )

    # Populate Ingress-specific fields
    if kind.lower() == "ingress" and hasattr(item, "spec") and item.spec:
        rules = item.spec.rules or []
        ref.ingress_hosts = [r.host for r in rules if r.host]

        # Extract the backend service name and port from the first rule's first path
        for rule in rules:
            if rule.http and rule.http.paths:
                for path in rule.http.paths:
                    backend = getattr(path, "backend", None)
                    if backend and backend.service:
                        ref.ingress_backend_service_name = backend.service.name
                        if backend.service.port:
                            port_obj = backend.service.port
                            ref.ingress_backend_service_port = getattr(port_obj, "number", None)
                        break
                if ref.ingress_backend_service_name:
                    break

    # Populate Service-specific fields
    if kind.lower() == "service" and hasattr(item, "spec") and item.spec:
        ref.service_cluster_ip = item.spec.cluster_ip or None
        if item.spec.ports:
            ref.service_ports = [p.port for p in item.spec.ports if p.port]

    return ref


class K8sWatcher:
    """Watches Kubernetes resources for Organizr annotations.

    Parameters
    ----------
    namespaces:
        Namespaces to watch. Empty list means watch all namespaces.
    resource_types:
        Resource types to watch (e.g. ``["ingresses", "services"]``).
    on_change:
        Callback invoked with the full list of :class:`K8sResourceRef` whenever
        a change is detected.
    """

    def __init__(
        self,
        namespaces: list[str],
        resource_types: list[str],
        on_change: Callable[[list[K8sResourceRef]], None],
    ) -> None:
        self._namespaces = namespaces
        self._resource_types = resource_types
        self._on_change = on_change
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        # Keyed by (resource_type, namespace, name) -> K8sResourceRef
        self._state: dict[str, K8sResourceRef] = {}

    def start(self) -> None:
        """Start watch threads for each resource type."""
        for rt in self._resource_types:
            if rt not in _RESOURCE_TYPE_MAP:
                logger.warning("unknown_resource_type", resource_type=rt)
                continue
            t = threading.Thread(target=self._watch_loop, args=(rt,), daemon=True, name=f"watch-{rt}")
            self._threads.append(t)
            t.start()
            logger.info("watcher_started", resource_type=rt, namespaces=self._namespaces or ["all"])

    def stop(self) -> None:
        """Signal all watch threads to stop."""
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=5)

    def list_current(self) -> list[K8sResourceRef]:
        """Return the current snapshot of all annotated resources."""
        with self._lock:
            return list(self._state.values())

    def do_full_list(self) -> list[K8sResourceRef]:
        """Perform a one-shot full list of all watched resources (no watch stream).

        This is used for the initial sync and periodic full reconciliation.
        """
        refs: list[K8sResourceRef] = []
        for rt in self._resource_types:
            if rt not in _RESOURCE_TYPE_MAP:
                continue
            refs.extend(self._list_resources(rt))
        with self._lock:
            self._state = {ref.tracking_key: ref for ref in refs}
        return refs

    def _list_resources(self, resource_type: str) -> list[K8sResourceRef]:
        """List all resources of a given type, filtered to annotated ones."""
        refs: list[K8sResourceRef] = []
        kind_hint = _kind_hint(resource_type)

        if self._namespaces:
            api_class_name, method_name = _RESOURCE_TYPE_NS_MAP[resource_type]
            api_instance = _get_api_instance(api_class_name)
            for ns in self._namespaces:
                try:
                    result = getattr(api_instance, method_name)(namespace=ns)
                    for item in result.items:
                        ref = _extract_ref(item, kind_hint)
                        if ref:
                            refs.append(ref)
                except Exception:
                    logger.exception("list_error", resource_type=resource_type, namespace=ns)
        else:
            api_class_name, method_name = _RESOURCE_TYPE_MAP[resource_type]
            api_instance = _get_api_instance(api_class_name)
            try:
                result = getattr(api_instance, method_name)()
                for item in result.items:
                    ref = _extract_ref(item, kind_hint)
                    if ref:
                        refs.append(ref)
            except Exception:
                logger.exception("list_error", resource_type=resource_type)

        return refs

    def _watch_loop(self, resource_type: str) -> None:
        """Run a Kubernetes watch stream for a single resource type.

        Automatically reconnects on stream timeout / errors.
        """
        kind_hint = _kind_hint(resource_type)
        w = watch.Watch()

        while not self._stop_event.is_set():
            try:
                api_class_name, method_name = (
                    _RESOURCE_TYPE_MAP[resource_type]
                    if not self._namespaces
                    else _RESOURCE_TYPE_NS_MAP[resource_type]
                )
                api_instance = _get_api_instance(api_class_name)

                stream_args: dict[str, Any] = {"timeout_seconds": 300}

                if self._namespaces:
                    # Watch each namespace sequentially in this thread
                    for ns in self._namespaces:
                        if self._stop_event.is_set():
                            break
                        for event in w.stream(
                            getattr(api_instance, method_name),
                            namespace=ns,
                            **stream_args,
                        ):
                            if self._stop_event.is_set():
                                break
                            self._handle_event(event, kind_hint)
                else:
                    for event in w.stream(
                        getattr(api_instance, method_name),
                        **stream_args,
                    ):
                        if self._stop_event.is_set():
                            break
                        self._handle_event(event, kind_hint)

            except Exception:
                if not self._stop_event.is_set():
                    logger.exception("watch_error", resource_type=resource_type)
                    # Brief backoff before reconnecting
                    self._stop_event.wait(5)

    def _handle_event(self, event: dict[str, Any], kind_hint: str) -> None:
        """Process a single watch event and notify on_change if state changed."""
        event_type = event.get("type", "")
        obj = event.get("object")
        if obj is None:
            return

        ref = _extract_ref(obj, kind_hint)

        changed = False
        with self._lock:
            if event_type in ("ADDED", "MODIFIED"):
                if ref:
                    key = ref.tracking_key
                    if key not in self._state or self._state[key] != ref:
                        self._state[key] = ref
                        changed = True
                else:
                    # Annotation might have been removed — treat as deletion
                    metadata = getattr(obj, "metadata", None)
                    if metadata:
                        temp_key = f"{metadata.namespace}/{kind_hint.lower()}/{metadata.name}"
                        if temp_key in self._state:
                            del self._state[temp_key]
                            changed = True
            elif event_type == "DELETED":
                metadata = getattr(obj, "metadata", None)
                if metadata:
                    key = f"{metadata.namespace}/{kind_hint.lower()}/{metadata.name}"
                    if key in self._state:
                        del self._state[key]
                        changed = True

        if changed:
            with self._lock:
                current = list(self._state.values())
            try:
                self._on_change(current)
            except Exception:
                logger.exception("on_change_error")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api_instance(api_class_name: str) -> Any:
    """Instantiate a Kubernetes API class by name."""
    cls = getattr(client, api_class_name)
    return cls()


def _kind_hint(resource_type: str) -> str:
    """Derive a Kind string from a resource type name."""
    mapping = {
        "ingresses": "Ingress",
        "services": "Service",
        "deployments": "Deployment",
        "statefulsets": "StatefulSet",
        "daemonsets": "DaemonSet",
    }
    return mapping.get(resource_type, resource_type.rstrip("s").title())
