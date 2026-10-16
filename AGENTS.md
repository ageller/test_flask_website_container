# AGENTS.md

Instructions for Claude Code (or any coding agent) building the **container workflow demo**.

## 1. Purpose

Build a small Flask app whose real job is to let the owner rehearse a container deployment workflow end to end. The app itself is intentionally trivial. The value is in the packaging, the Compose setup, and the documentation.

The owner will use the result to practice three stages:

- **Rung 1:** Fast inner loop. Run Flask with auto-reload inside a development container started by Docker Compose, with the source bind-mounted so edits made on the host appear immediately.
- **Rung 2:** Production-like stack built locally. Production image (gunicorn, non-root) behind an nginx container, using Docker Compose, viewed at `http://localhost:8080`.
- **Rung 3:** Registry rehearsal. Push an image to GitHub Container Registry (GHCR), then pull and run that exact image on the same laptop using the same Compose file a VM would use.

The same image and the same Compose file must later work unchanged on a Linux VM (local or cloud). Only the `.env` file and the host's published port should differ.

## 2. Hard rules

1. **Do not run any git commit, git push, git tag, or any command that writes to a remote.** Local file creation is fine. Do not create or modify anything under `.git/`.
2. **Do not push images to any registry.** Do not run `docker push` or `docker login`. Document those steps in the README for the owner to run.
3. **Do not run `docker login`, and never embed or request tokens.** Use placeholders such as `YOUR_GITHUB_USERNAME` and `YOUR_REPO_NAME`.
4. **No secrets in the repo or in images.** Provide `.env.example` only. Add `.env` to `.gitignore` and `.dockerignore`.
5. **If you need anything installed on the host machine, ask the owner.** You should not install.  Provide instructions to the owner to run the installation.  All Python tooling runs inside containers.
6. **Keep the app small.** If a choice is between simple and clever, choose simple. Do not add frameworks, ORMs, front-end build tooling, or authentication.
7. Writing GitHub Actions workflow files locally is allowed (see section 10), but do not trigger or run them.
8. **Do not use em-dashes** in any documentation or comments you write. Use commas, colons, parentheses, or separate sentences.

If something in these instructions is ambiguous or seems wrong, stop and ask the owner rather than guessing.

## 3. Stack

| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| Web framework | Flask |
| Production server | gunicorn (2 workers, sync) |
| Database | SQLite via the standard library `sqlite3` module (no ORM) |
| Reverse proxy | nginx (official image, config mounted from the repo) |
| Orchestration | Docker Compose v2 |
| Templates | Jinja2, plain HTML and a small CSS file, no JavaScript framework |
| Tests | pytest |
| Dev environment | Docker Compose dev file (`dev` image target, bind-mounted source, Flask reloader) |

Pin all Python dependencies to exact versions in `requirements.txt` (runtime) and `requirements-dev.txt` (adds pytest and similar). Pin base images to a specific minor version tag (for example `python:3.12-slim`, `nginx:1.27-alpine`), not `latest`.

## 4. Repository layout

Create this structure:

```
.
├── AGENTS.md
├── README.md
├── .env.example
├── .gitignore
├── .dockerignore
├── Dockerfile
├── docker-compose.yml            # production-style stack, image-based
├── docker-compose.local.yml      # override: build locally instead of pulling
├── docker-compose.dev.yml        # Rung 1: standalone dev stack with live reload
├── requirements.txt
├── requirements-dev.txt
├── .github/
│   └── workflows/
│       └── build-and-push.yml    # written but never run by you
├── nginx/
│   └── default.conf
├── app/
│   ├── __init__.py               # app factory
│   ├── db.py
│   ├── routes.py
│   ├── schema.sql
│   ├── templates/
│   │   ├── base.html
│   │   ├── form.html
│   │   ├── thanks.html
│   │   └── results.html
│   └── static/
│       └── style.css
├── wsgi.py                       # gunicorn entry point
└── tests/
    └── test_app.py
```

## 5. Application requirements

### Routes

- `GET /` shows the survey form.
- `POST /` validates and saves a submission, then redirects (POST/redirect/GET) to `/thanks`.
- `GET /thanks` shows a confirmation page.
- `GET /results` shows a simple summary: total submission count, a count per answer for the multiple-choice questions, and a table of the 10 most recent submissions (timestamp, name or "anonymous", and answers).
- `GET /healthz` returns `200` and JSON `{"status": "ok"}`. It should also confirm the database is reachable (run `SELECT 1`) and return `503` if not.

### Form questions

Use these (generic and harmless):

1. **Name** (optional text, max 80 characters)
2. **Primary language you use at work** (single select: Python, R, Julia, JavaScript, Other)
3. **Experience with containers** (radio, 1 to 5, where 1 is "never used" and 5 is "use daily")
4. **Which environments do you deploy to?** (checkboxes: Laptop, Local server, AWS, Azure, Other)
5. **Comments** (optional textarea, max 500 characters)

### Validation and security basics

- Validate server-side. Reject unknown select values, out-of-range ratings, and oversize text. Re-render the form with error messages and keep the user's input.
- Use parameterized SQL queries only. Never build SQL with string formatting.
- Jinja autoescaping must stay on.
- Add CSRF protection. A simple approach is fine: generate a token stored in the Flask session, include it as a hidden field, and verify it on POST. `Flask-WTF` is acceptable if you prefer, but keep dependencies minimal.
- `SECRET_KEY` comes from the environment. The app must refuse to start in production mode if `SECRET_KEY` is missing or equal to the example placeholder.

### Proxy awareness

When `TRUST_PROXY=1`, wrap the app with `werkzeug.middleware.proxy_fix.ProxyFix` (trust one hop for `x_for`, `x_proto`, `x_host`, `x_prefix`). When running directly with `flask run`, this stays off. This is a deliberate teaching point: the owner wants to see the difference between Rung 1 and Rung 2.

## 6. Database requirements

- SQLite file lives at the path in `DATABASE_PATH` (default `/data/survey.db` in containers, `./instance/survey.db` for bare local runs).
- `app/schema.sql` creates the table if it does not exist. Run it at startup via the app factory, idempotently.
- Table `submissions`: `id` (integer primary key), `created_at` (UTC ISO 8601 text), `name`, `language`, `container_experience` (integer), `environments` (comma-separated text or JSON text), `comments`.
- On every connection set `PRAGMA journal_mode=WAL;`, `PRAGMA busy_timeout=5000;`, and `PRAGMA foreign_keys=ON;`. This keeps two gunicorn workers from tripping over each other.
- Open a connection per request and close it at teardown (Flask `g` pattern). Do not share connections across threads or workers.
- Add a short comment in `db.py` explaining why SQLite is acceptable for this demo (single host, low write volume) and what would change for a real project (a managed database, or an API such as REDCap).

## 7. Configuration

All configuration comes from environment variables. Provide `.env.example` with:

```
# Required
SECRET_KEY=change-me

# App
FLASK_ENV=production
DATABASE_PATH=/data/survey.db
TRUST_PROXY=1

# Compose
IMAGE=ghcr.io/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME
IMAGE_TAG=local
HTTP_PORT=8080
```

Notes:

- `IMAGE` and `IMAGE_TAG` let the same Compose file run a locally built image (`local`) or a registry image pinned to a git SHA.
- `HTTP_PORT` is the host port nginx publishes. Locally it is 8080. On a VM it would be 80.
- Use the same variable names in every environment.
- Document how to generate a secret key in the README (for example `python -c "import secrets; print(secrets.token_hex(32))"` run inside the container).

## 8. Docker requirements

### Dockerfile

Use a multi-stage build:

- **Builder stage:** install dependencies into a virtual environment (or wheel cache) from `requirements.txt`.
- **Runtime stage:** copy only the virtual environment and the app. Final image should be `python:3.12-slim` based.
- Create a non-root user with a fixed UID (for example 10001). Run as that user.
- Create `/data` in the image, owned by that user, so a named volume mounted there inherits correct ownership.
- Set `PYTHONUNBUFFERED=1` and `PYTHONDONTWRITEBYTECODE=1`.
- `EXPOSE 8000`. Start with gunicorn: `gunicorn --bind 0.0.0.0:8000 --workers 2 --access-logfile - --error-logfile - wsgi:app`.
- Add a `HEALTHCHECK` that calls `/healthz` using Python's standard library (do not add curl just for this).
- Add OCI labels (`org.opencontainers.image.source`, `.revision`, `.created`) populated by build args, defaulting to empty values.
- Define two named targets from the same base and the same `requirements.txt`: `dev` (adds `requirements-dev.txt`, runs as the same non-root user, used only by `docker-compose.dev.yml`) and `prod` (no dev tooling, no tests). Make `prod` the last stage in the Dockerfile so that a plain `docker build` produces it. The `prod` image must not contain pytest or any other dev dependency.

### docker-compose.yml (production-style, image-based)

Services:

- `app`: `image: ${IMAGE}:${IMAGE_TAG}`, `env_file: .env`, volume `survey_data:/data`, no published ports, `restart: unless-stopped`, healthcheck inherited from the image.
- `nginx`: official nginx image, mounts `./nginx/default.conf` read-only, publishes `${HTTP_PORT}:80`, `depends_on` the app being healthy, `restart: unless-stopped`.
- Named volume `survey_data`.
- Only nginx publishes a port. The app is reachable only on the internal Compose network.

### docker-compose.local.yml (override)

Adds a `build:` section to `app` (context `.`, `target: prod`) so that `docker compose -f docker-compose.yml -f docker-compose.local.yml up --build` builds from source. Do not name this file `docker-compose.override.yml`, because Compose would load that automatically and silently break the Rung 3 rehearsal. Document this in the README.

### nginx/default.conf

- Proxy `/` to `http://app:8000`.
- Set `Host`, `X-Real-IP`, `X-Forwarded-For`, and `X-Forwarded-Proto` headers.
- `server_name _;` so it works with `localhost` and any VM hostname.
- Reasonable timeouts and `client_max_body_size 1m`.
- Include a short commented block showing the extra headers and longer timeouts that WebSocket apps (such as Shiny) would need, left commented out. This is for the owner's future reference.
- Plain HTTP only. Add a comment noting where TLS would be added on a real VM.

### .dockerignore

Exclude `.git`, `.env`, `__pycache__`, `instance/`, tests, and docs from the build context. (In the dev stack, source and tests are bind-mounted rather than copied.)

## 9. Development stack (Rung 1)

There is no VS Code dev container in this project. Rung 1 uses Docker Compose, so the owner has one workflow from laptop to VM and can use any editor.

Create `docker-compose.dev.yml` as a **standalone** file (do not layer it on `docker-compose.yml`). It defines a single service, `app`:

- `build`: context `.`, `target: dev`.
- `command`: `flask --app wsgi run --debug --host 0.0.0.0 --port 5000`, so the reloader is on.
- `ports`: `5000:5000`. In dev the app is published directly and nginx is not used.
- `volumes`: bind-mount `./app`, `./wsgi.py`, and `./tests` into the paths the Dockerfile uses for the application, so host edits are visible inside the container. Add a named volume `dev_data` mounted at `/data`. This is deliberately separate from the `survey_data` volume used in Rungs 2 and 3, so the databases never mix.
- `environment` (set directly in the file, not read from `.env`): `FLASK_ENV=development`, `DATABASE_PATH=/data/survey.db`, `TRUST_PROXY=0`, and `SECRET_KEY=dev-only-not-a-secret`. Add a comment that this key is for local development only and must never be reused.

Usage the README must document:

- Start: `docker compose -f docker-compose.dev.yml up --build`, then browse to `http://localhost:5000`.
- Tests: `docker compose -f docker-compose.dev.yml run --rm app pytest`.
- Shell inside the container: `docker compose -f docker-compose.dev.yml run --rm app sh`.
- Reset the dev database: `docker compose -f docker-compose.dev.yml down -v`.

Editor integration (document briefly in the README, do not build anything for it):

- By default the owner edits files on the host with any editor. The editor will not see packages installed inside the container, so autocomplete for Flask may be limited.
- Optional: create a local virtual environment from `requirements-dev.txt` purely so the editor can resolve imports. The app still runs in the container.
- Optional: attach VS Code to the running dev container for full editor integration.
- A VS Code Dev Container could be added later as a thin `devcontainer.json` that reuses the `dev` target. Do not create one now.

## 10. CI workflow (write only, do not run)

Create `.github/workflows/build-and-push.yml`:

- Triggers on push to `main` and on manual dispatch.
- Uses `actions/checkout`, `docker/setup-buildx-action`, `docker/login-action` (registry `ghcr.io`, username `${{ github.actor }}`, password `${{ secrets.GITHUB_TOKEN }}`), `docker/metadata-action`, and `docker/build-push-action`.
- Needs `permissions: contents: read, packages: write`.
- Builds the `prod` target for `linux/amd64`. Include a commented line showing how to add `linux/arm64`.
- Tags the image with the git SHA (short) and `latest`.
- Runs `pytest` before building, if that is straightforward. Otherwise leave a clear TODO.
- Image name derived from `${{ github.repository }}`, lowercased.

Remind the owner in the README that this file does nothing until it is committed and pushed by them.

## 11. Tests

Write a small pytest suite in `tests/test_app.py` using Flask's test client and a temporary database:

- `/healthz` returns 200.
- A valid submission is saved and redirects to `/thanks`.
- Invalid submissions (bad language value, rating out of range, oversize comment, missing CSRF token) are rejected and nothing is saved.
- `/results` renders and shows the saved submission.
- The app refuses to start in production mode with a missing or placeholder `SECRET_KEY`.

Run the tests with `docker compose -f docker-compose.dev.yml run --rm app pytest`. Never run them on the bare host.

## 12. README requirements

The README is the main deliverable besides the code. Write it for someone who is comfortable with Docker but has never deployed a container to a cloud or VM. It must include step-by-step instructions, with copy-pasteable commands, for each of the following. Use `YOUR_GITHUB_USERNAME` and `YOUR_REPO_NAME` as placeholders.

1. **Prerequisites** (Docker with Compose v2, and any editor).
2. **Rung 1:** start the dev stack with `docker compose -f docker-compose.dev.yml up --build`, browse at `http://localhost:5000`, and show that editing a file under `app/` on the host reloads the app. Include how to run tests, open a shell in the container, and reset the dev database volume. State that Rung 1 has its own Compose file and its own database volume, separate from Rungs 2 and 3. Include the short note on editor integration from section 9.
3. **Rung 2:** create `.env` from `.env.example`, then build and run the production-style stack locally with `docker compose -f docker-compose.yml -f docker-compose.local.yml up --build`. View it at `http://localhost:8080`. Show how to check logs, check health, stop the stack, and reset the database volume.
4. **A short "what to look for" list for Rung 2:** for example, confirm the app is not reachable directly on port 8000, confirm `/healthz`, confirm the container runs as non-root, confirm data survives `docker compose down` and `up` but not `down -v`.
5. **Creating a GitHub personal access token** for GHCR (classic token with `write:packages` for pushing from the laptop, and a separate read-only `read:packages` token for pulling on a VM). Explain that GHCR packages are private by default.
6. **Rung 3, manual path:** log in to GHCR, tag the locally built image with a short git SHA, push it, then set `IMAGE` and `IMAGE_TAG` in `.env`, run `docker compose pull` and `docker compose up -d` using only `docker-compose.yml`, and confirm it works at localhost. Explain that this is the same command sequence the VM will use.
7. **Rung 3, CI path:** how the included GitHub Actions workflow would do the build and push, and how to find the resulting tag.
8. **Rollback:** how to redeploy a previous tag.
9. **Moving to a VM:** a short checklist (install Docker Engine and Compose plugin, create a read-only GHCR token and `docker login`, copy `docker-compose.yml`, `nginx/default.conf`, and a VM-specific `.env`, set `HTTP_PORT=80`, `docker compose pull && docker compose up -d`). Note what differs per environment (firewall, DNS, TLS, secrets) and that the image does not change.
10. **Architecture note:** the owner will develop on Windows WSL and deploy to a VM running RHEL.  If any differences in setup are needed, explain here.
11. **Where this demo differs from a real project:** SQLite versus a managed database or REDCap API, no TLS, no auth, no migrations, no secrets manager.

## 13. Working method for the agent

1. Read this whole file first.
2. Plan the work briefly, then build the files in the order of section 4.
3. Build and run the stack to verify it, using only local Docker commands (`build`, `compose up`, `compose down`, `exec`, `logs`). Do not push or log in anywhere.
4. Run the tests in a container.
5. At the end, report: what was built, what was verified and how, anything you could not verify, and the exact commands the owner should run for each rung.

## 14. Acceptance checklist

The work is done when all of these are true:

- [ ] `docker compose -f docker-compose.dev.yml up --build` starts the dev stack at `http://localhost:5000`, and editing a file under `app/` on the host reloads the app.
- [ ] `docker compose -f docker-compose.yml -f docker-compose.local.yml up --build` starts the production-style stack, and the form works at `http://localhost:8080`.
- [ ] A submission is saved and appears on `/results`.
- [ ] Data persists across `docker compose down` followed by `up`.
- [ ] Port 8000 is not reachable from the host. Only nginx is published.
- [ ] `/healthz` works through nginx, and the container healthcheck reports healthy.
- [ ] The app container runs as a non-root user.
- [ ] Running `docker compose -f docker-compose.yml up -d` (no override) with `IMAGE` and `IMAGE_TAG` pointing at a local image tag works, proving the Rung 3 path.
- [ ] Tests pass when run with `docker compose -f docker-compose.dev.yml run --rm app pytest`.
- [ ] The `prod` image does not contain pytest or other dev dependencies.
- [ ] No secrets, tokens, or `.env` file are present in the repo or the image.
- [ ] Nothing was committed, pushed, or logged in to anywhere.
- [ ] The README covers every item in section 12.
