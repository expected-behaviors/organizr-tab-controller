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
        service_cluster_ip=service_cluster_ip,
        service_ports=service_ports or [],
    )


class TestBuildDesiredTab:
    def test_minimal_ingress(self) -> None:
        ref = _make_ref(
            name="radarr",
            ingress_hosts=["radarr.expectedbehaviors.com"],
        )
        tab = build_desired_tab(ref)
        assert tab.name == "Radarr"
        assert tab.url == "https://radarr.expectedbehaviors.com"
        assert tab.image == "plugins/images/tabs/radarr.png"
        assert tab.tab_type == TabType.IFRAME
        assert tab.managed_by == "media/ingress/radarr"

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

    def test_service_with_cluster_ip(self) -> None:
        ref = _make_ref(
            name="sonarr",
            kind="Service",
            service_cluster_ip="10.96.0.42",
            service_ports=[8989],
        )
        tab = build_desired_tab(ref)
        assert tab.url_local == "http://sonarr.media.svc.cluster.local:8989"
        assert tab.ping_url == "sonarr.media:8989"

    def test_external_dns_hostname_fallback(self) -> None:
        ref = _make_ref(
            name="myapp",
            kind="Service",
            annotations={"external-dns.alpha.kubernetes.io/hostname": "myapp.expectedbehaviors.com"},
        )
        tab = build_desired_tab(ref)
        assert tab.url == "https://myapp.expectedbehaviors.com"

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
        refs = [_make_ref(name="radarr", ingress_hosts=["radarr.example.com"])]
        existing = self._make_existing_tab(
            1,
            "Radarr",
            "https://radarr.example.com",
            image="plugins/images/tabs/radarr.png",
            tab_type=TabType.IFRAME,
            ping_url="radarr.example.com:443",
        )
        actions = reconcile(refs, [existing], SyncPolicy.UPSERT)
        assert actions.is_empty

    def test_update_existing_tab(self) -> None:
        refs = [
            _make_ref(
                name="radarr",
                annotations={f"{ANNOTATION_PREFIX}/type": "new-window"},
                ingress_hosts=["radarr.example.com"],
            )
        ]
        existing = self._make_existing_tab(
            1,
            "Radarr",
            "https://radarr.example.com",
            tab_type=TabType.IFRAME,
            image="plugins/images/tabs/radarr.png",
            ping_url="radarr.example.com:443",
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
            _make_ref(name="radarr", ingress_hosts=["radarr.example.com"]),
            _make_ref(name="sonarr", ingress_hosts=["sonarr.example.com"]),
        ]
        existing = self._make_existing_tab(
            1,
            "Radarr",
            "https://radarr.example.com",
            image="plugins/images/tabs/radarr.png",
            tab_type=TabType.IFRAME,
            ping_url="radarr.example.com:443",
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
