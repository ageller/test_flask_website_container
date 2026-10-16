# test_flask_website_container

A test of a workflow to build a Flask website within a container for deployment.

The app is a deliberately tiny survey (a form, a thanks page, a results page, and a health check). The point of this repo is the packaging around it: a production image, a Compose setup, and a rehearsed path from laptop to registry to VM. The workflow has three rungs:

| Rung | What you practice | Compose file(s) | URL |
|---|---|---|---|
| 1 | Fast inner loop: Flask with auto-reload in a dev container, source bind-mounted from the host | `docker-compose.dev.yml` | http://localhost:5000 |
| 2 | Production-like stack built locally: gunicorn (non-root) behind nginx | `docker-compose.yml` + `docker-compose.local.yml` | http://localhost:8080 |
| 3 | Registry rehearsal: push to GitHub Container Registry (GHCR), then pull and run that exact image | `docker-compose.yml` only | http://localhost:8080 |

The image and `docker-compose.yml` used in Rung 3 are exactly what a Linux VM will run later. Only `.env` (and the published port in it) changes.

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Rung 1: development stack with live reload](#2-rung-1-development-stack-with-live-reload)
3. [Rung 2: production-style stack built locally](#3-rung-2-production-style-stack-built-locally)
4. [What to look for in Rung 2](#4-what-to-look-for-in-rung-2)
5. [Creating GitHub tokens for GHCR](#5-creating-github-tokens-for-ghcr)
6. [Rung 3, manual path: push, then pull and run](#6-rung-3-manual-path-push-then-pull-and-run)
7. [Rung 3, CI path: GitHub Actions builds and pushes](#7-rung-3-ci-path-github-actions-builds-and-pushes)
8. [Rollback](#8-rollback)
9. [Moving to a VM](#9-moving-to-a-vm)
10. [Architecture note: WSL laptop to RHEL VM](#10-architecture-note-wsl-laptop-to-rhel-vm)
11. [Where this demo differs from a real project](#11-where-this-demo-differs-from-a-real-project)
12. [Troubleshooting](#12-troubleshooting)
13. [Reference](#13-reference)

---

## 1. Prerequisites

- **Docker Engine 25 or newer** (or Docker Desktop) with the **Compose plugin**, version 2.20 or newer. Check with:

  ```bash
  docker version --format '{{.Server.Version}}'
  docker compose version
  ```

  The command is `docker compose` (with a space). The old standalone `docker-compose` (v1) is not supported.
- **git**, **curl** (for the checks below), and **any editor**.
- A **GitHub account** for Rung 3.

You do not need Python on the host. Everything Python-related (the app, the tests, generating a secret key) runs inside containers.

Run every command in this README from the repository root (the folder that contains `docker-compose.yml`).

> **On WSL:** if `docker pull` or `docker compose up` fails with `error getting credentials ... docker-credential-desktop.exe`, see [Troubleshooting](#12-troubleshooting). It is a leftover setting from Docker Desktop and takes a minute to fix.

---

## 2. Rung 1: development stack with live reload

Rung 1 has **its own Compose file** (`docker-compose.dev.yml`), **its own Compose project** (`survey-demo-dev`), and **its own database volume** (`dev_data`). It never touches the `survey_data` volume used in Rungs 2 and 3, and it does not read `.env`.

It runs the `dev` image target: the same Python dependencies as production plus pytest, running as the same non-root user. Your `app/`, `wsgi.py`, and `tests/` folders are bind-mounted into the container, and Flask's development server runs with the reloader and debugger on.

### Start

```bash
docker compose -f docker-compose.dev.yml up --build
```

Open http://localhost:5000, fill in the form, and look at http://localhost:5000/results.

Press `Ctrl+C` to stop. (Add `-d` to run in the background, then follow the output with `docker compose -f docker-compose.dev.yml logs -f`.)

### See the live reload

With the stack running, edit a file under `app/` on the host:

1. **Template:** in `app/templates/form.html`, change the text of the `<h1>`. Refresh the browser: the new text appears immediately.
2. **Python:** in `app/routes.py`, change an error message such as `"Choose a language from the list."`. The terminal running the stack prints:

   ```
   * Detected change in '/app/app/routes.py', reloading
   * Restarting with stat
   ```

   Then the next request uses the new code.

The reloader checks file timestamps once a second ("stat" mode), so it works even when the repo lives on the Windows drive (`/mnt/c/...`) and you edit with a Windows editor.

> If you edit `wsgi.py` and the change does not show up, restart the stack. `wsgi.py` is mounted as a single file, and some editors save by replacing the file, which leaves the container looking at the old copy. Folders (`app/`, `tests/`) do not have this problem.

### Run the tests

```bash
docker compose -f docker-compose.dev.yml run --rm app pytest
```

This works whether or not the dev stack is already running. The tests use a temporary database, never the `dev_data` volume.

### Open a shell inside the dev container

```bash
docker compose -f docker-compose.dev.yml run --rm app sh
```

Try `id`, `pip list`, or `python -c "import flask; print(flask.__version__)"`. Type `exit` to leave.

### Reset the dev database

```bash
docker compose -f docker-compose.dev.yml down -v
```

`down` removes the container and network. `-v` also deletes the `dev_data` volume, so the next start begins with an empty database.

### Editor integration

- By default you edit files on the host with any editor. Flask and the other packages are installed only inside the container, so your editor may show unresolved imports and limited autocomplete for Flask. The app still runs fine.
- **Optional:** create a local virtual environment from `requirements-dev.txt` purely so the editor can resolve imports (for example `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`, then point your editor at `.venv`). This needs Python on the host. The app still runs in the container; `.venv` is ignored by git and Docker.
- **Optional:** attach VS Code to the running dev container (Dev Containers extension, command "Attach to Running Container...", pick `survey-demo-dev-app-1`) for full editor integration inside the container.
- A VS Code Dev Container (`devcontainer.json` reusing the `dev` target) could be added later. It is intentionally not part of this demo.

> **Security note:** the dev server publishes port 5000 and runs the Werkzeug debugger (protected by the PIN shown in the logs). That is fine on a laptop. Never run the dev stack on a shared or public machine.

---

## 3. Rung 2: production-style stack built locally

Rung 2 builds the `prod` image target from your working copy and runs it the way a server would: gunicorn with 2 workers as a non-root user, behind an nginx container. Only nginx publishes a port.

### Step 1: create `.env`

```bash
cp .env.example .env
```

`.env` holds configuration and the secret key. It is listed in `.gitignore` and `.dockerignore`, so it is never committed and never copied into an image.

### Step 2: set `IMAGE` to your real names, in lowercase

Open `.env` in your editor and replace the placeholders in this line:

```
IMAGE=ghcr.io/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME
```

Use your GitHub username and repository name **in lowercase**. For example, for `github.com/JaneDoe/My-Survey` write:

```
IMAGE=ghcr.io/janedoe/my-survey
```

Docker requires lowercase image names. If you leave the uppercase placeholder in place, Compose stops with:

```
invalid reference format: repository name (YOUR_GITHUB_USERNAME/YOUR_REPO_NAME) must be lowercase
```

Keep `IMAGE_TAG=local` for now. The image you build will be named `${IMAGE}:local`.

### Step 3: set a real `SECRET_KEY`

Generate a random key inside a container:

```bash
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output into `.env` as `SECRET_KEY=...`, or do both in one step:

```bash
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(docker run --rm python:3.12-slim python -c 'import secrets; print(secrets.token_hex(32))')/" .env
```

The app refuses to start in production mode if `SECRET_KEY` is missing or still `change-me`.

### Step 4: build and start

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d
```

Compose builds the `prod` image, tags it `${IMAGE}:${IMAGE_TAG}`, starts the app, waits for its health check to pass, and then starts nginx. Open http://localhost:8080.

Leave out `-d` if you want to watch the logs in the foreground (stop with `Ctrl+C`).

**Why two files?** `docker-compose.yml` only says "run this image". `docker-compose.local.yml` adds "and build it from source first". In Rung 3 and on the VM you drop the second file, so nothing is built and the image comes from the registry.

**Why not `docker-compose.override.yml`?** Compose automatically loads a file with that exact name. If the build override had that name, every plain `docker compose up` (including the Rung 3 rehearsal) would silently rebuild from source instead of using the registry image, and you would not notice.

### Everyday commands

After the stack is up, the shorter commands below are enough. `docker compose` with no `-f` reads `docker-compose.yml`, and both files share the fixed project name `survey-demo`, so these commands find the same containers.

```bash
docker compose ps                     # status and health of both containers
docker compose logs -f                # follow logs from app and nginx (Ctrl+C to stop following)
docker compose logs -f app            # just the app (gunicorn access log and errors)
curl -i http://localhost:8080/healthz # health through nginx: expect 200 {"status":"ok"}
docker inspect --format '{{.State.Health.Status}}' survey-demo-app-1   # container health check result
docker compose down                   # stop and remove containers; the database volume stays
docker compose down -v                # also delete the survey_data volume (resets the database)
```

After you change code, rebuild with the same command as Step 4.

> `docker compose down -v` deletes the same `survey_data` volume that Rung 3 uses, because Rungs 2 and 3 are the same Compose project.

---

## 4. What to look for in Rung 2

Work through these with the Rung 2 stack running.

1. **Only nginx publishes a port.** `docker compose ps` shows `8000/tcp` for the app (internal only) and `0.0.0.0:8080->80/tcp` for nginx.
2. **The app is not reachable directly.**

   ```bash
   curl -m 3 http://localhost:8000/healthz
   ```

   Expect `Connection refused`. The app is reachable only on the internal Compose network, where nginx calls it `app:8000`.
3. **Health works through nginx, and the container health check passes.**

   ```bash
   curl -i http://localhost:8080/healthz
   docker compose ps
   ```

   Expect `HTTP/1.1 200 OK` with `{"status":"ok"}`, and `(healthy)` next to the app. The `/healthz` route also runs `SELECT 1` against SQLite and returns `503` if the database is unreachable.
4. **The app runs as a non-root user and cannot change its own code.**

   ```bash
   docker compose exec app id
   docker compose exec app touch /app/wsgi.py
   ```

   Expect `uid=10001(app) gid=10001(app)` and `Permission denied`.
5. **The production image has no dev tooling.**

   ```bash
   docker compose exec app python -c "import pytest"
   docker compose exec app pip list
   ```

   Expect `ModuleNotFoundError: No module named 'pytest'`, and only Flask, gunicorn, their dependencies, and pip.
6. **No secrets are baked into the image.** The secret key reaches the container at run time from `.env`, not from the image:

   ```bash
   docker compose exec app ls -la /app
   docker image inspect "$(grep '^IMAGE=' .env | cut -d= -f2):local" --format '{{json .Config.Env}}'
   ```

   `/app` contains only `app/` and `wsgi.py`, and the image's environment has no `SECRET_KEY`.
7. **Data survives `down` and `up`, but not `down -v`.**

   ```bash
   # submit the form once at http://localhost:8080, then:
   docker compose down
   docker compose up -d
   # http://localhost:8080/results still shows the submission
   docker compose down -v
   docker compose up -d
   # http://localhost:8080/results now shows 0 submissions
   ```

8. **Production refuses a placeholder secret.** Set `SECRET_KEY=change-me` in `.env` and run `docker compose up -d`. Compose reports `dependency failed to start: container survey-demo-app-1 is unhealthy`, and `docker compose logs app` shows `RuntimeError: SECRET_KEY is missing or still set to the example placeholder`. Put your real key back afterwards.
9. **Proxy awareness (`TRUST_PROXY`).** Every page has a footer, "Request as seen by Flask". Compare:

   | | Client IP | X-Forwarded-For header | TRUST_PROXY |
   |---|---|---|---|
   | Rung 1 (Flask reached directly) | Docker's gateway, for example `172.18.0.1` | not sent | no |
   | Rung 2 (behind nginx, `TRUST_PROXY=1`) | the address nginx saw, for example `172.18.0.1` | set by nginx | yes |
   | Rung 2 with `TRUST_PROXY=0` | **nginx's own container address**, for example `172.18.0.3` | set by nginx, but ignored | no |

   To see the third row, set `TRUST_PROXY=0` in `.env`, run `docker compose up -d`, reload the page, and compare with `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' survey-demo-nginx-1`. Set it back to `1` afterwards. Without `ProxyFix`, every visitor looks like nginx. With it, Flask trusts exactly one proxy hop and sees the real client. On WSL the "real client" is Docker's gateway because of network address translation. On a VM it is the visitor's actual IP.

   The Host shows `localhost` without `:8080`, because nginx forwards `$host`, which has no port. Redirects in this app are relative, so that is harmless.

---

## 5. Creating GitHub tokens for GHCR

GHCR (GitHub Container Registry, `ghcr.io`) stores images next to your GitHub account. **Packages are private by default:** only accounts with access can pull them, so anything that pulls (including the VM) must log in.

GHCR accepts **classic** personal access tokens. Create two, with different powers:

| Token | Scope | Used on | Purpose |
|---|---|---|---|
| Laptop push token | `write:packages` (this also grants `read:packages`) | your laptop | push images in Rung 3 |
| VM pull token | `read:packages` only | each VM | pull images, nothing else |

Keeping them separate means a compromised VM cannot push a new image.

To create each token:

1. On GitHub, open your profile picture menu, then **Settings**, then **Developer settings**, then **Personal access tokens**, then **Tokens (classic)**.
2. Click **Generate new token**, then **Generate new token (classic)**.
3. Give it a descriptive note (for example `ghcr push from laptop` or `ghcr pull on survey VM`) and an expiration date.
4. Tick only the scope from the table above.
5. Click **Generate token** and copy it immediately. GitHub shows it only once. Store it in a password manager.

Never put a token in this repo, in `.env`, or in an image. `docker login` asks for it interactively.

---

## 6. Rung 3, manual path: push, then pull and run

You push the image you built in Rung 2, then run it using `docker-compose.yml` alone. That is exactly what the VM will do.

### Step 1: commit first

The image is tagged with the short git SHA, so commit your changes before tagging. Then the tag points at code that actually exists in git.

```bash
git status      # should report a clean working tree
```

If you changed code since the last Rung 2 build, rebuild first with `docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d`.

### Step 2: log in to GHCR

```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME
```

At the `Password:` prompt, paste your **laptop push token** (`write:packages`), not your GitHub password.

### Step 3: tag the local image with the short git SHA and push it

```bash
IMAGE=$(grep '^IMAGE=' .env | cut -d= -f2)
GIT_SHA=$(git rev-parse --short=7 HEAD)
echo "Will push $IMAGE:$GIT_SHA"

docker tag "$IMAGE:local" "$IMAGE:$GIT_SHA"
docker push "$IMAGE:$GIT_SHA"
```

The first push creates a private package. It appears on GitHub under your profile, in the **Packages** tab.

### Step 4: point `.env` at the registry image

Run steps 4 and 5 in the same terminal as step 3, because they use the `$IMAGE` and `$GIT_SHA` shell variables set there.

```bash
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$GIT_SHA/" .env
grep '^IMAGE' .env
```

### Step 5: delete the local copies, so the next step must pull

```bash
docker compose down
docker image rm "$IMAGE:$GIT_SHA" "$IMAGE:local"
```

### Step 6: pull and run with `docker-compose.yml` only

```bash
docker compose -f docker-compose.yml pull
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.yml ps
curl http://localhost:8080/healthz
```

Open http://localhost:8080. Some layers may report `Already exists` during the pull, because they are shared with `python:3.12-slim`, which you already have. That is normal.

Your Rung 2 submissions are still there, because Rungs 2 and 3 share the `survey-demo` project and its `survey_data` volume.

**This is the same command sequence the VM uses:** `docker login`, then `docker compose pull`, then `docker compose up -d`. The only differences on the VM are the values in its `.env` (its own `SECRET_KEY`, and `HTTP_PORT=80`).

---

## 7. Rung 3, CI path: GitHub Actions builds and pushes

`.github/workflows/build-and-push.yml` automates Rung 3's build and push. **It does nothing until you commit and push it to GitHub yourself:**

```bash
git add .
git commit -m "Add container workflow demo"
git push origin main
```

What the workflow does on each push to `main` (or when started by hand):

1. **test job:** sets up Python 3.12 on the GitHub runner, installs `requirements-dev.txt`, and runs `python -m pytest`. If a test fails, nothing is built.
2. **build-and-push job:**
   - logs in to `ghcr.io` with the workflow's built-in `GITHUB_TOKEN` (no personal token needed in CI; the workflow requests `packages: write`);
   - builds the `prod` target for `linux/amd64`;
   - names the image `ghcr.io/<owner>/<repo>`, lowercased;
   - tags it with the 7-character short SHA (for example `3f2c1ab`) and `latest`;
   - fills in the OCI labels (`source`, `revision`, `created`). The `source` label links the package to the repository on GitHub.

**Watch it run:** on GitHub, open the repository's **Actions** tab and select the `build-and-push` run. To start it by hand, choose **build-and-push** in the left sidebar, then **Run workflow**.

**Find the resulting tag:** the tag is the short SHA of the commit that triggered the run.

```bash
git rev-parse --short=7 HEAD     # on the commit you pushed
```

You can also find it on GitHub: on the repository page, find **Packages** in the right sidebar, open the package, and look at the list of recent tagged versions. The run's "Compute tags and labels" step also lists it.

Then deploy it on the laptop exactly as in [Rung 3, steps 4 to 6](#step-4-point-env-at-the-registry-image): set `IMAGE_TAG` to that SHA, then `pull` and `up -d`.

Notes:

- Use SHA tags in `.env`, not `latest`. A SHA says exactly which code is running, and it makes rollback a one-line change.
- If you pushed manually first, the package already exists and the workflow may fail with `403 Forbidden` or `permission_denied: write_package`. Fix: open the package on GitHub, then **Package settings**, then **Manage Actions access**, then add this repository with the **Write** role.
- To also build for ARM machines, follow the commented `linux/arm64` lines in the workflow.

---

## 8. Rollback

Every deployed version is a tag in GHCR, so rolling back means pointing `.env` at an older tag.

```bash
grep '^IMAGE_TAG' .env             # note the tag that is running now

# Find older tags: the package page on GitHub, or the images you have locally:
docker image ls "$(grep '^IMAGE=' .env | cut -d= -f2)"

# Pick the previous good tag and redeploy it (replace PREVIOUS_SHA):
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=PREVIOUS_SHA/" .env
docker compose -f docker-compose.yml pull
docker compose -f docker-compose.yml up -d
docker compose -f docker-compose.yml ps
```

Compose recreates only the app container. nginx is restarted with it, so it never keeps the old container's address. The `survey_data` volume is untouched.

Caveat: this demo has no database migrations. If a newer version had changed the table structure, the older code might not understand the data. Real projects keep migrations backwards compatible or roll the schema back as well.

---

## 9. Moving to a VM

The image does not change between laptop and VM. Only the host and the `.env` file do.

Checklist:

1. **Install Docker Engine and the Compose plugin** on the VM. For RHEL, see the commands in [section 10](#10-architecture-note-wsl-laptop-to-rhel-vm). Then check:

   ```bash
   docker compose version
   ```

2. **Log in to GHCR with the read-only token** (`read:packages`):

   ```bash
   docker login ghcr.io -u YOUR_GITHUB_USERNAME
   ```

3. **Copy the two deployment files** from your laptop. Nothing else is needed on the VM: no source code, no Dockerfile.

   ```bash
   ssh YOUR_VM_USER@YOUR_VM_ADDRESS 'mkdir -p ~/survey-demo/nginx'
   scp docker-compose.yml YOUR_VM_USER@YOUR_VM_ADDRESS:~/survey-demo/
   scp nginx/default.conf YOUR_VM_USER@YOUR_VM_ADDRESS:~/survey-demo/nginx/
   ```

4. **Create a VM-specific `.env`** on the VM. Do not copy the laptop's `.env`: generate a **new** secret key for every environment.

   ```bash
   cd ~/survey-demo
   cat > .env <<'EOF'
   SECRET_KEY=change-me
   FLASK_ENV=production
   DATABASE_PATH=/data/survey.db
   TRUST_PROXY=1
   IMAGE=ghcr.io/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME
   IMAGE_TAG=THE_SHORT_SHA_TO_DEPLOY
   HTTP_PORT=80
   EOF
   chmod 600 .env
   ```

   Then edit `.env` on the VM:
   - Replace `IMAGE` with your real names in lowercase, exactly as on the laptop.
   - Set `IMAGE_TAG` to the short SHA you want to deploy.
   - Set a new secret key, generated on the VM:

     ```bash
     sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env
     ```

   If you forget the key, the app refuses to start, rather than running with a guessable one.

5. **Pull and start:**

   ```bash
   docker compose pull && docker compose up -d
   docker compose ps
   curl http://localhost/healthz
   ```

   On the VM, `docker-compose.yml` is the only Compose file, so `-f` is not needed.

6. **Open the firewall for HTTP** (see section 10), then browse to `http://YOUR_VM_ADDRESS/` from your laptop.

`restart: unless-stopped` plus `systemctl enable docker` means the stack comes back by itself after a reboot.

What differs per environment, and what does not:

| Differs per environment | Same everywhere |
|---|---|
| `.env`: `SECRET_KEY`, `IMAGE_TAG`, `HTTP_PORT` (8080 on the laptop, 80 on the VM) | The image (same tag, same bytes) |
| Firewall: host firewall and the cloud or campus network rules | `docker-compose.yml` |
| DNS: a hostname pointing at the VM's address | `nginx/default.conf` (until you add TLS) |
| TLS: certificates and an HTTPS server block in nginx (see the comment in `nginx/default.conf`) | Variable names |
| Secrets: a file on disk here; a secrets manager in a real deployment | The data layout (`/data/survey.db` in a named volume) |

---

## 10. Architecture note: WSL laptop to RHEL VM

You develop on Windows with WSL (Ubuntu) and deploy to a VM running RHEL. Nothing in the image or `docker-compose.yml` has to change, but these points matter.

**CPU architecture.** Most laptops and most RHEL VMs are `x86_64`, which matches the `linux/amd64` images built here. Check on the VM with `uname -m`. If it prints `aarch64` (an ARM VM, for example AWS Graviton), build for `linux/arm64` as well (see the commented lines in the CI workflow). Otherwise the container fails with `exec format error`.

**Docker Engine on RHEL.** RHEL ships Podman, not Docker. This demo uses Docker Engine from Docker's own RHEL repository, so the commands are the same as on the laptop. On RHEL 8 or 9 (check [docs.docker.com/engine/install/rhel](https://docs.docker.com/engine/install/rhel/) for your version):

```bash
# Docker's packages conflict with RHEL's podman and runc. Only remove them if nothing else on the VM needs them.
sudo dnf remove -y podman runc
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"    # then log out and back in to use docker without sudo
```

Some institutional VMs do not allow third-party repositories, or require Podman. Ask your VM administrator first. Podman can run most of this setup (`podman compose`), but it is not what this demo was tested with: rootless Podman cannot publish port 80 without extra configuration, and some Compose features behave differently.

**SELinux.** RHEL runs SELinux in enforcing mode, which can block containers from reading files on the host. The nginx config mount in `docker-compose.yml` ends in `:ro,z`. The `z` tells Docker to give the file a label that containers may read. WSL and Ubuntu do not use SELinux and ignore the flag, so the same file works on both. The database lives in a named volume, which needs no labelling. If nginx ever logs `Permission denied` for `default.conf`, SELinux is the first suspect.

**firewalld.** RHEL's host firewall blocks port 80 by default:

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

Cloud VMs also have a network-level firewall (a security group or similar) that must allow port 80. Be aware that Docker manages its own firewall rules for published ports, and those rules can bypass firewalld. Treat any port published in `docker-compose.yml` as public, which is why only nginx publishes one.

**Where the repo lives on WSL.** This repo can live on the Windows drive (`/mnt/c/...`), and everything works there. File access across the Windows/Linux boundary is slower, though. For faster builds and reloads, clone the repo into your WSL home directory (for example `~/projects/`). You can still edit it from Windows (VS Code's WSL extension, or `\\wsl$\` in Explorer).

**Line endings.** Keep files with Unix (LF) line endings. Cloning and committing from inside WSL, with `git config --global core.autocrlf input`, does this. The files here tolerate Windows (CRLF) line endings, but scripts you add later may not.

**Reaching the app from Windows.** WSL forwards `localhost` ports to Windows, so a Windows browser can open http://localhost:5000 and http://localhost:8080.

**User IDs.** The app runs as UID 10001 on every host. Data is kept in a named volume, not a host folder, so there is no host user to match on either WSL or RHEL.

---

## 11. Where this demo differs from a real project

- **Database:** SQLite in a Docker volume on one host. A real project would use a managed database (for example PostgreSQL run by a cloud provider or central IT), or send responses to an API such as REDCap, to get backups, access control, and audit trails.
- **No TLS:** plain HTTP only. A real deployment terminates HTTPS in nginx (or a load balancer) with real certificates. See the comment in `nginx/default.conf`.
- **No authentication:** anyone who can reach the site can see `/results`.
- **No migrations:** the table is created once with `CREATE TABLE IF NOT EXISTS`. Changing its structure later needs a migration tool or hand-written migration scripts.
- **No secrets manager:** the secret key sits in a plain `.env` file on each host. Real deployments use a secrets manager or the platform's secret store, and rotate keys.
- **No backups or monitoring:** nothing backs up the `survey_data` volume, and logs go only to `docker compose logs`.
- **Single host:** one VM, one app container, no load balancing or zero-downtime deploys.
- **Minimal CSRF:** a hand-rolled session token is enough for one form. A bigger app would use a maintained library such as Flask-WTF.

---

## 12. Troubleshooting

**`error getting credentials - err: exec: "docker-credential-desktop.exe": executable file not found in $PATH`**
Your `~/.docker/config.json` still points at Docker Desktop's credential helper, but Docker Desktop is not installed or not reachable from WSL. Back up the file and remove the `"credsStore"` line:

```bash
cat ~/.docker/config.json
cp ~/.docker/config.json ~/.docker/config.json.bak
```

If the file contains nothing but `{"credsStore": "desktop.exe"}`, reset it with `echo '{}' > ~/.docker/config.json`. Otherwise delete just the `"credsStore"` line in an editor, keeping the JSON valid. Without a credential helper, `docker login` stores your token in that file, base64-encoded but not encrypted. Run `docker logout ghcr.io` when you no longer need it.

**`repository name (...) must be lowercase`**
`IMAGE` in `.env` still contains the uppercase placeholder or uppercase letters. See [Rung 2, step 2](#step-2-set-image-to-your-real-names-in-lowercase).

**`required variable IMAGE is missing a value`**
There is no `.env` file next to `docker-compose.yml`. Run `cp .env.example .env` and edit it.

**`dependency failed to start: container survey-demo-app-1 is unhealthy`**
The app did not start. Run `docker compose logs app`. The most common cause is `SECRET_KEY` missing or still `change-me`.

**`Bind for 0.0.0.0:8080 failed: port is already allocated`** (or 5000)
Something else is using the port. Stop it, or change `HTTP_PORT` in `.env` (Rung 2 and 3). For Rung 1, edit the `ports:` line in `docker-compose.dev.yml`.

**nginx returns `502 Bad Gateway`**
nginx is up but cannot reach the app. Check `docker compose ps` and `docker compose logs app`.

**`denied` or `unauthorized` on `docker push` or `docker pull`**
Log in again with `docker login ghcr.io -u YOUR_GITHUB_USERNAME`. Check the token's scope (`write:packages` to push, `read:packages` to pull), and that `IMAGE` matches your username and repository exactly, in lowercase.

**Edits are not picked up in Rung 1**
Check the Rung 1 output for `Detected change in ...`. For `wsgi.py`, restart the stack (see the note in Rung 1). Changes to `requirements*.txt` or the `Dockerfile` need a rebuild: `docker compose -f docker-compose.dev.yml up --build`.

---

## 13. Reference

### Configuration (`.env`)

| Variable | Example | Meaning |
|---|---|---|
| `SECRET_KEY` | 64 random hex characters | Signs the session cookie that carries the CSRF token. Required in production; `change-me` is rejected. |
| `FLASK_ENV` | `production` | Anything other than `development` enables the strict `SECRET_KEY` check. |
| `DATABASE_PATH` | `/data/survey.db` | SQLite file location. `/data` is the named volume. Bare local runs default to `./instance/survey.db`. |
| `TRUST_PROXY` | `1` | `1` trusts one hop of `X-Forwarded-*` headers (behind nginx). Use `0` when Flask is reached directly. |
| `IMAGE` | `ghcr.io/janedoe/my-survey` | Image name, lowercase. |
| `IMAGE_TAG` | `local` or a short SHA | `local` for images built in Rung 2, a git SHA for registry images. |
| `HTTP_PORT` | `8080` | Host port nginx publishes. `8080` on the laptop, `80` on a VM. |

Rung 1 does not read `.env`; its settings are in `docker-compose.dev.yml`.

### Names Compose creates

| | Rung 1 | Rungs 2 and 3 |
|---|---|---|
| Project | `survey-demo-dev` | `survey-demo` |
| Containers | `survey-demo-dev-app-1` | `survey-demo-app-1`, `survey-demo-nginx-1` |
| Database volume | `survey-demo-dev_dev_data` | `survey-demo_survey_data` |

The project names are fixed with `name:` at the top of each Compose file. Without them, both stacks would be named after the folder and their `app` containers would collide. On the VM, the volume name also stays the same whatever folder you deploy into.

### Files

| Path | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build: `builder` (venv with runtime deps), `dev` (adds pytest), `prod` (final stage, the default). |
| `docker-compose.yml` | Production-style stack: `app` (image from `.env`) and `nginx`. Used in Rungs 2 and 3 and on the VM. |
| `docker-compose.local.yml` | Rung 2 override that builds the `prod` target from source. |
| `docker-compose.dev.yml` | Rung 1 standalone dev stack with live reload. |
| `nginx/default.conf` | Reverse proxy to `app:8000`, with commented WebSocket and TLS notes. |
| `app/__init__.py` | App factory: reads configuration, checks `SECRET_KEY`, enables `ProxyFix`, initializes the database. |
| `app/db.py`, `app/schema.sql` | SQLite connection per request, WAL mode, idempotent schema. |
| `app/routes.py` | Form, validation, CSRF, results summary, `/healthz`. |
| `app/templates/`, `app/static/` | Jinja templates and one CSS file. |
| `wsgi.py` | Entry point for gunicorn (`wsgi:app`) and `flask --app wsgi`. |
| `tests/test_app.py` | pytest suite (run in the dev container). |
| `.github/workflows/build-and-push.yml` | CI: test, then build and push to GHCR. |
| `requirements.txt`, `requirements-dev.txt` | Exact-pinned runtime and dev dependencies. |
| `.env.example` | Template for `.env`. The real `.env` is never committed. |

### Routes

| Route | Purpose |
|---|---|
| `GET /` | Survey form |
| `POST /` | Validate and save, then redirect to `/thanks` (POST/redirect/GET) |
| `GET /thanks` | Confirmation page |
| `GET /results` | Totals, counts per answer, and the 10 most recent submissions |
| `GET /healthz` | `200 {"status": "ok"}` if the database answers `SELECT 1`, otherwise `503` |

### Pinned versions

Python 3.12 (`python:3.12-slim`), Flask 3.1.3, gunicorn 26.2.0, pytest 9.1.1, nginx 1.30 (`nginx:1.30-alpine`, the current stable series). To upgrade, change the pins, rebuild, and run the tests.
