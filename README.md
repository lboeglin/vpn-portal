# VPN Portal

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Build](https://img.shields.io/github/actions/workflow/status/<owner>/<repo>/deploy.yml?branch=main&label=build)

A self-hosted web portal for managing WireGuard VPN configurations. Administrators create user accounts; each user can log in to view, download, and scan their WireGuard config as a QR code. No command-line access required.

Built for Rocky Linux, deployable in minutes with Podman and Nginx.

---

## Screenshots

> _Screenshots coming soon._
>
> | Admin Dashboard | User Dashboard | QR Code |
> |---|---|---|
> | _(peer list, summary cards)_ | _(config viewer, download)_ | _(scannable WireGuard config)_ |

---

## Features

- **Admin portal**: create users and peers in one form; view all peers at a glance
- **User portal**: view WireGuard config, download `.conf` file, scan QR code
- **Automatic key generation**: X25519 keypairs generated server-side via the `cryptography` library (no `wg` subprocess)
- **Sequential IP assignment**: peers assigned the next available IP in the configured subnet
- **QR code generation**: server-side PNG rendered with `qrcode[pil]`
- **Rate-limited login**: brute-force protection via Flask-Limiter (10 req/min)
- **Dev mode**: full local development without a real WireGuard interface (`WG_DEV_MODE=true`)
- **Containerized**: Podman/Docker-compatible, auto-migrates the database on startup
- **CI/CD**: GitHub Actions builds and pushes to GHCR, then deploys to your VPS via SSH

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Framework | Flask 3.1, Flask-SQLAlchemy, Flask-Migrate |
| Auth & Security | Flask-Login, Flask-WTF (CSRF), Flask-Bcrypt, Flask-Limiter |
| Frontend | Jinja2 templates, Bootstrap 5.3 |
| Database | SQLite |
| WireGuard utilities | `cryptography` (key gen), `qrcode[pil]` (QR) |
| Production server | Gunicorn |
| Container runtime | Podman (Docker-compatible) |
| Reverse proxy | Nginx (TLS termination) |
| CI/CD | GitHub Actions → GitHub Container Registry → SSH deploy |

---

## Prerequisites

**Local development**
- Python 3.11+
- Git

**Production server**
- Rocky Linux 8/9 (or any RHEL-compatible distro)
- Podman 4.x + podman-compose
- WireGuard installed and `wg0` interface running
- Nginx
- A domain name with a valid TLS certificate (certbot recommended)

---

## Local Development

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/<your-org>/vpn-portal.git
cd vpn-portal
python3.11 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`. For local development the defaults work as-is; `WG_DEV_MODE=true` skips all real WireGuard calls.

```bash
# Minimum changes for local dev:
SECRET_KEY=any-random-string-here
WG_DEV_MODE=true
```

### 3. Initialise the database

```bash
export FLASK_APP=app
flask db upgrade
```

### 4. Seed the admin user

```bash
flask seed-admin
# Creates user 'admin' with password 'changeme'
# Override with ADMIN_USERNAME / ADMIN_PASSWORD in .env
```

### 5. Run the development server

```bash
flask run
# App available at http://127.0.0.1:5000
```

Log in at `/auth/login` with the admin credentials created above.

---

## Production Deployment

Ready for production? See the [Production Deployment Guide](docs/DEPLOYMENT.md) for step-by-step instructions covering GitHub Actions CI/CD, VPS setup, the WireGuard sync service, Nginx, and TLS.

---

## Environment Variables

All variables are read from `.env` via `python-dotenv`. See [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) for the full configuration reference.

---

## CI/CD

The GitHub Actions workflow (`.github/workflows/deploy.yml`) triggers on every push to `main`:

1. **Build**: builds the container image from `Containerfile` using Docker Buildx with layer caching from GHCR
2. **Push**: pushes two tags to GitHub Container Registry:
   - `ghcr.io/<owner>/<repo>:latest`
   - `ghcr.io/<owner>/<repo>:sha-<git-sha>`
3. **Deploy**: SSHes into the VPS, pulls the new image, and runs `podman-compose up -d --no-build`

**Required GitHub secrets** (repository Settings → Secrets → Actions):

| Secret | Value |
|---|---|
| `VPS_HOST` | Server IP or hostname |
| `VPS_USER` | SSH user on the server (e.g. `deploy`) |
| `VPS_SSH_KEY` | Private SSH key for that user |

---

## Roadmap

The current release is the MVP (Phase 1). Planned for Phase 2:

- **Traffic statistics**: display bytes sent/received and last handshake time per peer, polled live from `wg show`
- **Peer revocation**: admins can deactivate a peer; the sync service removes it from the live interface
- **Online status**: flag peers with a recent handshake (within the last 3 minutes) as online
- **Multi-peer per user**: allow each user to register more than one device
- **Audit log**: record who created or revoked which peer and when

---

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for project structure, code style, and how to open a pull request.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
