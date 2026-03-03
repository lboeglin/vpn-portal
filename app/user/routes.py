import io
import re
from base64 import b64encode

from flask import abort, render_template, send_file
from flask_login import current_user, login_required

from . import bp
from ..models import Peer
from ..services.wireguard import generate_client_config, generate_qr_code


@bp.route("/")
@login_required
def dashboard():
    peer = Peer.query.filter_by(user_id=current_user.id, is_active=True).first()
    config = generate_client_config(peer) if peer else None
    return render_template("user/dashboard.html", peer=peer, config=config)


@bp.route("/download")
@login_required
def download():
    peer = Peer.query.filter_by(user_id=current_user.id, is_active=True).first()
    if not peer:
        abort(404)
    config = generate_client_config(peer)
    buf = io.BytesIO(config.encode())
    safe_name = re.sub(r"[^\w\-]", "_", peer.name)
    return send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name=f"{safe_name}.conf",
    )


@bp.route("/qr")
@login_required
def qr():
    peer = Peer.query.filter_by(user_id=current_user.id, is_active=True).first()
    if not peer:
        abort(404)
    config = generate_client_config(peer)
    png_bytes = generate_qr_code(config)
    qr_b64 = b64encode(png_bytes).decode()
    return render_template("user/qr.html", peer=peer, qr_b64=qr_b64)
