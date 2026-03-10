# VPN Portal

A self-hosted web portal for managing WireGuard VPN configurations. Administrators create user accounts; each user can log in to view, download, and scan their WireGuard config as a QR code — no command-line access required.

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

- **Admin portal** — create users and peers in one form; view all peers at a glance
- **User portal** — view WireGuard config, download `.conf` file, scan QR code
- **Automatic key generation** — X25519 keypairs generated server-side via the `cryptography` library (no `wg` subprocess)
- **Sequential IP assignment** — peers assigned the next available IP in the configured subnet
- **QR code generation** — server-side PNG rendered with `qrcode[pil]`
- **Rate-limited login** — brute-force protection via Flask-Limiter (10 req/min)
- **Dev mode** — full local development without a real WireGuard interface (`WG_DEV_MODE=true`)
- **Containerized** — Podman/Docker-compatible, auto-migrates the database on startup
- **CI/CD** — GitHub Actions builds and pushes to GHCR, then deploys to your VPS via SSH

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

Edit `.env`. For local development the defaults work as-is — `WG_DEV_MODE=true` skips all real WireGuard calls.

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

### Running tests

```bash
pytest
```

### Code quality

```bash
black .        # format
flake8         # lint
```

---

## Production Deployment

### 1. Prepare the server

```bash
# Install Podman and podman-compose
sudo dnf install -y podman
pip3 install podman-compose

# Ensure WireGuard is running
sudo systemctl enable --now wg-quick@wg0
sudo wg show wg0
```

### 2. Create the deploy directory and config

```bash
sudo mkdir -p /opt/vpn-portal
sudo chown deploy:deploy /opt/vpn-portal
cd /opt/vpn-portal

# Copy project files (or clone the repo)
cp .env.example .env
```

Edit `.env` for production:

```bash
FLASK_ENV=production
SECRET_KEY=<long-random-secret>
WG_DEV_MODE=false
WG_SERVER_PUBLIC_KEY=<output of: sudo wg show wg0 public key>
WG_SERVER_ENDPOINT=vpn.yourdomain.com:51820
WG_SUBNET=10.66.66.0/24
WG_SERVER_IP=10.66.66.1
```

### 3. Set up the host WireGuard sync service

The container writes peer configs to `/var/lib/vpn-portal/peers.conf`. A privileged host service watches that file and applies changes to the running `wg0` interface — keeping the container unprivileged.

```bash
# Shared directory (writable by the deploy user / container)
sudo mkdir -p /var/lib/vpn-portal
sudo chown deploy:deploy /var/lib/vpn-portal
sudo touch /var/lib/vpn-portal/peers.conf
sudo chown deploy:deploy /var/lib/vpn-portal/peers.conf

# Sync script
sudo tee /usr/local/bin/vpn-portal-wg-sync << 'EOF'
#!/bin/bash
set -e
PEERS_FILE="/var/lib/vpn-portal/peers.conf"
WG_CONF="/etc/wireguard/wg0.conf"
INTERFACE="wg0"

[ -s "$PEERS_FILE" ] || exit 0

wg addconf "$INTERFACE" "$PEERS_FILE"

sed -i '/^# BEGIN VPN PORTAL PEERS/,$d' "$WG_CONF"
printf '# BEGIN VPN PORTAL PEERS\n' >> "$WG_CONF"
cat "$PEERS_FILE" >> "$WG_CONF"

logger "vpn-portal: synced $(grep -c '^\[Peer\]' "$PEERS_FILE") peer(s) to $INTERFACE"
EOF
sudo chmod +x /usr/local/bin/vpn-portal-wg-sync

# systemd service unit
sudo tee /etc/systemd/system/vpn-portal-wg-sync.service << 'EOF'
[Unit]
Description=Apply VPN Portal WireGuard peer changes
After=wg-quick@wg0.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/vpn-portal-wg-sync
EOF

# systemd path unit — triggers on file change
sudo tee /etc/systemd/system/vpn-portal-wg-sync.path << 'EOF'
[Unit]
Description=Watch VPN Portal WireGuard peers config

[Path]
PathChanged=/var/lib/vpn-portal/peers.conf
Unit=vpn-portal-wg-sync.service

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now vpn-portal-wg-sync.path
```

### 4. Build and start the container

```bash
cd /opt/vpn-portal
podman build -t vpn-portal:latest .
podman-compose up -d

# Seed the admin user (first run only)
podman exec vpn-portal flask seed-admin
```

The container runs `flask db upgrade` automatically on startup. The app listens on `0.0.0.0:8000` (host network mode, only accessible via Nginx from outside).

### 5. Configure Nginx

```bash
sudo cp nginx.conf /etc/nginx/conf.d/vpn-portal.conf
# Replace the placeholder domain with your own
sudo sed -i 's/free-cities-hub.duckdns.org/vpn.yourdomain.com/g' \
    /etc/nginx/conf.d/vpn-portal.conf
```

### 6. Obtain a TLS certificate

```bash
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d vpn.yourdomain.com
sudo systemctl enable --now certbot-renew.timer
```

### 7. Start Nginx

```bash
sudo nginx -t && sudo systemctl enable --now nginx
```

The portal is now accessible at `https://vpn.yourdomain.com`.

---

## Environment Variables

All variables are read from `.env` via `python-dotenv`. `.env.example` is the source of truth.

| Variable | Default | Description |
|---|---|---|
| `FLASK_APP` | `app` | Flask application module |
| `FLASK_ENV` | `development` | `development`, `testing`, or `production` |
| `SECRET_KEY` | `change-me-to-a-random-secret-key` | Flask session signing key — **must be changed in production** |
| `DATABASE_URL` | `sqlite:///vpn_portal.db` | SQLAlchemy database URI |
| `WG_SERVER_PUBLIC_KEY` | _(empty)_ | Base64 public key of the WireGuard server |
| `WG_SERVER_ENDPOINT` | `vpn.example.com:51820` | Endpoint written into generated client configs |
| `WG_DNS` | `1.1.1.1` | DNS server written into generated client configs |
| `WG_SUBNET` | `10.0.0.0/24` | WireGuard subnet for peer IP allocation |
| `WG_SERVER_IP` | `10.0.0.1` | Server IP within the subnet (skipped during allocation) |
| `WG_INTERFACE` | `wg0` | WireGuard interface name |
| `WG_DEV_MODE` | `true` | When `true`, skips all WireGuard filesystem/subprocess calls |
| `RATELIMIT_STORAGE_URL` | `memory://` | Flask-Limiter backend (`memory://` or a Redis URL) |
| `ADMIN_USERNAME` | `admin` | Username created by `flask seed-admin` |
| `ADMIN_PASSWORD` | `changeme` | Password created by `flask seed-admin` — **change immediately** |

> In production, `DATABASE_URL` is overridden by `podman-compose.yml` to `sqlite:////data/vpn_portal.db`, persisted in a named Podman volume.

---

## CI/CD

The GitHub Actions workflow (`.github/workflows/deploy.yml`) triggers on every push to `main`:

1. **Build** — builds the container image from `Containerfile` using Docker Buildx with layer caching from GHCR
2. **Push** — pushes two tags to GitHub Container Registry:
   - `ghcr.io/<owner>/<repo>:latest`
   - `ghcr.io/<owner>/<repo>:sha-<git-sha>`
3. **Deploy** — SSHes into the VPS, pulls the new image, and runs `podman-compose up -d --no-build`

**Required GitHub secrets** (repository Settings → Secrets → Actions):

| Secret | Value |
|---|---|
| `VPS_HOST` | Server IP or hostname |
| `VPS_USER` | SSH user on the server (e.g. `deploy`) |
| `VPS_SSH_KEY` | Private SSH key for that user |

---

## Project Structure

```
vpn-portal/
├── app/
│   ├── __init__.py          # App factory (create_app), seed-admin CLI command
│   ├── models.py            # User, Peer SQLAlchemy models
│   ├── config.py            # DevelopmentConfig, TestingConfig, ProductionConfig
│   ├── extensions.py        # db, migrate, login_manager, bcrypt, limiter
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── forms.py         # LoginForm
│   │   └── routes.py        # /auth/login, /auth/logout
│   ├── admin/
│   │   ├── __init__.py
│   │   ├── forms.py         # CreateUserPeerForm
│   │   └── routes.py        # /admin/ dashboard, /admin/users/create
│   ├── user/
│   │   ├── __init__.py
│   │   └── routes.py        # /user/ dashboard, /user/download, /user/qr
│   ├── services/
│   │   └── wireguard.py     # Key gen, IP allocation, config gen, QR, peer sync
│   ├── templates/
│   │   ├── layout.html
│   │   ├── index.html
│   │   ├── auth/
│   │   ├── admin/
│   │   └── user/
│   └── static/
│       └── css/main.css
├── migrations/              # Flask-Migrate / Alembic migrations
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_wireguard.py
│   └── test_integration.py
├── .github/
│   └── workflows/
│       └── deploy.yml
├── Containerfile
├── entrypoint.sh            # Runs flask db upgrade then gunicorn
├── podman-compose.yml
├── nginx.conf
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## Contributing

1. Fork the repository and create a feature branch
2. Install dev dependencies: `pip install -r requirements-dev.txt`
3. Make your changes and add tests where appropriate
4. Run `black .` and `flake8` before committing
5. Run `pytest` to verify all tests pass
6. Open a pull request against `main`

---

## Roadmap

The current release is the MVP (Phase 1). Planned for Phase 2:

- **Traffic statistics** — display bytes sent/received and last handshake time per peer, polled live from `wg show`
- **Peer revocation** — admins can deactivate a peer; the sync service removes it from the live interface
- **Online status** — flag peers with a recent handshake (within the last 3 minutes) as online
- **Multi-peer per user** — allow each user to register more than one device
- **Audit log** — record who created or revoked which peer and when

---

## License

MIT License — see [LICENSE](LICENSE) for details.
