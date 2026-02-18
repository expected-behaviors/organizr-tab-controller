# CI/CD: GitHub Actions and publishing

This project automates the full release cycle: **merge to main** → auto-release (tag + GitHub Release) → **Docker** and **Helm** publish → **release notes** from the merged PR (summarized as bullet points via OpenAI).

## Workflows

| Workflow file | Trigger | Purpose |
|---------------|---------|--------|
| [release-on-merge.yml](release-on-merge.yml) | Push to `main` (code paths only) | Bump patch version, create tag (e.g. `v0.1.1`) and publish GitHub Release |
| [docker-publish.yml](docker-publish.yml) | **Release published** (and push to `main` for `latest`) | Build image and push to Docker Hub |
| [helm-publish.yml](helm-publish.yml) | **Release published** or *Release on merge* completes | Package chart and upload `.tgz` to the GitHub Release |
| [release-notes.yml](release-notes.yml) | **Release published** or *Release on merge* completes | Set release body from merged PR; OpenAI summarizes into bullet points (requires `OPENAI_API_KEY`) |

### What runs when

- **Merge a PR into `main`** (that touches `docker/`, `src/`, `helm/`, or `pyproject.toml`): **Release on merge** runs → creates the next `v*` tag and a GitHub Release. That **release published** event triggers: **Docker** build/push, **Helm** package/upload, and **Release notes** (OpenAI summary).

- **Push to `main`** without those paths (e.g. docs only): no new release; **Docker** still runs if its paths changed (tags `latest` and `sha-*`).

- **Manually create a release** (tag + publish in the UI or `gh release create`): same as above – Docker, Helm, and release notes all run.

**Note:** Helm publish and Release notes also run when **Release on merge to main** completes (workflow_run fallback). That way they still run even if the `release: published` event doesn’t trigger them (e.g. release created by another workflow).

**Manual run:** You can run **Docker build and publish**, **Helm chart publish**, and **Release notes from PR** from the Actions tab (**Run workflow**). Optional inputs:
- **Docker:** `image_tag` – tag for the image (default: `sha-<short-sha>`).
- **Helm / Release notes:** `release_tag` – e.g. `v0.1.0` (default: latest release).

---

## Required secrets

Add these under **Settings → Secrets and variables → Actions** in the repo.

| Credential | Required? | Used by | How to create |
|------------|-----------|---------|----------------|
| **GITHUB_TOKEN** | No (automatic) | All workflows | Provided by GitHub Actions; no setup. |
| **DOCKERHUB_USERNAME** | **Yes** (for Docker publish) | Docker build and publish | Your Docker Hub username. |
| **DOCKERHUB_TOKEN** | **Yes** (for Docker publish) | Docker build and publish | Docker Hub **Personal Access Token** (not your password). See below. |
| **OPENAI_API_KEY** | **Yes** (for release notes) | Release notes from PR | OpenAI API key; workflow fails if unset. New accounts often get free trial credits. See below. |

### Docker Hub Personal Access Token

1. Log in at [hub.docker.com](https://hub.docker.com).
2. Click your username (top right) → **Account Settings** → **Security** → **New Access Token**.
3. Name it (e.g. `github-actions-organizr-tab-controller`), set permissions to **Read & Write**.
4. Generate and **copy the token once** (it won’t be shown again).
5. In your GitHub repo: **Settings → Secrets and variables → Actions** → **New repository secret** → Name: `DOCKERHUB_TOKEN`, Value: paste the token. Also add `DOCKERHUB_USERNAME` with your Docker Hub username.

Image is pushed as `DOCKER_REPO_PREFIX/DOCKER_IMAGE:<tag>`. Set `DOCKER_REPO_PREFIX` (and optionally `DOCKER_IMAGE`) in the workflow `env` in `docker-publish.yml` to match your Docker Hub namespace and image name.

### OpenAI API key (required for release notes)

1. Sign in at [platform.openai.com](https://platform.openai.com/) (or create an account; new accounts often get free trial credits).
2. Go to [API keys](https://platform.openai.com/api-keys) → **Create new secret key**.
3. Name it (e.g. `github-release-notes`), copy the key once.
4. In your GitHub repo: **Settings → Secrets and variables → Actions** → **New repository secret** → Name: `OPENAI_API_KEY`, Value: paste the key.

The **Release notes from PR** workflow fails if `OPENAI_API_KEY` is not set.

**Security:** GitHub stores secrets encrypted and does not show values in logs. The key is only sent to OpenAI’s API over HTTPS from GitHub’s runners.

---

## Release notes (OpenAI bullet points)

The **Release notes from PR** workflow:

1. Finds the **PR that was merged** for the release commit.
2. Uses that PR’s **description** as input.
3. Calls OpenAI (`gpt-4o-mini`) to summarize it into **2–4 short bullet points** and sets that as the release body.

---

## Automated release cycle (merge → release)

1. You merge a PR into `main` that touches `docker/`, `src/`, `helm/`, or `pyproject.toml`.
2. **Release on merge to main** runs: computes the next patch version (e.g. last tag `v0.1.0` → `v0.1.1`), creates that tag and a GitHub Release with a short placeholder note.
3. The **release published** event triggers:
   - **Docker** – build and push image (e.g. `0.1.1` and `latest`).
   - **Helm** – package chart with that version and upload the `.tgz` to the release.
   - **Release notes** – replace the placeholder with OpenAI-generated bullet summary.

No manual tagging or release creation needed for the standard flow.

---

## Helm chart publishing

- On **release published**, the **Helm chart publish** workflow sets chart **version** and **appVersion** from the release tag, sets the default **image tag** in the packaged chart to that version (e.g. `docker.io/expectedbehaviors/organizr-tab-controller:0.1.1`), and uploads `organizr-tab-controller-<version>.tgz` to the GitHub Release.
- **From Git (Argo CD / Helm):** use repo URL and path `helm/` (see [helm/README.md](../../helm/README.md)); image tag will be `latest` unless overridden.
- **Artifact Hub:** add this GitHub repo as a Helm repository and point it at **GitHub Releases** so the chart and versions appear there.

---

## Other CI you might add

- **Tests on PR:** `pytest` (and optionally `ruff` / `mypy`) on pull requests.
- **Build-only on PR:** `docker build` (no push) when `docker/` or `src/` change.
- **Image scanning:** e.g. Trivy in the Docker workflow before push.
- **Helm lint:** `helm lint helm/` in the Helm workflow.
