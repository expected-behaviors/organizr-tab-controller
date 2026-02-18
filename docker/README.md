# Container image

**Hardened base** (Chainguard Python): distroless runtime, non-root, minimal attack surface.

**Build from the repository root** (required):

```bash
docker build -f docker/Dockerfile -t organizr-tab-controller:latest .
```

## Why build from repo root?

The **build context** is the root directory (`.`), not `docker/`. The Dockerfile lives under `docker/` for organization, but it `COPY`s files from the context:

- `COPY pyproject.toml README.md ./`
- `COPY src/ src/`

Those paths are relative to the context, so they point at the repo root. That way:

- **One source tree** – `src/` is the same package you use for local development (`pip install -e .`, `pytest`). Tests, tooling, and the image all use the same code.
- **No duplication** – We don’t put `src/` inside `docker/` because that would duplicate the package or force the rest of the repo (e.g. `tests/`) to import from `docker/src/`, which is brittle and non-standard.

So: context = root, Dockerfile in `docker/`, and the image is built from the root. This matches common practice for Python projects (e.g. LinuxServer, many OSS apps).

See the [root README](../README.md) for full tool documentation and deployment options.
