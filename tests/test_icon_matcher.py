"""Tests for the icon_matcher module."""

from organizr_tab_controller.icon_matcher import match_icon, normalise_name


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
