"""Tests for the Organizr API client."""

import httpx
import pytest
import respx

from organizr_tab_controller.models import Tab, TabType
from organizr_tab_controller.organizr_client import OrganizrAPIError, OrganizrClient

BASE_URL = "https://organizr.example.com"


@pytest.fixture()
def api_client() -> OrganizrClient:
    return OrganizrClient(base_url=BASE_URL, api_key="test-key", api_version="v2")


@pytest.fixture()
def v1_client() -> OrganizrClient:
    return OrganizrClient(base_url=BASE_URL, api_key="test-key", api_version="v1")


def _sample_tab_json(tab_id: int = 1, name: str = "Radarr", url: str = "https://radarr.example.com") -> dict:
    return {
        "id": tab_id,
        "name": name,
        "url": url,
        "url_local": "",
        "ping_url": "",
        "image": "plugins/images/tabs/radarr.png",
        "type": 1,
        "group_id": 1,
        "category_id": 0,
        "order": 1,
        "default": 0,
        "enabled": 1,
        "splash": 0,
        "ping": 1,
        "preload": 0,
    }


class TestHealthCheck:
    @respx.mock
    def test_healthy(self, api_client: OrganizrClient) -> None:
        respx.get(f"{BASE_URL}/api/v2/ping").mock(return_value=httpx.Response(200, json={"data": "pong"}))
        assert api_client.health_check() is True

    @respx.mock
    def test_unreachable(self, api_client: OrganizrClient) -> None:
        respx.get(f"{BASE_URL}/api/v2/ping").mock(side_effect=httpx.ConnectError("refused"))
        assert api_client.health_check() is False


class TestListTabs:
    @respx.mock
    def test_list_v2(self, api_client: OrganizrClient) -> None:
        respx.get(f"{BASE_URL}/api/v2/tabs").mock(
            return_value=httpx.Response(200, json={"data": [_sample_tab_json()]})
        )
        tabs = api_client.list_tabs()
        assert len(tabs) == 1
        assert tabs[0].name == "Radarr"
        assert tabs[0].id == 1
        assert tabs[0].tab_type == TabType.IFRAME

    @respx.mock
    def test_list_v2_empty(self, api_client: OrganizrClient) -> None:
        respx.get(f"{BASE_URL}/api/v2/tabs").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        tabs = api_client.list_tabs()
        assert tabs == []

    @respx.mock
    def test_list_v1(self, v1_client: OrganizrClient) -> None:
        respx.get(f"{BASE_URL}/api/?v1/tab/list").mock(
            return_value=httpx.Response(200, json={"data": {"tabs": [_sample_tab_json()]}})
        )
        tabs = v1_client.list_tabs()
        assert len(tabs) == 1
        assert tabs[0].name == "Radarr"


class TestCreateTab:
    @respx.mock
    def test_create_v2(self, api_client: OrganizrClient) -> None:
        respx.post(f"{BASE_URL}/api/v2/tabs").mock(
            return_value=httpx.Response(200, json={"data": {"id": 5}})
        )
        tab = Tab(name="Sonarr", url="https://sonarr.example.com")
        created = api_client.create_tab(tab)
        assert created.id == 5
        assert created.name == "Sonarr"

    @respx.mock
    def test_create_v2_error(self, api_client: OrganizrClient) -> None:
        respx.post(f"{BASE_URL}/api/v2/tabs").mock(
            return_value=httpx.Response(500, json={"error": "internal"})
        )
        tab = Tab(name="Fail", url="https://fail.example.com")
        with pytest.raises(OrganizrAPIError):
            api_client.create_tab(tab)


class TestUpdateTab:
    @respx.mock
    def test_update_v2(self, api_client: OrganizrClient) -> None:
        respx.put(f"{BASE_URL}/api/v2/tabs/3").mock(
            return_value=httpx.Response(200, json={"data": {"id": 3}})
        )
        tab = Tab(id=3, name="Updated", url="https://updated.example.com")
        updated = api_client.update_tab(tab)
        assert updated.id == 3

    def test_update_without_id_raises(self, api_client: OrganizrClient) -> None:
        tab = Tab(name="NoID", url="https://noid.example.com")
        with pytest.raises(OrganizrAPIError, match="without an ID"):
            api_client.update_tab(tab)


class TestDeleteTab:
    @respx.mock
    def test_delete_v2(self, api_client: OrganizrClient) -> None:
        respx.delete(f"{BASE_URL}/api/v2/tabs/7").mock(
            return_value=httpx.Response(200, json={"data": "ok"})
        )
        api_client.delete_tab(7)  # should not raise

    @respx.mock
    def test_delete_v2_error(self, api_client: OrganizrClient) -> None:
        respx.delete(f"{BASE_URL}/api/v2/tabs/99").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        with pytest.raises(OrganizrAPIError):
            api_client.delete_tab(99)


class TestParseTab:
    def test_parse_standard_fields(self) -> None:
        raw = _sample_tab_json(tab_id=10, name="Plex", url="https://plex.example.com")
        raw["type"] = 2
        tab = OrganizrClient._parse_tab(raw)
        assert tab.id == 10
        assert tab.name == "Plex"
        assert tab.url == "https://plex.example.com"
        assert tab.tab_type == TabType.NEW_WINDOW

    def test_parse_v1_field_names(self) -> None:
        raw = {
            "id": 3,
            "tabName": "Sonarr",
            "tabURL": "https://sonarr.example.com",
            "tabLocalURL": "",
            "pingURL": "sonarr:8989",
            "tabImage": "plugins/images/tabs/sonarr.png",
            "tabType": "1",
            "tabGroupID": "1",
            "tabCategoryID": "0",
            "tabOrder": "2",
            "default": 0,
            "enabled": 1,
            "splash": 0,
            "ping": 1,
            "preload": 0,
        }
        tab = OrganizrClient._parse_tab(raw)
        assert tab.name == "Sonarr"
        assert tab.url == "https://sonarr.example.com"
        assert tab.ping_url == "sonarr:8989"
        assert tab.tab_type == TabType.IFRAME

    def test_parse_handles_missing_fields(self) -> None:
        raw = {"id": 1, "name": "Minimal", "url": "https://min.example.com"}
        tab = OrganizrClient._parse_tab(raw)
        assert tab.name == "Minimal"
        assert tab.tab_type == TabType.IFRAME  # default
