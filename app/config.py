import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///vpn_portal.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # WireGuard
    WG_SERVER_PUBLIC_KEY = os.environ.get("WG_SERVER_PUBLIC_KEY", "")
    WG_SERVER_ENDPOINT = os.environ.get("WG_SERVER_ENDPOINT", "vpn.example.com:51820")
    WG_DNS = os.environ.get("WG_DNS", "1.1.1.1")
    WG_SUBNET = os.environ.get("WG_SUBNET", "10.0.0.0/24")
    WG_SERVER_IP = os.environ.get("WG_SERVER_IP", "10.0.0.1")
    WG_INTERFACE = os.environ.get("WG_INTERFACE", "wg0")
    WG_DEV_MODE = os.environ.get("WG_DEV_MODE", "false").lower() == "true"

    # Rate limiting
    RATELIMIT_STORAGE_URL = os.environ.get("RATELIMIT_STORAGE_URL", "memory://")


class DevelopmentConfig(Config):
    DEBUG = True
    WG_DEV_MODE = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    WG_DEV_MODE = True


class ProductionConfig(Config):
    DEBUG = False


config_map = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
