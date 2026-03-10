# Contributing to VPN Portal

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

## Running Tests

```bash
pytest
```

---

## Code Quality

```bash
black .        # format
flake8         # lint
```

---

## How to Contribute

1. Fork the repository and create a feature branch
2. Install dev dependencies: `pip install -r requirements-dev.txt`
3. Make your changes and add tests where appropriate
4. Run `black .` and `flake8` before committing
5. Run `pytest` to verify all tests pass
6. Open a pull request against `main`
