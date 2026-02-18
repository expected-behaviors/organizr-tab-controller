"""Tests for the controller module (unit-level, mocking external dependencies)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from organizr_tab_controller.config import ControllerSettings
from organizr_tab_controller.controller import TabController
from organizr_tab_controller.models import K8sResourceRef, SyncPolicy, Tab, TabType


def _make_settings(**overrides) -> ControllerSettings:
    defaults = {
        "api_url": "https://organizr.example.com",
        "api_key": "test-key",
        "sync_policy": SyncPolicy.UPSERT,
        "reconcile_interval": 60,
        "watch_namespaces": [],
        "watch_resource_types": ["ingresses"],
        "log_level": "WARNING",
        "log_format": "console",
    }
    defaults.update(overrides)
    return ControllerSettings(**defaults)


def _make_ref(name: str = "radarr", namespace: str = "media") -> K8sResourceRef:
    return K8sResourceRef(
        api_version="networking.k8s.io/v1",
        kind="Ingress",
        namespace=namespace,
        name=name,
        uid=f"uid-{name}",
        annotations={"organizr-tab-controller.io/enabled": "true"},
        labels={"app.kubernetes.io/name": name},
        ingress_hosts=[f"{name}.example.com"],
    )


class TestTabControllerInit:
    def test_creates_organizr_client(self) -> None:
        settings = _make_settings()
        controller = TabController(settings)
        assert controller._organizr is not None
        assert controller._organizr._base_url == "https://organizr.example.com"
        assert controller._organizr._api_key == "test-key"

    def test_stop_is_safe_when_not_started(self) -> None:
        settings = _make_settings()
        controller = TabController(settings)
        controller.stop()  # should not raise


class TestDoReconcile:
    @patch("organizr_tab_controller.controller.reconcile")
    def test_reconcile_calls_apply(self, mock_reconcile: MagicMock) -> None:
        settings = _make_settings()
        controller = TabController(settings)

        # Mock the organizr client
        controller._organizr = MagicMock()
        controller._organizr.list_tabs.return_value = []

        # Mock reconcile to return a create action
        from organizr_tab_controller.tab_reconciler import ReconcileActions

        tab = Tab(name="Radarr", url="https://radarr.example.com")
        mock_reconcile.return_value = ReconcileActions(to_create=[tab])
        controller._organizr.create_tab.return_value = tab.model_copy(update={"id": 1})

        refs = [_make_ref()]
        controller._do_reconcile(refs)

        controller._organizr.list_tabs.assert_called_once()
        mock_reconcile.assert_called_once()
        controller._organizr.create_tab.assert_called_once_with(tab)

    @patch("organizr_tab_controller.controller.reconcile")
    def test_reconcile_no_actions(self, mock_reconcile: MagicMock) -> None:
        settings = _make_settings()
        controller = TabController(settings)
        controller._organizr = MagicMock()
        controller._organizr.list_tabs.return_value = []

        from organizr_tab_controller.tab_reconciler import ReconcileActions

        mock_reconcile.return_value = ReconcileActions()

        controller._do_reconcile([])

        controller._organizr.create_tab.assert_not_called()
        controller._organizr.update_tab.assert_not_called()
        controller._organizr.delete_tab.assert_not_called()

    @patch("organizr_tab_controller.controller.reconcile")
    def test_reconcile_handles_api_error_on_list(self, mock_reconcile: MagicMock) -> None:
        from organizr_tab_controller.organizr_client import OrganizrAPIError

        settings = _make_settings()
        controller = TabController(settings)
        controller._organizr = MagicMock()
        controller._organizr.list_tabs.side_effect = OrganizrAPIError("connection failed")

        # Should not raise
        controller._do_reconcile([_make_ref()])
        mock_reconcile.assert_not_called()


class TestApplyActions:
    def test_apply_creates(self) -> None:
        settings = _make_settings()
        controller = TabController(settings)
        controller._organizr = MagicMock()

        tab = Tab(name="New", url="https://new.example.com")
        controller._organizr.create_tab.return_value = tab.model_copy(update={"id": 10})

        from organizr_tab_controller.tab_reconciler import ReconcileActions

        actions = ReconcileActions(to_create=[tab])
        controller._apply_actions(actions)
        controller._organizr.create_tab.assert_called_once_with(tab)

    def test_apply_updates(self) -> None:
        settings = _make_settings()
        controller = TabController(settings)
        controller._organizr = MagicMock()

        tab = Tab(id=5, name="Updated", url="https://updated.example.com")

        from organizr_tab_controller.tab_reconciler import ReconcileActions

        actions = ReconcileActions(to_update=[tab])
        controller._apply_actions(actions)
        controller._organizr.update_tab.assert_called_once_with(tab)

    def test_apply_deletes(self) -> None:
        settings = _make_settings()
        controller = TabController(settings)
        controller._organizr = MagicMock()

        tab = Tab(id=7, name="Old", url="https://old.example.com")

        from organizr_tab_controller.tab_reconciler import ReconcileActions

        actions = ReconcileActions(to_delete=[tab])
        controller._apply_actions(actions)
        controller._organizr.delete_tab.assert_called_once_with(7)
