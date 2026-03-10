# Environment Variables

All variables are read from `.env` via `python-dotenv`. `.env.example` is the source of truth.

| Variable | Default | Description |
|---|---|---|
| `FLASK_APP` | `app` | Flask application module |
| `FLASK_ENV` | `development` | `development`, `testing`, or `production` |
| `SECRET_KEY` | `change-me-to-a-random-secret-key` | Flask session signing key; **must be changed in production** |
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
| `ADMIN_PASSWORD` | `changeme` | Password created by `flask seed-admin`; **change immediately** |

> In production, `DATABASE_URL` is overridden by `podman-compose.yml` to `sqlite:////data/vpn_portal.db`, persisted in a named Podman volume.
