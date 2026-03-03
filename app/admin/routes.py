from . import bp  # noqa: F401


@bp.route("/")
def dashboard():
    return "Admin dashboard — coming soon"
