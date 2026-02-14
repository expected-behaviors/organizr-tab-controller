"""Tests for the tab reconciler."""

import pytest

from organizr_tab_controller.models import (
    ANNOTATION_PREFIX,
    K8sResourceRef,
    SyncPolicy,
    Tab,
    TabType,
)
from organizr_tab_controller.tab_reconciler import build_desired_tab, reconcile


def _make_ref(
    name: str = "radarr",
    namespace: str = "media",
    kind: str = "Ingress",
    annotations: dict[str, str] | None = None,
    labels: dict[str, str] | None = None,
    ingress_hosts: list[str] | None = None,
    ingress_backend_service_name: str | None = None,
    ingress_backend_service_port: int | None = None,
    service_cluster_ip: str | None = None,
    service_ports: list[int] | None = None,
) -> K8sResourceRef:
    base_annotations = {f"{ANNOTATION_PREFIX}/enabled": "true"}
    if annotations:
        base_annotations.update(annotations)
    return K8sResourceRef(
        api_version="networking.k8s.io/v1" if kind == "Ingress" else "v1",
        kind=kind,
        namespace=namespace,
        name=name,
        uid=f"uid-{name}",
        annotations=base_annotations,
        labels=labels or {},
        ingress_hosts=ingress_hosts or [],
        ingress_backend_service_name=ingress_backend_service_name,
        ingress_backend_service_port=ingress_backend_service_port,
        service_cluster_ip=service_cluster_ip,
        service_ports=service_ports or [],
    )


class TestBuildDesiredTab:
    def test_minimal_ingress(self) -> None:
        """Ingress with host -> external URL is https, local URL from backend service."""
        ref = _make_ref(
            name="radarr",
            ingress_hosts=["radarr.expectedbehaviors.com"],
            ingress_backend_service_name="radarr",
            ingress_backend_service_port=7878,
        )
        tab = build_desired_tab(ref)
        assert tab.name == "Radarr"
        assert tab.url == "https://radarr.expectedbehaviors.com"
        assert tab.url_local == "http://radarr.media.svc.cluster.local:7878"
        assert tab.ping_url == "radarr.media:7878"
        assert tab.image == "plugins/images/tabs/radarr.png"
        assert tab.tab_type == TabType.IFRAME
        assert tab.managed_by == "media/ingress/radarr"

    def test_ingress_without_backend_info(self) -> None:
        """Ingress with host but no backend service info -> no local URL, no ping."""
        ref = _make_ref(
            name="radarr",
            ingress_hosts=["radarr.expectedbehaviors.com"],
        )
        tab = build_desired_tab(ref)
        assert tab.url == "https://radarr.expectedbehaviors.com"
        assert tab.url_local is None
        assert tab.ping_url is None

    def test_ingress_backend_default_port(self) -> None:
        """Ingress backend with no port defaults to 80."""
        ref = _make_ref(
            name="myapp",
            ingress_hosts=["myapp.example.com"],
            ingress_backend_service_name="myapp-svc",
        )
        tab = build_desired_tab(ref)
        assert tab.url_local == "http://myapp-svc.media.svc.cluster.local:80"
        assert tab.ping_url == "myapp-svc.media:80"

    def test_explicit_name_annotation(self) -> None:
        ref = _make_ref(
            name="radarr",
            annotations={f"{ANNOTATION_PREFIX}/name": "Movie Manager"},
            ingress_hosts=["radarr.expectedbehaviors.com"],
        )
        tab = build_desired_tab(ref)
        assert tab.name == "Movie Manager"

    def test_explicit_url_annotation(self) -> None:
        ref = _make_ref(
            name="radarr",
            annotations={f"{ANNOTATION_PREFIX}/url": "https://custom.example.com/radarr"},
        )
        tab = build_desired_tab(ref)
        assert tab.url == "https://custom.example.com/radarr"

    def test_explicit_url_local_annotation(self) -> None:
        """Explicit url-local annotation takes priority over passive derivation."""
        ref = _make_ref(
            name="radarr",
            annotations={f"{ANNOTATION_PREFIX}/url-local": "http://custom-local:9999"},
            ingress_hosts=["radarr.example.com"],
            ingress_backend_service_name="radarr",
            ingress_backend_service_port=7878,
        )
        tab = build_desired_tab(ref)
        assert tab.url_local == "http://custom-local:9999"

    def test_explicit_image_url(self) -> None:
        ref = _make_ref(
            name="myapp",
            annotations={f"{ANNOTATION_PREFIX}/image": "https://cdn.example.com/myapp.png"},
            ingress_hosts=["myapp.example.com"],
        )
        tab = build_desired_tab(ref)
        assert tab.image == "https://cdn.example.com/myapp.png"

    def test_explicit_image_known_name(self) -> None:
        ref = _make_ref(
            name="myapp",
            annotations={f"{ANNOTATION_PREFIX}/image": "plex"},
            ingress_hosts=["myapp.example.com"],
        )
        tab = build_desired_tab(ref)
        assert tab.image == "plugins/images/tabs/plex.png"

    def test_type_new_window(self) -> None:
        ref = _make_ref(
            name="external",
            annotations={f"{ANNOTATION_PREFIX}/type": "new-window"},
            ingress_hosts=["external.example.com"],
        )
        tab = build_desired_tab(ref)
        assert tab.tab_type == TabType.NEW_WINDOW

    def test_service_derives_local_url_and_ping(self) -> None:
        """Service -> local URL is http internal DNS, ping is service:port."""
        ref = _make_ref(
            name="sonarr",
            kind="Service",
            service_cluster_ip="10.96.0.42",
            service_ports=[8989],
        )
        tab = build_desired_tab(ref)
        assert tab.url_local == "http://sonarr.media.svc.cluster.local:8989"
        assert tab.ping_url == "sonarr.media:8989"

    def test_service_external_url_from_external_dns(self) -> None:
        """Service with external-dns annotation -> external URL is https."""
        ref = _make_ref(
            name="myapp",
            kind="Service",
            annotations={"external-dns.alpha.kubernetes.io/hostname": "myapp.expectedbehaviors.com"},
            service_cluster_ip="10.96.0.50",
            service_ports=[80],
        )
        tab = build_desired_tab(ref)
        assert tab.url == "https://myapp.expectedbehaviors.com"
        assert tab.url_local == "http://myapp.media.svc.cluster.local:80"

    def test_service_default_port(self) -> None:
        """Service with no ports defaults to port 80 for local URL."""
        ref = _make_ref(
            name="simple",
            kind="Service",
            service_cluster_ip="10.96.0.99",
        )
        tab = build_desired_tab(ref)
        assert tab.url_local == "http://simple.media.svc.cluster.local:80"
        # No ports -> no ping_url
        assert tab.ping_url is None

    def test_service_no_cluster_ip_no_local(self) -> None:
        """Service without ClusterIP (headless) still gets local URL from name."""
        ref = _make_ref(
            name="headless",
            kind="Service",
            service_ports=[8080],
        )
        tab = build_desired_tab(ref)
        assert tab.url_local == "http://headless.media.svc.cluster.local:8080"
        assert tab.ping_url == "headless.media:8080"

    def test_external_dns_hostname_fallback_no_service(self) -> None:
        """Non-Ingress resource with external-dns hostname but no service info."""
        ref = _make_ref(
            name="myapp",
            kind="Deployment",
            annotations={"external-dns.alpha.kubernetes.io/hostname": "myapp.expectedbehaviors.com"},
        )
        tab = build_desired_tab(ref)
        assert tab.url == "https://myapp.expectedbehaviors.com"
        assert tab.url_local is None  # Deployment has no service info

    def test_app_label_for_name(self) -> None:
        ref = _make_ref(
            name="some-deployment-abc123",
            labels={"app.kubernetes.io/name": "plex"},
            ingress_hosts=["plex.example.com"],
        )
        tab = build_desired_tab(ref)
        assert tab.name == "Plex"
        assert tab.image == "plugins/images/tabs/plex.png"

    def test_boolean_annotations(self) -> None:
        ref = _make_ref(
            name="radarr",
            annotations={
                f"{ANNOTATION_PREFIX}/default": "true",
                f"{ANNOTATION_PREFIX}/splash": "true",
                f"{ANNOTATION_PREFIX}/preload": "true",
                f"{ANNOTATION_PREFIX}/active": "false",
            },
            ingress_hosts=["radarr.example.com"],
        )
        tab = build_desired_tab(ref)
        assert tab.default is True
        assert tab.splash is True
        assert tab.preload is True
        assert tab.active is False

    def test_group_and_category(self) -> None:
        ref = _make_ref(
            name="radarr",
            annotations={
                f"{ANNOTATION_PREFIX}/group-id": "2",
                f"{ANNOTATION_PREFIX}/category-id": "5",
            },
            ingress_hosts=["radarr.example.com"],
        )
        tab = build_desired_tab(ref)
        assert tab.group_id == 2
        assert tab.category_id == 5

    def test_fallback_url_from_name_namespace(self) -> None:
        """When no host/hostname info is available, URL falls back to name.namespace."""
        ref = _make_ref(
            name="obscure",
            kind="Deployment",
        )
        tab = build_desired_tab(ref)
        assert tab.url == "https://obscure.media"


class TestReconcile:
    def _make_existing_tab(self, tab_id: int, name: str, url: str, **kwargs) -> Tab:
        return Tab(id=tab_id, name=name, url=url, **kwargs)

    def test_create_new_tab(self) -> None:
        refs = [_make_ref(name="radarr", ingress_hosts=["radarr.example.com"])]
        actual: list[Tab] = []
        actions = reconcile(refs, actual, SyncPolicy.UPSERT)
        assert len(actions.to_create) == 1
        assert actions.to_create[0].name == "Radarr"
        assert len(actions.to_update) == 0
        assert len(actions.to_delete) == 0

    def test_no_changes_needed(self) -> None:
        refs = [
            _make_ref(
                name="radarr",
                ingress_hosts=["radarr.example.com"],
                ingress_backend_service_name="radarr",
                ingress_backend_service_port=7878,
            )
        ]
        existing = self._make_existing_tab(
            1,
            "Radarr",
            "https://radarr.example.com",
            url_local="http://radarr.media.svc.cluster.local:7878",
            image="plugins/images/tabs/radarr.png",
            tab_type=TabType.IFRAME,
            ping_url="radarr.media:7878",
        )
        actions = reconcile(refs, [existing], SyncPolicy.UPSERT)
        assert actions.is_empty

    def test_update_existing_tab(self) -> None:
        refs = [
            _make_ref(
                name="radarr",
                annotations={f"{ANNOTATION_PREFIX}/type": "new-window"},
                ingress_hosts=["radarr.example.com"],
                ingress_backend_service_name="radarr",
                ingress_backend_service_port=7878,
            )
        ]
        existing = self._make_existing_tab(
            1,
            "Radarr",
            "https://radarr.example.com",
            tab_type=TabType.IFRAME,
            image="plugins/images/tabs/radarr.png",
            ping_url="radarr.media:7878",
        )
        actions = reconcile(refs, [existing], SyncPolicy.UPSERT)
        assert len(actions.to_update) == 1
        assert actions.to_update[0].id == 1
        assert actions.to_update[0].tab_type == TabType.NEW_WINDOW

    def test_delete_in_sync_mode(self) -> None:
        refs: list[K8sResourceRef] = []  # no desired tabs
        existing = self._make_existing_tab(
            1, "Orphan", "https://orphan.example.com", tab_type=TabType.IFRAME
        )
        actions = reconcile(refs, [existing], SyncPolicy.SYNC)
        assert len(actions.to_delete) == 1
        assert actions.to_delete[0].id == 1

    def test_no_delete_in_upsert_mode(self) -> None:
        refs: list[K8sResourceRef] = []
        existing = self._make_existing_tab(
            1, "Orphan", "https://orphan.example.com", tab_type=TabType.IFRAME
        )
        actions = reconcile(refs, [existing], SyncPolicy.UPSERT)
        assert len(actions.to_delete) == 0

    def test_skip_internal_tabs_on_delete(self) -> None:
        refs: list[K8sResourceRef] = []
        homepage = self._make_existing_tab(
            1, "Homepage", "api/v2/page/homepage", tab_type=TabType.INTERNAL
        )
        actions = reconcile(refs, [homepage], SyncPolicy.SYNC)
        assert len(actions.to_delete) == 0

    def test_multiple_resources(self) -> None:
        refs = [
            _make_ref(
                name="radarr",
                ingress_hosts=["radarr.example.com"],
                ingress_backend_service_name="radarr",
                ingress_backend_service_port=7878,
            ),
            _make_ref(name="sonarr", ingress_hosts=["sonarr.example.com"]),
        ]
        existing = self._make_existing_tab(
            1,
            "Radarr",
            "https://radarr.example.com",
            url_local="http://radarr.media.svc.cluster.local:7878",
            image="plugins/images/tabs/radarr.png",
            tab_type=TabType.IFRAME,
            ping_url="radarr.media:7878",
        )
        actions = reconcile(refs, [existing], SyncPolicy.UPSERT)
        assert len(actions.to_create) == 1
        assert actions.to_create[0].name == "Sonarr"
        assert len(actions.to_update) == 0

    def test_match_by_name_fallback(self) -> None:
        """If URL doesn't match but name does, treat as the same tab."""
        refs = [
            _make_ref(
                name="radarr",
                annotations={f"{ANNOTATION_PREFIX}/url": "https://new-radarr.example.com"},
                ingress_hosts=["new-radarr.example.com"],
            )
        ]
        existing = self._make_existing_tab(
            1, "Radarr", "https://old-radarr.example.com", tab_type=TabType.IFRAME
        )
        actions = reconcile(refs, [existing], SyncPolicy.UPSERT)
        assert len(actions.to_update) == 1
        assert actions.to_update[0].url == "https://new-radarr.example.com"
        assert actions.to_update[0].id == 1
