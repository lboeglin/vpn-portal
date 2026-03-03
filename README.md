# WireGuard VPN Portal

A self-hosted web application for managing WireGuard VPN peer configurations.
Administrators create user accounts and generate peer configs through a browser UI.
Users log in, download their `.conf` file, or scan a QR code to import it directly
into the WireGuard app on any device.

## Why

Managing WireGuard on a VPS usually means editing config files by hand, running
`wg` commands as root, and distributing keys out-of-band. This becomes fragile as
the number of peers grows. This portal replaces that workflow with a small,
auditable web app that handles key generation, IP allocation, config rendering,
and interface synchronisation — while staying close to the metal (no Kubernetes,
no external dependencies beyond a single SQLite file).

## Features

- Admin creates a user account and a WireGuard peer in a single form
- Sequential IP allocation within a configurable subnet
- Keys generated server-side using X25519 via the `cryptography` library (no `wg` subprocess for key gen)
- Per-user dashboard showing the full client config, a download link, and a QR code
- Live interface sync: new peers are applied to the running `wg0` interface and written to `wg0.conf` atomically via `wg syncconf`
- Rate-limited login (10 requests per minute per IP)
- CSRF protection on all forms (Flask-WTF)
- `WG_DEV_MODE` flag stubs all OS-level calls for local development without root

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Framework | Flask 3.1, Gunicorn |
| Database | SQLite via SQLAlchemy 2.0 + Flask-Migrate |
| Auth | Flask-Login, Flask-Bcrypt |
| Forms | Flask-WTF |
| Rate limiting | Flask-Limiter |
| Crypto | `cryptography` (X25519 key pairs) |
| QR codes | `qrcode[pil]` |
| Frontend | Jinja2 templates, Bootstrap 5.3 |
| Container | Podman / Docker (OCI-compatible `Containerfile`) |
| Reverse proxy | Nginx (TLS termination, security headers) |
| CI/CD | GitHub Actions — build image, push to GHCR, deploy via SSH |

## Project Structure

```
vpn-portal/
├── app/
│   ├── __init__.py          # App factory (create_app)
│   ├── config.py            # DevelopmentConfig, TestingConfig, ProductionConfig
│   ├── extensions.py        # db, migrate, login_manager, bcrypt, limiter
│   ├── models.py            # User, Peer models
│   ├── auth/                # Blueprint: /auth/login, /auth/logout
│   ├── admin/               # Blueprint: dashboard, create user+peer
│   ├── user/                # Blueprint: dashboard, download config, QR code
│   ├── services/
│   │   └── wireguard.py     # Key gen, config rendering, interface management
│   ├── templates/
│   └── static/
├── tests/
│   ├── conftest.py
│   ├── test_integration.py  # Full flow integration tests
│   └── test_wireguard.py    # WireGuard service unit tests
├── migrations/
├── Containerfile
├── entrypoint.sh            # Runs flask db upgrade then gunicorn
├── podman-compose.yml
├── nginx.conf
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

## Local Development

### Prerequisites

- Python 3.11+
- No WireGuard interface required locally (`WG_DEV_MODE=true` stubs all `wg` calls)

### Setup

```bash
git clone <repo-url>
cd vpn-portal

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
pip install -r requirements-dev.txt

cp .env.example .env              # Edit values as needed (WG_DEV_MODE=true by default)
```

### Database

```bash
flask db upgrade                  # Apply migrations (creates vpn_portal.db)
flask seed-admin                  # Create the admin user (reads ADMIN_USERNAME / ADMIN_PASSWORD from .env)
```

Default admin credentials: `admin` / `changeme`. Change them via `.env` before seeding.

### Run

```bash
flask run
```

The app is available at `http://127.0.0.1:5000`.

### Tests

```bash
pytest -v
```

72 tests across two suites (unit + integration), all running against an in-memory
SQLite database with `WG_DEV_MODE=true`.

### Code Quality

```bash
black app/ tests/
flake8 app/ tests/
```

## Environment Variables

Copy `.env.example` to `.env` and set the following:

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session signing key. Use a long random string in production. |
| `FLASK_ENV` | No | `development`, `testing`, or `production`. Defaults to `development`. |
| `DATABASE_URL` | No | SQLAlchemy URI. Defaults to `sqlite:///vpn_portal.db`. |
| `WG_SERVER_PUBLIC_KEY` | Yes (prod) | Base64 public key of the WireGuard server interface. |
| `WG_SERVER_ENDPOINT` | Yes (prod) | Server endpoint shown in client configs, e.g. `vpn.example.com:51820`. |
| `WG_DNS` | No | DNS server written into client configs. Defaults to `1.1.1.1`. |
| `WG_SUBNET` | No | Subnet for peer IPs. Defaults to `10.0.0.0/24`. |
| `WG_SERVER_IP` | No | Server IP within the subnet. Defaults to `10.0.0.1`. |
| `WG_INTERFACE` | No | WireGuard interface name. Defaults to `wg0`. |
| `WG_DEV_MODE` | No | Set to `true` to stub all `wg` and filesystem calls. |
| `RATELIMIT_STORAGE_URL` | No | Flask-Limiter storage URI. Defaults to `memory://`. Use a Redis URL in production for persistence across restarts. |
| `ADMIN_USERNAME` | No | Username for `flask seed-admin`. Defaults to `admin`. |
| `ADMIN_PASSWORD` | No | Password for `flask seed-admin`. Defaults to `changeme`. |

## Production Deployment

The intended production setup is a Rocky Linux VPS running the app in a Podman
container behind an Nginx reverse proxy.

### 1. Prepare the VPS

WireGuard must be configured and running on the host before the portal can manage
peers. The container mounts `/etc/wireguard` from the host.

```bash
# On the VPS
wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key
chmod 600 /etc/wireguard/private.key

# Create /etc/wireguard/wg0.conf with at minimum:
# [Interface]
# PrivateKey = <contents of private.key>
# Address = 10.0.0.1/24
# ListenPort = 51820

wg-quick up wg0
systemctl enable wg-quick@wg0
```

### 2. Configure the app

```bash
mkdir -p /opt/vpn-portal
cp podman-compose.yml /opt/vpn-portal/
cp .env.example /opt/vpn-portal/.env
```

Edit `/opt/vpn-portal/.env`:

```
FLASK_ENV=production
SECRET_KEY=<long-random-string>
WG_SERVER_PUBLIC_KEY=<contents of /etc/wireguard/public.key>
WG_SERVER_ENDPOINT=vpn.example.com:51820
WG_DEV_MODE=false
```

### 3. Run the container

```bash
cd /opt/vpn-portal
podman-compose up -d

# Create the admin account
podman exec vpn-portal flask seed-admin
```

The container runs Gunicorn on port 8000, bound to `127.0.0.1` only.

### 4. Configure Nginx

Copy `nginx.conf` to `/etc/nginx/conf.d/vpn-portal.conf`, replace
`vpn.example.com` with your domain, and obtain a certificate:

```bash
certbot --nginx -d vpn.example.com
systemctl reload nginx
```

### 5. CI/CD

The included GitHub Actions workflow (`.github/workflows/deploy.yml`) triggers on
every push to `main`:

1. Builds the container image and pushes it to GitHub Container Registry (GHCR)
2. SSH-es into the VPS, pulls the new image, and restarts the container via `podman-compose`

Set the following secrets in your GitHub repository:

| Secret | Value |
|---|---|
| `VPS_HOST` | IP address or hostname of your VPS |
| `VPS_USER` | SSH user on the VPS |
| `VPS_SSH_KEY` | Private SSH key (the public key must be in `~/.ssh/authorized_keys` on the VPS) |

## Security Notes

- Passwords are hashed with bcrypt (cost factor 12)
- All forms are CSRF-protected
- Login is rate-limited to 10 requests per minute per IP
- The `next` redirect parameter is validated to reject external URLs and non-HTTP schemes
- Download filenames are sanitised before being sent in `Content-Disposition` headers
- Peer names are stripped of newlines before being written into WireGuard config comments
- The container requires `NET_ADMIN` capability and `/dev/net/tun` to manage the WireGuard interface
- Nginx enforces HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and a strict Content Security Policy
- WireGuard peer private keys are stored in the database; ensure the database file is not world-readable and consider encrypting the volume at rest

## License

MIT
