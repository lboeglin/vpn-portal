from . import bp  # noqa: F401


@bp.route("/")
def dashboard():
    return "User dashboard — coming soon"
