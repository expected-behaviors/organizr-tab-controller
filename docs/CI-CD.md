# CI/CD: GitHub Actions and publishing

This project automates the full release cycle: **merge to main** → auto-release (tag + GitHub Release) → **Docker** and **Helm** publish → **release notes** from the merged PR (summarized as bullet points via OpenAI when configured).

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|--------|
| **Release on merge to main** | Push to `main` (code paths only) | Bump patch version, create tag (e.g. `v0.1.1`) and publish GitHub Release. |
| **Docker build and publish** | **Release published** (and push to `main` for `latest`) | Build image and push to Docker Hub. |
| **Helm chart publish** | **Release published** | Package chart and upload `.tgz` to the GitHub Release. |
| **Release notes from PR** | **Release published** | Set release body from merged PR; optional OpenAI bullet-point summary. |

### What runs when

- **Merge a PR into `main`** (that touches `docker/`, `src/`, `helm/`, or `pyproject.toml`):  
  **Release on merge** runs → creates the next `v*` tag and a GitHub Release.  
  That **release published** event triggers: **Docker** build/push, **Helm** package/upload, and **Release notes** (PR body or OpenAI summary).

- **Push to `main`** without those paths (e.g. docs only): no new release; **Docker** still runs if its paths changed (tags `latest` and `sha-*`).

- **Manually create a release** (tag + publish in the UI or `gh release create`): same as above – Docker, Helm, and release notes all run.

---

## Required secrets

### Docker Hub

Add these under **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `DOCKERHUB_USERNAME` | Your Docker Hub username. |
| `DOCKERHUB_TOKEN` | Docker Hub **Personal Access Token** (not your password). |

**Create a token:** [Docker Hub](https://hub.docker.com) → Account Settings → Security → New Access Token → **Read & Write**.  
Image is pushed as `$DOCKERHUB_USERNAME/organizr-tab-controller:<tag>`.

### OpenAI (release notes – recommended)

To get **short bullet-point release notes** from the merged PR description instead of the raw text:

| Secret | Description |
|--------|-------------|
| `OPENAI_API_KEY` | OpenAI API key used only in the **Release notes from PR** workflow. |

**How to get an OpenAI API key**

1. Go to [OpenAI Platform](https://platform.openai.com/) and sign in (or create an account).
2. **API keys**: [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys) → **Create new secret key**.
3. Name it (e.g. `github-release-notes`), copy the key once (it won’t be shown again).
4. In your **GitHub repo**: **Settings → Secrets and variables → Actions → New repository secret**.
5. Name: `OPENAI_API_KEY`, Value: paste the key → **Add secret**.

**Security**

- GitHub stores secrets **encrypted** and does not show values in logs. Workflows reference `${{ secrets.OPENAI_API_KEY }}`; the value is never printed.
- The key is only sent to OpenAI’s API over HTTPS from GitHub’s runners. Use a key with minimal scope if your account supports it.
- If you don’t set `OPENAI_API_KEY`, the workflow uses the PR description as-is and adds a notice to the job log pointing to this doc.

---

## Release notes (ChatGPT-style bullets)

The **Release notes from PR** workflow:

1. Finds the **PR that was merged** for the release commit.
2. Uses that PR’s **description** as input.
3. If **`OPENAI_API_KEY`** is set: calls OpenAI (`gpt-4o-mini`) to summarize it into **2–4 short bullet points** and sets that as the release body.
4. If not set: uses the PR description verbatim and logs a notice.

So: add `OPENAI_API_KEY` as above for minimal, clean bullet-point release notes with no extra manual work.

---

## Automated release cycle (merge → release)

1. You merge a PR into `main` that touches `docker/`, `src/`, `helm/`, or `pyproject.toml`.
2. **Release on merge to main** runs: computes the next patch version (e.g. last tag `v0.1.0` → `v0.1.1`), creates that tag and a GitHub Release with a short placeholder note.
3. The **release published** event triggers:
   - **Docker** – build and push image (e.g. `0.1.1` and `latest`).
   - **Helm** – package chart with that version and upload the `.tgz` to the release.
   - **Release notes** – replace the placeholder with PR description or OpenAI bullet summary.

No manual tagging or release creation needed for the standard flow.

---

## Helm chart publishing

- On **release published**, the **Helm chart publish** workflow:
  - Sets chart **version** and **appVersion** from the release tag (e.g. `v0.1.1` → `0.1.1`).
  - Sets the default **image tag** in the packaged chart to that same version, so installs from the release tarball use the matching image (e.g. `docker.io/jd4883/organizr-tab-controller:0.1.1`). Source `helm/values.yaml` in Git keeps `tag: latest` for local/dev; only the **released** `.tgz` has the version-pinned default.
  - Uploads `organizr-tab-controller-0.1.1.tgz` to the GitHub Release.
- **From Git (Argo CD / Helm):** use repo URL and path `helm/` (see [helm/README.md](../helm/README.md)); image tag will be `latest` unless overridden.
- **Artifact Hub:** add this GitHub repo as a Helm repository and point it at **GitHub Releases** so the chart and versions appear there.

---

## Other CI you might add

- **Tests on PR:** `pytest` (and optionally `ruff` / `mypy`) on pull requests.
- **Build-only on PR:** `docker build` (no push) when `docker/` or `src/` change.
- **Image scanning:** e.g. Trivy in the Docker workflow before push.
- **Helm lint:** `helm lint helm/` in the Helm workflow.

These can be added as extra jobs or workflows when you want them.
