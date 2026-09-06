# Papermerge DMS

A self-hosted deployment of [Papermerge DMS](https://www.papermerge.com/) (document management with OCR and full-text search) via Docker/Podman Compose, built from the [Self-Hosting-Template](https://github.com/Self-Host-Server) tooling for linting, CI, and release automation.

## Stack

`compose.yml` defines:

- **`webapp`** — the Papermerge UI/API. Built from `docker/webapp/Dockerfile`, which layers a small patch over the upstream `papermerge/papermerge:3.5.3` image (see [OIDC / Authentik SSO](#oidc--authentik-sso) below for why).
- **`ocr_worker`** — OCR processing (Celery worker on the `ocr` queue).
- **`i3worker`** — search-index updates (Celery worker on the `i3` queue).
- **`db`** — PostgreSQL.
- **`redis`** — Celery broker/result backend.
- **`solr`** — full-text search index.

## Setup

1. Copy `.env.example` to `.env` and fill in real values — at minimum, generate a secret key and set real passwords:

   ```bash
   cp .env.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # for PAPERMERGE_SECRET_KEY
   ```

   `.env` is gitignored; never commit it.

2. Start the stack:

   ```bash
   docker compose up -d
   ```

   First run builds the `webapp` image and pulls the rest; watch `docker compose ps` until `db`, `redis`, and `solr` report `healthy`.

3. Log in at `http://localhost:12000` with `PAPERMERGE_ADMIN_USERNAME` / `PAPERMERGE_ADMIN_PASSWORD` from your `.env`.

### OCR is not automatic

Uploading a document does **not** trigger OCR by itself — it's a separate, explicit call: `POST /api/tasks/ocr` with `{"document_id": "...", "lang": "eng"}`. The web UI's upload flow handles this for you; if you're driving the API directly, you need to call it yourself.

## OIDC / Authentik SSO

Papermerge supports OIDC login via generic OAuth2 endpoint URLs (token/userinfo/introspect) rather than issuer-based discovery. To enable it:

1. Create an OAuth2/OIDC Provider + Application in Authentik (or another OIDC provider). Register the redirect URI as exactly `<http|https>://<your domain>/oidc/callback`.
2. Fill in the six `PAPERMERGE_OIDC_*` variables in `.env` with that provider's client ID/secret and its token/userinfo/introspect endpoint URLs. Leaving them at the `.env.example` placeholders is harmless — nothing calls them unless something actually initiates an OIDC login.

**Custom image layer:** `docker/webapp/Dockerfile` patches three files in upstream core_app (see `docker/webapp/patches/*.py` for the full diff and comments) to fix bugs that otherwise break first-time OIDC/JWT login entirely:

- `get_user()` never raised the exception its callers expected, so any brand-new identity 500'd instead of being auto-provisioned.
- The auto-provisioning code mishandled `create_user()`'s return value (and was missing `await` in one branch).
- `get_current_user()` called a function (`get_user_scopes_from_groups`) that doesn't exist anywhere in the codebase, crashing on any token with a non-empty `groups` claim.

With those fixed, OIDC `groups`/`roles` claims map to existing Papermerge **Roles** by name (case-insensitive). Set `PAPERMERGE_OIDC_DEFAULT_ROLE` to an existing role name to grant it as a baseline to SSO users who match no group/role claim — otherwise, per upstream default, they're created with zero permissions until an admin grants access manually.

These patches were verified against a local test instance (self-signed test JWTs, no live IdP) — see commit `5857a57` ("fix: patch core_app OIDC auth bugs and add group/role-to-scope mapping") for the verification method if you need to re-check them against a future upstream version bump.

## Development tooling

This repo is built on the Self-Hosting-Template, which provides:

- **`environment.yml` / `requirements.txt`** — conda environment (Python, pip, `gh`) with Python deps installed via pip.
- **`pyproject.toml`** — [tox](https://tox.wiki) environments for linting and formatting:
  - `lint` — `ruff check`
  - `format` — `ruff format` + `ruff check --fix` + `prettier --write` + `taplo fmt`
  - `txt-lint` — [textlint](https://textlint.github.io/) over `**/*.txt`
  - `prettier` — `prettier --check` over CSS/JS/HTML/JSON/YAML/Markdown
  - `toml-lint` — `taplo` format/lint check over TOML files
  - `duplicate-code` — [jscpd](https://github.com/kucherenko/jscpd) zero-tolerance duplicate-code scan (config in `.jscpd.json`). Real duplication should be refactored into a shared file the callers source/import, not waved off by raising the threshold. `docker/webapp/patches/**` is excluded — those are full-file vendor copies kept close to upstream for patch clarity, not original project code.
  - `github` — the full read-only CI chain (`lint` + `txt-lint` + `prettier` + `toml-lint` + `duplicate-code`)
  - `all` — `format` then `github`
  - Also configures [git-cliff](https://git-cliff.org/) for generating changelogs/PR descriptions from Conventional Commits.
- **`package.json`** — `prettier` and `textlint` (+ plugins), installed on demand by the relevant tox envs.
- **`scripts/render_env_docs.py`** — renders `*.md.template` files, substituting `${VAR}` / `${VAR:-default}` / `${VAR:?message}` references (same syntax as `compose.yml`) from `.env`. Run it via `tox -e render-docs` or `make render-docs`. **Don't use this for docs that get committed if `.env` holds secrets** — either keep the rendered output gitignored, or only template non-sensitive values (domain, ports) and leave real secrets out of the template entirely.
- **`.github/workflows/`**
  - `tests.yml` — runs `tox -e github` on every push and PR.
  - `secret-detection.yml` — [TruffleHog](https://github.com/trufflesecurity/trufflehog) scan on every push and PR.
  - `duplicate-code.yml` — runs the jscpd duplicate-code check.
  - `release.yml` — on push to `main`, bumps semver based on Conventional Commit prefixes (`feat` → minor, `fix`/other → patch, `!`/`BREAKING CHANGE` → major) and publishes a GitHub Release with an auto-generated changelog.
- **`CODEOWNERS`** — defaults review ownership to `@Self-Host-Server/code-owners`.
- **`.gitignore`** — editor/AI-assistant artifacts (`.vscode`, `.cursor`, `CLAUDE.md`, etc.), `.env`, `node_modules`, `__pycache__`.

Run the full check locally before pushing:

```bash
pip install tox
tox -e github   # lint + txt-lint + prettier + toml-lint + duplicate-code
tox -e format   # auto-fix formatting issues
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the commit convention (Conventional Commits — it drives changelog generation and release versioning) and the local checks to run before opening a PR.
