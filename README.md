# organizr-tab-controller

A Kubernetes controller that automatically manages [Organizr](https://organizr.app) tabs by watching annotated Kubernetes resources. Inspired by the patterns used by [external-dns](https://github.com/kubernetes-sigs/external-dns) and [Reloader](https://github.com/stakater/Reloader).

## About Organizr

[Organizr](https://organizr.app) is a homelab dashboard that aggregates your services (Plex, Radarr, Sonarr, etc.) into a single UI with tabs, auth, and health checks. This controller talks to Organizr’s API to create and update those tabs from Kubernetes annotations.

- **Documentation:** [docs.organizr.app](https://docs.organizr.app/) — installation, features, and configuration.
- **API reference:** [demo.organizr.app/docs](https://demo.organizr.app/docs/) — interactive API docs (RapiDoc) for the endpoints this controller uses (tabs, categories, groups).
- **Running Organizr:** There is no single “official” Helm chart; common options are:
  - **Docker (official):** [organizr/organizr](https://hub.docker.com/r/organizr/organizr) on Docker Hub (also `ghcr.io/organizr/organizr`).
  - **LinuxServer.io:** [linuxserver/organizr](https://hub.docker.com/r/linuxserver/organizr) — note [LinuxServer has deprecated this image](https://docs.linuxserver.io/deprecated_images/docker-organizr/); consider the official image or Hotio for new installs.
  - **Hotio:** [hotio.dev/containers](https://hotio.dev/containers/) — community images for many homelab apps; check for Organizr or use the official image.

You need a running Organizr instance and an API key (from Organizr’s Settings → API Keys) to use this controller.

## Project layout

| Path | Purpose |
|------|--------|
| **Root** | Tool source code (`src/`, `tests/`), and this README (overview, annotations, config, development). |
| **[docker/](docker/)** | Container image build (hardened Chainguard Python base, non-root). Build from repo root. |
| **[helm/](helm/)** | Kubernetes deployment chart. [BJW-S app-template](https://bjw-s-labs.github.io/helm-charts/docs/app-template/) wrapper with HPA, no ingress, RBAC; only what the controller needs. |
| **[.github/workflows/](.github/workflows/)** | GitHub Actions workflows and [CI/CD documentation](.github/workflows/README.md) (credentials, triggers, release flow). |

## Overview

Instead of manually configuring Organizr tabs through the UI, annotate your Kubernetes Ingresses, Services, Deployments (or any resource) and let the controller create, update, and optionally delete Organizr tabs automatically.

**Key features:**

- Watches any Kubernetes resource type (Ingress, Service, Deployment, StatefulSet, DaemonSet)
- Passively derives tab name, URL, icon, ping URL, and local URL from resource metadata
- Built-in icon matching for 60+ common homelab apps (Radarr, Sonarr, Plex, etc.)
- Configurable sync policy: `upsert` (safe, default) or `sync` (full reconciliation with deletions)
- Supports both Organizr API v2 and v1 (legacy) endpoints
- Runs as a stateless Deployment; supports HA via leader election
- Runnable as a Docker container or directly as a Python script

## Quick Start

### 1. Annotate your resources

Add a single annotation to opt in:

```yaml
# In any Helm chart values.yaml
ingress:
  main:
    annotations:
      organizr-tab-controller.io/enabled: "true"
      # Everything else is auto-derived!
```

The controller will automatically determine:
- **Tab name** from `app.kubernetes.io/name` label or resource name
- **Tab URL** from the Ingress host (with HTTPS)
- **Icon** by matching the app name against the built-in icon library
- **Ping URL** from the Service ClusterIP and port

### 2. Deploy the controller

```bash
# Build the container (from repo root)
docker build -f docker/Dockerfile -t organizr-tab-controller:latest .

# Or run directly with Python
pip install -e .
ORGANIZR_API_URL=https://organizr.example.com \
ORGANIZR_API_KEY=your-api-key \
python -m organizr_tab_controller

# Or install the Helm chart (HPA, no ingress; see helm/README.md)
helm dependency update helm/
helm install organizr-tab-controller ./helm -n organizr --create-namespace \
  --set organizr-tab-controller.controllers.main.containers.main.env.ORGANIZR_API_URL=https://organizr.example.com
```

### 3. Watch tabs appear in Organizr

The controller reconciles every 60 seconds (configurable) and reacts to Kubernetes watch events in real-time.

Annotations use a **generic prefix** (`organizr-tab-controller.io`) so the same manifests work with any Kubernetes + Organizr setup, not tied to a specific domain.

## Annotation Reference

All annotations use the prefix `organizr-tab-controller.io/`. Group and category are specified by **human-readable names**; the controller resolves them to Organizr API IDs (and creates categories if missing) before creating or updating tabs.

| Annotation | Required | Default | Description |
|---|---|---|---|
| `enabled` | Yes | - | Set to `"true"` to opt in |
| `name` | No | From `app.kubernetes.io/name` label or resource name (title-cased) | Tab display name |
| `url` | No | From Ingress host (HTTPS) or `external-dns` hostname annotation | Tab URL |
| `url-local` | No | From Service ClusterIP (cluster-internal DNS) | Local/RFC1918 URL |
| `ping-url` | No | From Service name:port or Ingress host:443 | Health check endpoint (no scheme) |
| `image` | No | Auto-matched from app name | Icon: known name (e.g. `radarr`), full URL, or `fontawesome::icon` |
| `type` | No | `iframe` | Tab type: `iframe`, `new-window`, or `internal` |
| `group` | No | (default group) | **Group name** (e.g. `Media`, `Admin`). Controller resolves to Organizr group ID; does not create groups. |
| `group-icon` | No | - | Icon for the group: filename only (e.g. `media.png` → path completion), full path, or `http(s)://` URL. Applied when group exists. |
| `category` | No | - | **Category name** (e.g. `Media Apps`). Controller creates the category if missing, then assigns the tab to it. |
| `category-icon` | No | - | Icon for the category: filename only, full path, or `http(s)://` URL. Set when creating or updating the category. |
| `order` | No | Auto-assigned | Tab position/weight |
| `default` | No | `false` | Default tab on login |
| `active` | No | `true` | Whether the tab is enabled |
| `splash` | No | `false` | Show on splash/login screen |
| `ping` | No | `true` (if ping URL derivable) | Enable ping health check |
| `preload` | No | `false` | Preload tab on login |

## Configuration

All settings are configured via environment variables with the `ORGANIZR_` prefix.

| Environment Variable | Required | Default | Description |
|---|---|---|---|
| `ORGANIZR_API_URL` | Yes | - | Organizr base URL (e.g. `https://organizr.example.com`) |
| `ORGANIZR_API_KEY` | No* | - | API key (or use `ORGANIZR_API_KEY_FILE`) |
| `ORGANIZR_API_KEY_FILE` | No | `/var/run/secrets/organizr/api-key` | Path to file containing API key (K8s Secret mount) |
| `ORGANIZR_API_VERSION` | No | `v2` | API version: `v2` or `v1` |
| `ORGANIZR_API_TIMEOUT` | No | `30` | HTTP timeout (seconds) |
| `ORGANIZR_SYNC_POLICY` | No | `upsert` | `upsert` (create/update only) or `sync` (create/update/delete) |
| `ORGANIZR_RECONCILE_INTERVAL` | No | `60` | Seconds between full reconciliation |
| `ORGANIZR_WATCH_NAMESPACES` | No | (all) | Comma-separated list of namespaces to watch |
| `ORGANIZR_WATCH_RESOURCE_TYPES` | No | `ingresses,services,deployments,statefulsets,daemonsets` | Resource types to watch |
| `ORGANIZR_ENABLE_LEADER_ELECTION` | No | `false` | Enable for HA (multiple replicas); reserved for future use |
| `ORGANIZR_LEADER_ELECTION_NAMESPACE` | No | `default` | Namespace for the leader-election Lease |
| `ORGANIZR_LEADER_ELECTION_NAME` | No | `organizr-tab-controller-leader` | Name of the leader-election Lease object |
| `ORGANIZR_LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `ORGANIZR_LOG_FORMAT` | No | `json` | `json` or `console` |

*Either `ORGANIZR_API_KEY` or a valid file at `ORGANIZR_API_KEY_FILE` is required.

### Group and category icons

For `group-icon` and `category-icon`:

- **Filename only** (e.g. `media.png`): the controller prepends Organizr’s default path (`plugins/images/groups/` or `plugins/images/categories/`) so the icon is resolved relative to Organizr’s install.
- **Full path** (e.g. `plugins/custom/groups/my.png`): used as-is.
- **`http://` or `https://` URL**: used as-is.

Categories can be created by name; the controller ensures the category exists (and sets its icon if provided) before creating tabs. Groups are matched by name only; the controller does not create groups but can set an icon for an existing group.

## Examples

### Minimal: auto-derive everything

```yaml
# radarr ingress — controller auto-derives:
#   name: "Radarr", url: "https://radarr.example.com", icon: radarr.png
ingress:
  main:
    annotations:
      organizr-tab-controller.io/enabled: "true"
    hosts:
      - host: radarr.example.com
        paths:
          - path: /
```

### Explicit overrides

```yaml
ingress:
  main:
    annotations:
      organizr-tab-controller.io/enabled: "true"
      organizr-tab-controller.io/name: "Movie Manager"
      organizr-tab-controller.io/image: "https://cdn.example.com/custom-icon.png"
      organizr-tab-controller.io/type: "new-window"
      organizr-tab-controller.io/group: "Media"
      organizr-tab-controller.io/category: "Media Apps"
      organizr-tab-controller.io/group-icon: "media.png"
      organizr-tab-controller.io/category-icon: "https://example.com/cat.png"
```

### Service-level annotation

```yaml
# Annotate a Service instead of an Ingress
service:
  main:
    annotations:
      organizr-tab-controller.io/enabled: "true"
      organizr-tab-controller.io/url: "https://myapp.example.com"
```

### Deployment-level annotation

```yaml
# Annotate a Deployment
defaultPodOptions:
  # Note: pod annotations won't work — use the Deployment itself
controllers:
  main:
    annotations:
      organizr-tab-controller.io/enabled: "true"
      organizr-tab-controller.io/url: "https://myapp.example.com"
      organizr-tab-controller.io/image: "fontawesome::server"
```

## Kubernetes deployment (raw manifests)

Example Kubernetes manifests for deploying the controller (alternative to the [Helm chart](helm/)):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: organizr-tab-controller
  namespace: organizr
spec:
  replicas: 1  # Set to 2 with leader election for HA
  selector:
    matchLabels:
      app.kubernetes.io/name: organizr-tab-controller
  template:
    metadata:
      labels:
        app.kubernetes.io/name: organizr-tab-controller
    spec:
      serviceAccountName: organizr-tab-controller
      containers:
        - name: controller
          image: docker.io/expectedbehaviors/organizr-tab-controller:latest
          env:
            - name: ORGANIZR_API_URL
              value: "https://organizr.example.com"  # Your Organizr base URL
            - name: ORGANIZR_API_KEY_FILE
              value: "/var/run/secrets/organizr/api-key"
            - name: ORGANIZR_SYNC_POLICY
              value: "upsert"
            - name: ORGANIZR_LOG_LEVEL
              value: "INFO"
          volumeMounts:
            - name: api-key
              mountPath: /var/run/secrets/organizr
              readOnly: true
          resources:
            requests:
              cpu: 50m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
          securityContext:
            runAsNonRoot: true
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
      volumes:
        - name: api-key
          secret:
            secretName: organizr-api-key
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: organizr-tab-controller
  namespace: organizr
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: organizr-tab-controller
rules:
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["get", "create", "update"]  # For leader election
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: organizr-tab-controller
subjects:
  - kind: ServiceAccount
    name: organizr-tab-controller
    namespace: organizr
roleRef:
  kind: ClusterRole
  name: organizr-tab-controller
  apiGroup: rbac.authorization.k8s.io
```

## Passive Derivation Logic

When only `organizr-tab-controller.io/enabled: "true"` is set, the controller automatically derives:

1. **Name**: `app.kubernetes.io/name` label (title-cased), falling back to the resource name
2. **URL**: First Ingress host with HTTPS scheme, or `external-dns.alpha.kubernetes.io/hostname`
3. **Local URL**: `http://<service>.<namespace>.svc.cluster.local:<port>` (Services only)
4. **Ping URL**: `<service>.<namespace>:<port>` (Services) or `<host>:443` (Ingresses)
5. **Icon**: Fuzzy-matched from app name against 60+ built-in homelab app icons

## Icon Library

The controller ships with icons for these apps (and more):

**Media**: Plex, Jellyfin, Emby, Tautulli, Ombi, Overseerr
**Arr Suite**: Sonarr, Radarr, Lidarr, Readarr, Prowlarr, Bazarr, Whisparr
**Downloads**: SABnzbd, qBittorrent, Transmission, Deluge, NZBGet
**Reading**: Kavita, Komga, Mylar, Calibre, Calibre-web, Audiobookshelf
**Home Automation**: Home Assistant, Node-RED
**Infrastructure**: Grafana, Portainer, Proxmox, Unraid, TrueNAS, Longhorn
**Networking**: Pi-hole, AdGuard, Nginx, Traefik, Unifi
**Other**: Immich, Bitwarden/Vaultwarden, Nextcloud, Gitea, GitLab, Gaps, Uptime Kuma

Custom icons: set `image` annotation to any URL or `fontawesome::icon-name`.

## Development

From the repo root:

```bash
# Clone and install
git clone git@github.com:expectedbehaviors/organizr-tab-controller.git
cd organizr-tab-controller
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest -v

# Lint
ruff check src/ tests/

# Type check
mypy src/

# Build image (context = root)
docker build -f docker/Dockerfile -t organizr-tab-controller:latest .
```

## Architecture

```
K8s Resources (annotated)
        |
        v
  K8s Watcher (watch streams + periodic list)
        |
        v
  Tab Reconciler (desired vs actual state diff)
        |
        v
  Organizr API Client (create / update / delete)
        |
        v
  Organizr Instance (tabs managed)
```

The controller is fully stateless — all state is derived from Kubernetes resources and the Organizr API on each reconciliation cycle.

## Support this project

I build tools to get the best homelab experience I can from what’s available and to grow as a programmer along the way. If you’d like to contribute, donations go toward homelab operating costs and subscriptions that keep this tooling maintained. Optional and appreciated.

[![Donate with PayPal](https://www.paypalobjects.com/en_US/i/btn/btn_donate_LG.gif)](https://www.paypal.com/donate/?business=9RHVW92WMWQNL&no_recurring=0&item_name=Optional+donations+help+support+Expected+Behaviors%E2%80%99+open+source+work.+Thank+you.&currency_code=USD)

## License

GPL-3.0-or-later
