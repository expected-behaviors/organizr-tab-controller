"""HTTP client for the Organizr API (v2, with v1 fallback)."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from organizr_tab_controller.icon_matcher import (
    DEFAULT_CATEGORY_ICON_PATH_PREFIX,
    DEFAULT_GROUP_ICON_PATH_PREFIX,
    normalize_icon_spec,
)
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

    # -- categories (v2; optional endpoints - may not exist on all Organizr versions)
    def _v2_categories_url(self, path: str = "") -> str:
        return f"/api/v2/categories{path}"

    def _v2_groups_url(self) -> str:
        return "/api/v2/groups"

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

    # -- groups and categories (name resolution, ensure-before-tab) ------------

    def list_categories(self) -> list[dict[str, Any]]:
        """List tab categories. Returns empty list if endpoint is not available."""
        if self._api_version != "v2":
            return []
        try:
            resp = self.client.get(self._v2_categories_url())
            self._check_response(resp, "list categories")
            data = resp.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, list):
                return items
            if isinstance(items, dict) and "categories" in items:
                return items["categories"]
            return []
        except OrganizrAPIError:
            raise
        except Exception as e:
            logger.warning("list_categories_failed", error=str(e))
            return []

    def list_groups(self) -> list[dict[str, Any]]:
        """List user groups (for tab access). Returns empty list if endpoint not available."""
        if self._api_version != "v2":
            return []
        try:
            resp = self.client.get(self._v2_groups_url())
            self._check_response(resp, "list groups")
            data = resp.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(items, list):
                return items
            if isinstance(items, dict) and "groups" in items:
                return items["groups"]
            return []
        except OrganizrAPIError:
            raise
        except Exception as e:
            logger.warning("list_groups_failed", error=str(e))
            return []

    def resolve_group_id_by_name(self, name: str) -> int:
        """Resolve a group name to an API group ID. Returns 1 (default) if not found."""
        if not name or not name.strip():
            return 1
        name_clean = name.strip()
        for g in self.list_groups():
            gname = g.get("name", g.get("group_name", ""))
            if str(gname).strip().lower() == name_clean.lower():
                gid = g.get("id", g.get("group_id"))
                if gid is not None:
                    return int(gid)
        logger.debug("group_name_not_found_using_default", name=name_clean)
        return 1

    def ensure_category_by_name(self, name: str, icon: str | None = None) -> int | None:
        """Get or create a category by name; set icon if provided. Returns category ID or None."""
        if not name or not name.strip():
            return None
        name_clean = name.strip()
        icon_normalized = (
            normalize_icon_spec(icon, DEFAULT_CATEGORY_ICON_PATH_PREFIX) if icon else None
        )
        categories = self.list_categories()
        for c in categories:
            cname = c.get("name", c.get("category_name", ""))
            if str(cname).strip().lower() == name_clean.lower():
                cid = c.get("id", c.get("category_id"))
                if cid is not None:
                    cat_id = int(cid)
                    if icon_normalized and c.get("image", c.get("icon", "")) != icon_normalized:
                        self._update_category_icon(cat_id, icon_normalized)
                    return cat_id
        # Create new category
        try:
            new_id = self._create_category(name_clean, icon_normalized)
            if new_id is not None:
                logger.info("category_created", name=name_clean, id=new_id)
            return new_id
        except Exception as e:
            logger.warning("create_category_failed", name=name_clean, error=str(e))
            return None

    def ensure_group_icon_by_name(self, name: str, icon: str | None = None) -> None:
        """If a group exists with this name, update its icon. Does not create groups."""
        if not name or not icon:
            return
        name_clean = name.strip()
        icon_normalized = normalize_icon_spec(icon, DEFAULT_GROUP_ICON_PATH_PREFIX)
        for g in self.list_groups():
            gname = g.get("name", g.get("group_name", ""))
            if str(gname).strip().lower() == name_clean.lower():
                gid = g.get("id", g.get("group_id"))
                if gid is not None and g.get("image", g.get("icon", "")) != icon_normalized:
                    self._update_group_icon(int(gid), icon_normalized)
                return

    def _create_category(self, name: str, icon: str | None) -> int | None:
        try:
            payload: dict[str, Any] = {"name": name}
            if icon:
                payload["image"] = icon
            resp = self.client.post(self._v2_categories_url(), json=payload)
            self._check_response(resp, "create category")
            data = resp.json()
            created = data.get("data", data)
            if isinstance(created, dict) and "id" in created:
                return int(created["id"])
            return None
        except Exception:
            return None

    def _update_category_icon(self, category_id: int, icon: str) -> None:
        try:
            resp = self.client.put(
                self._v2_categories_url(f"/{category_id}"),
                json={"image": icon},
            )
            self._check_response(resp, f"update category {category_id} icon")
        except Exception as e:
            logger.warning("update_category_icon_failed", category_id=category_id, error=str(e))

    def _update_group_icon(self, group_id: int, icon: str) -> None:
        try:
            resp = self.client.put(
                self._v2_groups_url() + f"/{group_id}",
                json={"image": icon},
            )
            self._check_response(resp, f"update group {group_id} icon")
        except Exception as e:
            logger.warning("update_group_icon_failed", group_id=group_id, error=str(e))

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
