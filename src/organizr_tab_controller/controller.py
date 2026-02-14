"""Main controller loop — ties the K8s watcher, Organizr client, and
reconciler together.
"""

from __future__ import annotations

import threading
import time

import structlog

from organizr_tab_controller.config import ControllerSettings
from organizr_tab_controller.k8s_watcher import K8sWatcher, load_k8s_config
from organizr_tab_controller.models import K8sResourceRef
from organizr_tab_controller.organizr_client import OrganizrClient, OrganizrAPIError
from organizr_tab_controller.tab_reconciler import ReconcileActions, reconcile

logger = structlog.get_logger(__name__)


class TabController:
    """Top-level orchestrator.

    1. Loads K8s config and connects to the Organizr API.
    2. Starts K8s resource watches.
    3. Runs a periodic full-reconciliation loop.
    4. Reacts to watch events for immediate reconciliation.

    Parameters
    ----------
    settings:
        Fully-resolved controller configuration.
    """

    def __init__(self, settings: ControllerSettings) -> None:
        self._settings = settings
        self._stop_event = threading.Event()

        self._organizr = OrganizrClient(
            base_url=settings.api_url,
            api_key=settings.api_key,
            api_version=settings.api_version,
            timeout=settings.api_timeout,
        )
        self._watcher: K8sWatcher | None = None
        self._reconcile_lock = threading.Lock()
        self._event_reconcile_requested = threading.Event()

    # -- lifecycle --------------------------------------------------------------

    def start(self) -> None:
        """Initialise components and begin the control loop."""
        logger.info(
            "controller_starting",
            api_url=self._settings.api_url,
            sync_policy=self._settings.sync_policy.value,
            namespaces=self._settings.watch_namespaces or ["all"],
            resource_types=self._settings.watch_resource_types,
            reconcile_interval=self._settings.reconcile_interval,
        )

        # 1. Kubernetes config
        load_k8s_config()

        # 2. Health-check the Organizr API
        if not self._organizr.health_check():
            logger.warning("organizr_unreachable", url=self._settings.api_url)

        # 3. Start watchers
        self._watcher = K8sWatcher(
            namespaces=self._settings.watch_namespaces,
            resource_types=self._settings.watch_resource_types,
            on_change=self._on_k8s_change,
        )

        # 4. Initial full list + reconcile
        logger.info("initial_full_reconcile")
        refs = self._watcher.do_full_list()
        self._do_reconcile(refs)

        # 5. Start watch streams (background threads)
        self._watcher.start()

        # 6. Run periodic reconciliation in the main thread
        self._periodic_loop()

    def stop(self) -> None:
        """Gracefully shut down the controller."""
        logger.info("controller_stopping")
        self._stop_event.set()
        self._event_reconcile_requested.set()  # unblock wait
        if self._watcher:
            self._watcher.stop()
        self._organizr.close()
        logger.info("controller_stopped")

    # -- reconciliation ---------------------------------------------------------

    def _on_k8s_change(self, refs: list[K8sResourceRef]) -> None:
        """Callback from the K8s watcher when annotated resources change."""
        logger.debug("k8s_change_detected", resource_count=len(refs))
        # Signal the periodic loop to do an immediate reconcile
        self._event_reconcile_requested.set()

    def _periodic_loop(self) -> None:
        """Run full reconciliation at a fixed interval, or sooner on watch events."""
        while not self._stop_event.is_set():
            # Wait for either a change event or the timer to fire
            triggered = self._event_reconcile_requested.wait(timeout=self._settings.reconcile_interval)
            if self._stop_event.is_set():
                break
            self._event_reconcile_requested.clear()

            if triggered:
                logger.debug("reconcile_triggered_by_event")
            else:
                logger.debug("reconcile_triggered_by_timer")

            try:
                if self._watcher:
                    # Re-list for a consistent view
                    refs = self._watcher.do_full_list()
                    self._do_reconcile(refs)
            except Exception:
                logger.exception("reconcile_loop_error")

    def _do_reconcile(self, refs: list[K8sResourceRef]) -> None:
        """Execute a single reconciliation cycle."""
        with self._reconcile_lock:
            try:
                actual_tabs = self._organizr.list_tabs()
            except OrganizrAPIError:
                logger.exception("failed_to_list_tabs")
                return

            actions = reconcile(
                desired_refs=refs,
                actual_tabs=actual_tabs,
                sync_policy=self._settings.sync_policy,
            )

            if actions.is_empty:
                logger.debug("no_changes_needed")
                return

            self._apply_actions(actions)

    def _apply_actions(self, actions: ReconcileActions) -> None:
        """Execute create / update / delete actions against the Organizr API."""
        for tab in actions.to_create:
            try:
                created = self._organizr.create_tab(tab)
                logger.info("tab_created", name=created.name, id=created.id)
            except OrganizrAPIError:
                logger.exception("tab_create_failed", name=tab.name)

        for tab in actions.to_update:
            try:
                self._organizr.update_tab(tab)
                logger.info("tab_updated", name=tab.name, id=tab.id)
            except OrganizrAPIError:
                logger.exception("tab_update_failed", name=tab.name, id=tab.id)

        for tab in actions.to_delete:
            if tab.id is None:
                continue
            try:
                self._organizr.delete_tab(tab.id)
                logger.info("tab_deleted", name=tab.name, id=tab.id)
            except OrganizrAPIError:
                logger.exception("tab_delete_failed", name=tab.name, id=tab.id)
