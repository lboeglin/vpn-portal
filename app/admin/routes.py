from functools import wraps

from flask import render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from . import bp
from .forms import CreateUserPeerForm
from ..models import User, Peer
from ..extensions import db
from ..services.wireguard import (
    apply_peer_to_interface,
    generate_keypair,
    get_next_available_ip,
    sync_config_file,
)


def admin_required(f):
    """Decorator: requires the user to be logged in and have role='admin'."""

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# Dashboard — list all peers
# ---------------------------------------------------------------------------


@bp.route("/")
@admin_required
def dashboard():
    peers = Peer.query.join(User).order_by(Peer.created_at.desc()).all()
    user_count = User.query.count()
    return render_template("admin/dashboard.html", peers=peers, user_count=user_count)


# ---------------------------------------------------------------------------
# Create user + peer
# ---------------------------------------------------------------------------


@bp.route("/users/create", methods=["GET", "POST"])
@admin_required
def create_user():
    form = CreateUserPeerForm()

    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash("Username already taken.", "danger")
            return render_template("admin/create_user.html", form=form)

        try:
            user = User(username=form.username.data, role="user")
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()  # populate user.id before creating the peer

            keypair = generate_keypair()
            assigned_ip = get_next_available_ip()

            peer = Peer(
                user_id=user.id,
                name=form.peer_name.data,
                private_key=keypair["private_key"],
                public_key=keypair["public_key"],
                assigned_ip=assigned_ip,
                is_active=True,
            )
            db.session.add(peer)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to create user: {exc}", "danger")
            return render_template("admin/create_user.html", form=form)

        try:
            apply_peer_to_interface(peer)
            sync_config_file()
        except Exception as exc:
            flash(
                f"User '{user.username}' created but WireGuard sync failed: {exc}",
                "warning",
            )
            return redirect(url_for("admin.dashboard"))

        flash(
            f"User '{user.username}' created with peer '{peer.name}' ({assigned_ip}).",
            "success",
        )
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/create_user.html", form=form)
