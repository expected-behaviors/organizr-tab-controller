"""Tests for the icon_matcher module."""

from organizr_tab_controller.icon_matcher import (
    DEFAULT_CATEGORY_ICON_PATH_PREFIX,
    DEFAULT_GROUP_ICON_PATH_PREFIX,
    match_icon,
    normalise_name,
    normalize_icon_spec,
)


class TestNormaliseName:
    def test_lowercase(self) -> None:
        assert normalise_name("Radarr") == "radarr"

    def test_strips_dashes(self) -> None:
        assert normalise_name("home-assistant") == "homeassistant"

    def test_strips_underscores(self) -> None:
        assert normalise_name("home_assistant") == "homeassistant"

    def test_strips_dots(self) -> None:
        assert normalise_name("node.red") == "nodered"

    def test_empty(self) -> None:
        assert normalise_name("") == ""


class TestMatchIcon:
    def test_known_app(self) -> None:
        result = match_icon("radarr")
        assert result == "plugins/images/tabs/radarr.png"

    def test_case_insensitive(self) -> None:
        result = match_icon("Radarr")
        assert result == "plugins/images/tabs/radarr.png"

    def test_dashes_ignored(self) -> None:
        result = match_icon("Home-Assistant")
        assert result == "plugins/images/tabs/homeassistant.png"

    def test_underscores_ignored(self) -> None:
        result = match_icon("home_assistant")
        assert result == "plugins/images/tabs/homeassistant.png"

    def test_uptime_kuma_variants(self) -> None:
        assert match_icon("uptime-kuma") == "plugins/images/tabs/uptimekuma.png"
        assert match_icon("uptimekuma") == "plugins/images/tabs/uptimekuma.png"

    def test_unknown_app(self) -> None:
        result = match_icon("totally-unknown-app-12345")
        assert result is None

    def test_empty_string(self) -> None:
        result = match_icon("")
        assert result is None

    def test_url_passthrough_https(self) -> None:
        url = "https://example.com/icon.png"
        assert match_icon(url) == url

    def test_url_passthrough_http(self) -> None:
        url = "http://example.com/icon.png"
        assert match_icon(url) == url

    def test_absolute_path_passthrough(self) -> None:
        path = "/custom/icons/myapp.svg"
        assert match_icon(path) == path

    def test_fontawesome_passthrough(self) -> None:
        fa = "fontawesome::home"
        assert match_icon(fa) == fa

    def test_arr_suite_coverage(self) -> None:
        for app in ["sonarr", "radarr", "lidarr", "readarr", "prowlarr", "bazarr"]:
            assert match_icon(app) is not None, f"Missing icon for {app}"

    def test_download_clients(self) -> None:
        for app in ["sabnzbd", "qbittorrent", "transmission", "deluge", "nzbget"]:
            assert match_icon(app) is not None, f"Missing icon for {app}"

    def test_media_servers(self) -> None:
        for app in ["plex", "jellyfin", "emby"]:
            assert match_icon(app) is not None, f"Missing icon for {app}"

    def test_homelab_common(self) -> None:
        for app in ["grafana", "portainer", "pihole", "organizr", "ombi", "tautulli"]:
            assert match_icon(app) is not None, f"Missing icon for {app}"


class TestNormalizeIconSpec:
    def test_filename_only_group(self) -> None:
        assert (
            normalize_icon_spec("media.png", DEFAULT_GROUP_ICON_PATH_PREFIX)
            == "plugins/images/groups/media.png"
        )

    def test_filename_only_category(self) -> None:
        assert (
            normalize_icon_spec("apps.png", DEFAULT_CATEGORY_ICON_PATH_PREFIX)
            == "plugins/images/categories/apps.png"
        )

    def test_https_url_passthrough(self) -> None:
        url = "https://example.com/icon.png"
        assert normalize_icon_spec(url, DEFAULT_GROUP_ICON_PATH_PREFIX) == url

    def test_full_path_passthrough(self) -> None:
        path = "plugins/custom/groups/my.png"
        assert normalize_icon_spec(path, DEFAULT_GROUP_ICON_PATH_PREFIX) == path

    def test_empty_returns_empty(self) -> None:
        assert normalize_icon_spec("", DEFAULT_GROUP_ICON_PATH_PREFIX) == ""
