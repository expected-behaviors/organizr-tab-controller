"""HTTP client for the Organizr API (v2, with v1 fallback)."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from organizr_tab_controller.models import Tab, TabType

logger = structlog.get_logger(__name__)


class OrganizrAPIError(Exception):
    """Raised when the Organizr API returns an unexpected response."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class OrganizrClient:
    """Manages communication with the Organizr REST API.

    Parameters
    ----------
    base_url:
        Root URL of the Organizr instance (e.g. ``https://organizr.example.com``).
    api_key:
        Organizr API key used for authentication.
    api_version:
        ``"v2"`` (preferred) or ``"v1"`` (legacy ``data[]`` format).
    timeout:
        HTTP timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_version: str = "v2",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_version = api_version
        self._timeout = timeout
        self._client: httpx.Client | None = None

    # -- lifecycle --------------------------------------------------------------

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=self._base_url,
                headers={"Token": self._api_key},
                timeout=self._timeout,
            )
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    # -- v2 API helpers ---------------------------------------------------------

    def _v2_url(self, path: str = "") -> str:
        return f"/api/v2/tabs{path}"

    def _v1_url(self) -> str:
        return "/api/?v1/settings/tab/editor/tabs"

    def _v1_tab_list_url(self) -> str:
        return "/api/?v1/tab/list"

    # -- public interface -------------------------------------------------------

    def health_check(self) -> bool:
        """Return ``True`` if the Organizr instance responds to a ping."""
        try:
            resp = self.client.get("/api/v2/ping")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    # -- list -------------------------------------------------------------------

    def list_tabs(self) -> list[Tab]:
        """Fetch all tabs from Organizr."""
        if self._api_version == "v2":
            return self._list_tabs_v2()
        return self._list_tabs_v1()

    def _list_tabs_v2(self) -> list[Tab]:
        resp = self.client.get(self._v2_url())
        self._check_response(resp, "list tabs (v2)")
        data = resp.json()
        tabs_raw = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(tabs_raw, dict):
            # Some Organizr versions nest under response -> data -> tabs
            tabs_raw = tabs_raw.get("tabs", tabs_raw)
        if not isinstance(tabs_raw, list):
            logger.warning("unexpected_tabs_response", body=data)
            return []
        return [self._parse_tab(t) for t in tabs_raw]

    def _list_tabs_v1(self) -> list[Tab]:
        resp = self.client.get(self._v1_tab_list_url())
        self._check_response(resp, "list tabs (v1)")
        data = resp.json()
        tabs_raw = data.get("data", {}).get("tabs", [])
        return [self._parse_tab(t) for t in tabs_raw]

    # -- create -----------------------------------------------------------------

    def create_tab(self, tab: Tab) -> Tab:
        """Create a new tab in Organizr. Returns the created tab (with ID)."""
        logger.info("creating_tab", name=tab.name, url=tab.url)
        if self._api_version == "v2":
            return self._create_tab_v2(tab)
        return self._create_tab_v1(tab)

    def _create_tab_v2(self, tab: Tab) -> Tab:
        payload = tab.to_api_payload()
        payload.pop("id", None)
        resp = self.client.post(self._v2_url(), json=payload)
        self._check_response(resp, "create tab (v2)")
        body = resp.json()
        created = body.get("data", body)
        if isinstance(created, dict) and "id" in created:
            tab = tab.model_copy(update={"id": created["id"]})
        return tab

    def _create_tab_v1(self, tab: Tab) -> Tab:
        payload = tab.to_v1_payload(action="addNewTab")
        resp = self.client.post(self._v1_url(), data=payload)
        self._check_response(resp, "create tab (v1)")
        # v1 does not always return the new ID; re-fetch to find it
        all_tabs = self._list_tabs_v1()
        for t in all_tabs:
            if t.name == tab.name and t.url == tab.url:
                return t
        return tab

    # -- update -----------------------------------------------------------------

    def update_tab(self, tab: Tab) -> Tab:
        """Update an existing tab. ``tab.id`` must be set."""
        if tab.id is None:
            raise OrganizrAPIError("Cannot update tab without an ID")
        logger.info("updating_tab", id=tab.id, name=tab.name)
        if self._api_version == "v2":
            return self._update_tab_v2(tab)
        return self._update_tab_v1(tab)

    def _update_tab_v2(self, tab: Tab) -> Tab:
        payload = tab.to_api_payload()
        resp = self.client.put(self._v2_url(f"/{tab.id}"), json=payload)
        self._check_response(resp, f"update tab {tab.id} (v2)")
        return tab

    def _update_tab_v1(self, tab: Tab) -> Tab:
        payload = tab.to_v1_payload(action="editTab")
        resp = self.client.post(self._v1_url(), data=payload)
        self._check_response(resp, f"update tab {tab.id} (v1)")
        # If tab type changed, send a separate changeType call
        # (v1 quirk: editTab ignores type changes)
        change_type_payload = {
            "data[action]": "changeType",
            "data[id]": str(tab.id),
            "data[tabType]": str(tab.tab_type.value),
        }
        resp = self.client.post(self._v1_url(), data=change_type_payload)
        self._check_response(resp, f"change tab type {tab.id} (v1)")
        return tab

    # -- delete -----------------------------------------------------------------

    def delete_tab(self, tab_id: int) -> None:
        """Delete a tab by ID."""
        logger.info("deleting_tab", id=tab_id)
        if self._api_version == "v2":
            self._delete_tab_v2(tab_id)
        else:
            self._delete_tab_v1(tab_id)

    def _delete_tab_v2(self, tab_id: int) -> None:
        resp = self.client.delete(self._v2_url(f"/{tab_id}"))
        self._check_response(resp, f"delete tab {tab_id} (v2)")

    def _delete_tab_v1(self, tab_id: int) -> None:
        payload = {
            "data[action]": "deleteTab",
            "data[id]": str(tab_id),
        }
        resp = self.client.post(self._v1_url(), data=payload)
        self._check_response(resp, f"delete tab {tab_id} (v1)")

    # -- parsing helpers --------------------------------------------------------

    @staticmethod
    def _parse_tab(raw: dict[str, Any]) -> Tab:
        """Parse a raw API response dict into a Tab model."""

        def _int(val: Any, default: int = 0) -> int:
            try:
                return int(val)
            except (TypeError, ValueError):
                return default

        def _bool(val: Any) -> bool:
            return _int(val) == 1

        tab_type_val = _int(raw.get("type", raw.get("tab_type", raw.get("tabType", 1))))
        try:
            tab_type = TabType(tab_type_val)
        except ValueError:
            tab_type = TabType.IFRAME

        return Tab(
            id=_int(raw.get("id")) or None,
            name=raw.get("name", raw.get("tab_name", raw.get("tabName", ""))),
            url=raw.get("url", raw.get("tab_url", raw.get("tabURL", ""))),
            url_local=raw.get("url_local", raw.get("tabLocalURL")) or None,
            ping_url=raw.get("ping_url", raw.get("pingURL")) or None,
            image=raw.get("image", raw.get("tab_image", raw.get("tabImage"))) or None,
            tab_type=tab_type,
            group_id=_int(raw.get("group_id", raw.get("tabGroupID", 1)), 1),
            category_id=_int(raw.get("category_id", raw.get("tabCategoryID", 0))) or None,
            order=_int(raw.get("order", raw.get("tab_order", raw.get("tabOrder")))) or None,
            default=_bool(raw.get("default", 0)),
            active=_bool(raw.get("enabled", raw.get("active", 1))),
            splash=_bool(raw.get("splash", 0)),
            ping=_bool(raw.get("ping", 1)),
            preload=_bool(raw.get("preload", 0)),
        )

    @staticmethod
    def _check_response(resp: httpx.Response, context: str) -> None:
        """Raise on non-2xx responses."""
        if resp.status_code >= 400:
            body: Any = None
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise OrganizrAPIError(
                f"Organizr API error during {context}: HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=body,
            )
