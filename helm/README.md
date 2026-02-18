# Helm chart (organizr-tab-controller)

Kubernetes deployment for **organizr-tab-controller**. Security-hardened defaults: non-root, no ingress, minimal surface. Based on [bjw-s app-template](https://bjw-s-labs.github.io/helm-charts/docs/app-template/); only the resources the controller needs are enabled.

## What this chart does

- **Deployment** – single controller container (image, env, resources, API key from Secret).
- **Service** – for pod selector/labels (controller does not serve HTTP).
- **RBAC** – ServiceAccount, ClusterRole, ClusterRoleBinding (watch Ingresses, Services, Deployments, StatefulSets, DaemonSets, Leases).
- **HPA** – optional horizontal pod autoscaling (default: min 1, max 3).
- **No ingress, no persistence** – controller is cluster-internal and stateless.

## Requirements

- Kubernetes 1.28+
- **Organizr API URL** – set via values or `--set`.
- **Organizr API key** – in a Secret named `organizr-api-key` in the release namespace, with key `api-key` (or override env to use a different secret/key).

---

## Deploy with Helm

**1. Create namespace and API key secret** (if not already present):

```bash
kubectl create namespace organizr --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic organizr-api-key -n organizr \
  --from-literal=api-key="YOUR_ORGANIZR_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
```

**2. Install the chart** (from repo root after `helm dependency update helm/`):

```bash
helm repo add bjw-s https://bjw-s-labs.github.io/helm-charts
helm dependency update helm/

helm install organizr-tab-controller ./helm -n organizr --create-namespace \
  --set organizr-tab-controller.controllers.main.containers.main.env.ORGANIZR_API_URL=https://organizr.example.com
```

**3. Upgrade:**

```bash
helm upgrade organizr-tab-controller ./helm -n organizr \
  --set organizr-tab-controller.controllers.main.containers.main.env.ORGANIZR_API_URL=https://organizr.example.com
```

With a values file (e.g. `my-values.yaml` that sets `organizr-tab-controller.controllers.main.containers.main.env.ORGANIZR_API_URL`):

```bash
helm install organizr-tab-controller ./helm -n organizr --create-namespace -f my-values.yaml
```

---

## Deploy with Argo CD

Use either **Option A** (Git repo + chart path) or **Option B** (Helm repo from GitHub Releases). In both cases, **provide valid credentials** as below; the examples use default chart values and only override what’s required.

### Prerequisites (both options)

1. **Namespace**  
   Create the target namespace if it doesn’t exist (e.g. `organizr`).

2. **Organizr API key**  
   Create a Secret in that namespace with the key the chart expects:
   ```bash
   kubectl create secret generic organizr-api-key -n organizr \
     --from-literal=api-key="YOUR_ORGANIZR_API_KEY"
   ```
   (Or use ExternalSecrets / your secret manager and ensure the secret name and key match.)

3. **Organizr API URL**  
   Set in the Application (see examples). Replace `https://organizr.example.com` with your Organizr base URL.

With that in place, the following examples work with default values.

---

### Option A: Git repo + Helm chart path

Argo CD pulls the repo and renders the chart from the `helm/` directory. Good for tracking a branch or tag; no separate Helm repo needed.

**1. Application manifest** – save as e.g. `argocd-organizr-tab-controller.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: organizr-tab-controller
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/jd4883/organizr-tab-controller.git
    targetRevision: main
    path: helm
    helm:
      valueFiles:
        - values.yaml
      parameters:
        - name: organizr-tab-controller.controllers.main.containers.main.env.ORGANIZR_API_URL
          value: "https://organizr.example.com"
  destination:
    server: https://kubernetes.default.svc
    namespace: organizr
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**2. Apply:**

```bash
kubectl apply -f argocd-organizr-tab-controller.yaml
```

**3. Optional overrides** (image, log level, etc.) – add under `source.helm.parameters`, for example:

```yaml
        - name: organizr-tab-controller.controllers.main.containers.main.image.tag
          value: "v0.1.0"
        - name: organizr-tab-controller.controllers.main.containers.main.env.ORGANIZR_LOG_LEVEL
          value: "DEBUG"
```

**Private repo:** set `source.repoURL` to your SSH or HTTPS URL and configure Argo CD credentials (Repository credentials or SSH key) so it can clone the repo.

---

### Option B: Helm repo (chart from GitHub Releases)

Use this when you consume the chart from a Helm repo (e.g. one built from GitHub Release assets). The chart is installed by name and version; you still need the same Secret and namespace.

**1. Add the Helm repo** (if your releases are published as a repo, e.g. GitHub Pages):

```bash
helm repo add organizr-tab-controller https://jd4883.github.io/organizr-tab-controller/
helm repo update
```

**2. Application manifest** – reference the chart and set required values:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: organizr-tab-controller
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://jd4883.github.io/organizr-tab-controller/
    chart: organizr-tab-controller
    targetRevision: "0.1.0"
    helm:
      values: |
        fullnameOverride: organizr-tab-controller
        rbac:
          create: true
        hpa:
          enabled: true
        organizr-tab-controller:
          global:
            fullnameOverride: organizr-tab-controller
          controllers:
            main:
              containers:
                main:
                  env:
                    ORGANIZR_API_URL: "https://organizr.example.com"
  destination:
    server: https://kubernetes.default.svc
    namespace: organizr
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**3. Apply:**

```bash
kubectl apply -f argocd-organizr-tab-controller-helm-repo.yaml
```

Replace `repoURL` and `targetRevision` with your actual Helm repo URL and chart version. The API key still comes from the `organizr-api-key` Secret (default values); ensure that Secret exists in the `organizr` namespace.

---

## Chart layout

- **Chart.yaml** – bjw-s app-template dependency (alias `organizr-tab-controller`).
- **values.yaml** – security defaults, single controller, no ingress/persistence, HPA, RBAC.
- **templates/** – ServiceAccount, ClusterRole, ClusterRoleBinding (when `rbac.create`), HPA (when `hpa.enabled`).

Full tool docs and annotations: [root README](../README.md).
