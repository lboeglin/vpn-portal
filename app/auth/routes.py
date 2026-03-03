from . import bp  # noqa: F401


@bp.route("/login")
def login():
    return "Login — coming soon"


@bp.route("/logout")
def logout():
    return "Logout — coming soon"
