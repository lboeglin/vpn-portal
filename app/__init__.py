import os
import click
from flask import Flask, render_template
from dotenv import load_dotenv

from .config import config_map
from .extensions import db, migrate, login_manager, bcrypt, limiter

load_dotenv()


def create_app(config_name: str | None = None) -> Flask:
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__)
    app.config.from_object(config_map.get(config_name, config_map["development"]))

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    limiter.init_app(app)

    # Models (must be imported after db is initialized so Flask-Migrate can detect them)
    from . import models  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(models.User, int(user_id))

    # Blueprints
    from .auth import bp as auth_bp
    from .admin import bp as admin_bp
    from .user import bp as user_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(user_bp, url_prefix="/user")

    # Hello-world index
    @app.route("/")
    def index():
        return render_template("index.html")

    # CLI commands
    @app.cli.command("seed-admin")
    def seed_admin():
        """Create the default admin user if one does not already exist."""
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD", "changeme")

        existing = models.User.query.filter_by(username=username).first()
        if existing:
            click.echo(f"Admin user '{username}' already exists — skipping.")
            return

        admin = models.User(username=username, role="admin")
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Admin user '{username}' created.")

    return app
