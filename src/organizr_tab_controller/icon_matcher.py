"""Passive icon matching and icon spec normalization for Organizr.

When no explicit ``organizr-tab-controller.io/image`` annotation is set on
a Kubernetes resource, the controller attempts to match the app name against a
built-in dictionary of known icons that ship with Organizr.

Organizr stores its built-in tab images under ``plugins/images/tabs/`` (PNG)
and also recognises ``fontawesome::<icon-name>`` references.

Group and category icons support: filename-only (path completion), full path, or http(s) URL.
"""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Known icon mapping
# ---------------------------------------------------------------------------
# Keys are normalised app names (lowercase, stripped of special chars).
# Values are the image string Organizr expects (relative path or fontawesome).
#
# Organizr ships a large library of tab icons under plugins/images/tabs/.
# The mapping below covers the most common homelab apps.  Additional entries
# can be added trivially.

_ICON_MAP: dict[str, str] = {
    # *arr suite
    "bazarr": "plugins/images/tabs/bazarr.png",
    "lidarr": "plugins/images/tabs/lidarr.png",
    "prowlarr": "plugins/images/tabs/prowlarr.png",
    "radarr": "plugins/images/tabs/radarr.png",
    "readarr": "plugins/images/tabs/readarr.png",
    "sonarr": "plugins/images/tabs/sonarr.png",
    "whisparr": "plugins/images/tabs/whisparr.png",
    # Download clients
    "deluge": "plugins/images/tabs/deluge.png",
    "nzbget": "plugins/images/tabs/nzbget.png",
    "qbittorrent": "plugins/images/tabs/qbittorrent.png",
    "rtorrent": "plugins/images/tabs/rtorrent.png",
    "rutorrent": "plugins/images/tabs/rutorrent.png",
    "sabnzbd": "plugins/images/tabs/sabnzbd.png",
    "transmission": "plugins/images/tabs/transmission.png",
    # Media servers
    "emby": "plugins/images/tabs/emby.png",
    "jellyfin": "plugins/images/tabs/jellyfin.png",
    "plex": "plugins/images/tabs/plex.png",
    # Media management
    "calibre": "plugins/images/tabs/calibre.png",
    "calibreweb": "plugins/images/tabs/calibreweb.png",
    "kavita": "plugins/images/tabs/kavita.png",
    "komga": "plugins/images/tabs/komga.png",
    "mylar": "plugins/images/tabs/mylar.png",
    "ombi": "plugins/images/tabs/ombi.png",
    "overseerr": "plugins/images/tabs/overseerr.png",
    "petio": "plugins/images/tabs/petio.png",
    "tautulli": "plugins/images/tabs/tautulli.png",
    # Home automation
    "homeassistant": "plugins/images/tabs/homeassistant.png",
    "home-assistant": "plugins/images/tabs/homeassistant.png",
    "nodered": "plugins/images/tabs/nodered.png",
    "node-red": "plugins/images/tabs/nodered.png",
    # Infrastructure / admin
    "grafana": "plugins/images/tabs/grafana.png",
    "portainer": "plugins/images/tabs/portainer.png",
    "proxmox": "plugins/images/tabs/proxmox.png",
    "unraid": "plugins/images/tabs/unraid.png",
    "truenas": "plugins/images/tabs/truenas.png",
    # Networking / DNS
    "pihole": "plugins/images/tabs/pihole.png",
    "adguard": "plugins/images/tabs/adguard.png",
    "nginx": "plugins/images/tabs/nginx.png",
    "traefik": "plugins/images/tabs/traefik.png",
    "unifi": "plugins/images/tabs/unifi.png",
    # Dashboards
    "organizr": "plugins/images/tabs/organizr.png",
    "heimdall": "plugins/images/tabs/heimdall.png",
    "homepage": "plugins/images/tabs/homepage.png",
    # Development
    "gitea": "plugins/images/tabs/gitea.png",
    "gitlab": "plugins/images/tabs/gitlab.png",
    "jenkins": "plugins/images/tabs/jenkins.png",
    # Storage
    "minio": "plugins/images/tabs/minio.png",
    "nextcloud": "plugins/images/tabs/nextcloud.png",
    "syncthing": "plugins/images/tabs/syncthing.png",
    # Misc
    "bitwarden": "plugins/images/tabs/bitwarden.png",
    "vaultwarden": "plugins/images/tabs/vaultwarden.png",
    "bookstack": "plugins/images/tabs/bookstack.png",
    "duplicati": "plugins/images/tabs/duplicati.png",
    "filebrowser": "plugins/images/tabs/filebrowser.png",
    "gaps": "plugins/images/tabs/gaps.png",
    "guacamole": "plugins/images/tabs/guacamole.png",
    "jackett": "plugins/images/tabs/jackett.png",
    "monica": "plugins/images/tabs/monica.png",
    "netdata": "plugins/images/tabs/netdata.png",
    "nzbhydra": "plugins/images/tabs/nzbhydra.png",
    "requestrr": "plugins/images/tabs/requestrr.png",
    "speedtest": "plugins/images/tabs/speedtest.png",
    "tdarr": "plugins/images/tabs/tdarr.png",
    "uptime-kuma": "plugins/images/tabs/uptimekuma.png",
    "uptimekuma": "plugins/images/tabs/uptimekuma.png",
    "watchtower": "plugins/images/tabs/watchtower.png",
    "audiobookshelf": "plugins/images/tabs/audiobookshelf.png",
    "immich": "plugins/images/tabs/immich.png",
    "longhorn": "plugins/images/tabs/longhorn.png",
    # FontAwesome fallbacks for very common concepts
    "settings": "fontawesome::cog",
    "home": "fontawesome::home",
    "search": "fontawesome::search",
    "music": "fontawesome::music",
    "video": "fontawesome::video",
    "download": "fontawesome::download",
}

# Pre-compile a regex to strip non-alpha chars for normalisation
_STRIP_RE = re.compile(r"[^a-z0-9]")


def normalise_name(name: str) -> str:
    """Normalise an app name for fuzzy matching.

    Lowercases, strips dashes / underscores / dots, etc.
    """
    return _STRIP_RE.sub("", name.lower())


def match_icon(app_name: str) -> str | None:
    """Return the Organizr image string for *app_name*, or ``None`` if no match.

    The lookup is fuzzy: ``"Home-Assistant"``, ``"home_assistant"``, and
    ``"homeassistant"`` all resolve to the same icon.

    If *app_name* looks like a URL (starts with ``http`` or ``/``), it is
    returned verbatim — the caller already has a custom image URL.
    """
    if not app_name:
        return None

    # Already a URL or path — pass through as-is
    if app_name.startswith(("http://", "https://", "/")):
        return app_name

    # Already a fontawesome reference
    if app_name.startswith("fontawesome::"):
        return app_name

    normalised = normalise_name(app_name)
    icon = _ICON_MAP.get(normalised)
    if icon:
        logger.debug("icon_matched", app_name=app_name, icon=icon)
    else:
        logger.debug("icon_no_match", app_name=app_name)
    return icon


def get_all_known_icons() -> dict[str, str]:
    """Return a copy of the full icon mapping (useful for debugging / docs)."""
    return dict(_ICON_MAP)


# Default path prefixes for group/category icons when only a filename is given
DEFAULT_GROUP_ICON_PATH_PREFIX = "plugins/images/groups/"
DEFAULT_CATEGORY_ICON_PATH_PREFIX = "plugins/images/categories/"


def normalize_icon_spec(value: str, default_path_prefix: str) -> str:
    """Normalize a group or category icon annotation to a full path or URL.

    - If value is empty, returns empty string.
    - If value starts with ``http://`` or ``https://``, returns as-is (URL).
    - If value contains ``/``, treated as a full path; returns as-is.
    - Otherwise treated as filename only (e.g. ``media.png``); returns
      ``default_path_prefix + value`` (e.g. ``plugins/images/groups/media.png``).

    This allows annotations to specify either a filename (for Organizr's default
    library), a path, or a custom URL.
    """
    if not value or not value.strip():
        return ""
    v = value.strip()
    if v.startswith(("http://", "https://")):
        return v
    if "/" in v:
        return v
    prefix = default_path_prefix.rstrip("/") + "/"
    return prefix + v
