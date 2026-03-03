"""Integration tests: full user flow from admin login to QR display."""

import pytest

from app.models import Peer, User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client, username, password, follow_redirects=True):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=follow_redirects,
    )


def _make_admin(db, username="admin", password="adminpass123"):
    admin = User(username=username, role="admin")
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    return admin


def _create_user_via_admin(client, username, password, peer_name):
    return client.post(
        "/admin/users/create",
        data={
            "username": username,
            "password": password,
            "confirm_password": password,
            "peer_name": peer_name,
        },
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_login_page_loads(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert b"Login" in resp.data

    def test_admin_login_success_redirects_to_index(self, client, db):
        _make_admin(db)
        resp = _login(client, "admin", "adminpass123")
        assert resp.status_code == 200
        assert b"WireGuard VPN Portal" in resp.data

    def test_login_wrong_password_shows_error(self, client, db):
        _make_admin(db)
        resp = _login(client, "admin", "wrongpassword")
        assert b"Invalid username or password" in resp.data

    def test_login_nonexistent_user_shows_error(self, client):
        resp = _login(client, "nobody", "password")
        assert b"Invalid username or password" in resp.data

    def test_already_logged_in_redirected_from_login(self, client, db):
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        resp = client.get("/auth/login", follow_redirects=True)
        # Should land on index, not stay on login
        assert b"WireGuard VPN Portal" in resp.data

    def test_logout_clears_session(self, client, db):
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        resp = client.get("/auth/logout", follow_redirects=True)
        assert resp.status_code == 200
        assert b"logged out" in resp.data.lower()

    def test_logout_requires_login(self, client):
        resp = client.get("/auth/logout", follow_redirects=True)
        # Redirected to login page
        assert b"Login" in resp.data


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


class TestAccessControl:
    def test_admin_dashboard_requires_login(self, client):
        resp = client.get("/admin/", follow_redirects=True)
        assert b"Login" in resp.data

    def test_user_dashboard_requires_login(self, client):
        resp = client.get("/user/", follow_redirects=True)
        assert b"Login" in resp.data

    def test_download_requires_login(self, client):
        resp = client.get("/user/download", follow_redirects=True)
        assert b"Login" in resp.data

    def test_qr_requires_login(self, client):
        resp = client.get("/user/qr", follow_redirects=True)
        assert b"Login" in resp.data

    def test_regular_user_cannot_access_admin_dashboard(self, client, db):
        user = User(username="regularuser", role="user")
        user.set_password("userpass123")
        db.session.add(user)
        db.session.commit()
        _login(client, "regularuser", "userpass123")
        resp = client.get("/admin/")
        assert resp.status_code == 403

    def test_regular_user_cannot_access_create_user(self, client, db):
        user = User(username="regularuser2", role="user")
        user.set_password("userpass123")
        db.session.add(user)
        db.session.commit()
        _login(client, "regularuser2", "userpass123")
        resp = client.post("/admin/users/create", data={})
        assert resp.status_code == 403

    def test_admin_can_access_dashboard(self, client, db):
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"Admin Dashboard" in resp.data


# ---------------------------------------------------------------------------
# Admin: create user + peer
# ---------------------------------------------------------------------------


class TestAdminCreateUser:
    def test_create_user_and_peer_succeeds(self, client, db):
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        resp = _create_user_via_admin(client, "newuser", "newuserpass123", "Laptop")
        assert resp.status_code == 200
        assert b"newuser" in resp.data

        user = User.query.filter_by(username="newuser").first()
        assert user is not None
        assert user.role == "user"
        assert len(user.peers) == 1
        assert user.peers[0].name == "Laptop"
        assert user.peers[0].is_active is True
        assert user.peers[0].assigned_ip == "10.0.0.2"

    def test_created_peer_appears_on_dashboard(self, client, db):
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        _create_user_via_admin(client, "peeruser", "peeruserpass123", "WorkPhone")
        resp = client.get("/admin/")
        assert b"WorkPhone" in resp.data
        assert b"peeruser" in resp.data

    def test_duplicate_username_shows_error(self, client, db):
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        post_data = {
            "username": "dupuser",
            "password": "dupuserpass123",
            "confirm_password": "dupuserpass123",
            "peer_name": "Phone",
        }
        client.post("/admin/users/create", data=post_data, follow_redirects=True)
        resp = client.post("/admin/users/create", data=post_data, follow_redirects=True)
        assert b"already taken" in resp.data

    def test_password_mismatch_shows_error(self, client, db):
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        resp = client.post(
            "/admin/users/create",
            data={
                "username": "mismatch",
                "password": "password123",
                "confirm_password": "different123",
                "peer_name": "Tablet",
            },
            follow_redirects=True,
        )
        assert b"Passwords must match" in resp.data

    def test_short_password_shows_error(self, client, db):
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        resp = client.post(
            "/admin/users/create",
            data={
                "username": "shortpw",
                "password": "abc",
                "confirm_password": "abc",
                "peer_name": "Device",
            },
            follow_redirects=True,
        )
        assert b"8 characters" in resp.data

    def test_second_user_gets_next_ip(self, client, db):
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        _create_user_via_admin(client, "user1", "user1pass123", "PC")
        _create_user_via_admin(client, "user2", "user2pass123", "Mac")
        peer1 = Peer.query.filter_by(name="PC").first()
        peer2 = Peer.query.filter_by(name="Mac").first()
        assert peer1.assigned_ip == "10.0.0.2"
        assert peer2.assigned_ip == "10.0.0.3"

    def test_create_user_form_loads(self, client, db):
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        resp = client.get("/admin/users/create")
        assert resp.status_code == 200
        assert b"Create User" in resp.data


# ---------------------------------------------------------------------------
# Full flow: admin creates user → user logs in → views config → downloads → QR
# ---------------------------------------------------------------------------


class TestFullFlow:
    @pytest.fixture(autouse=True)
    def setup(self, client, db):
        """Create admin and a regular user+peer before each test in this class."""
        _make_admin(db)
        _login(client, "admin", "adminpass123")
        _create_user_via_admin(client, "vpnuser", "vpnuserpass123", "MyLaptop")
        client.get("/auth/logout")
        self.client = client

    def test_user_can_login(self):
        resp = _login(self.client, "vpnuser", "vpnuserpass123")
        assert resp.status_code == 200
        assert b"WireGuard VPN Portal" in resp.data

    def test_user_dashboard_shows_peer_info(self):
        _login(self.client, "vpnuser", "vpnuserpass123")
        resp = self.client.get("/user/")
        assert resp.status_code == 200
        assert b"MyLaptop" in resp.data
        assert b"[Interface]" in resp.data
        assert b"PrivateKey" in resp.data
        assert b"10.0.0.2" in resp.data

    def test_user_dashboard_shows_download_link(self):
        _login(self.client, "vpnuser", "vpnuserpass123")
        resp = self.client.get("/user/")
        assert b"Download .conf" in resp.data
        assert b"Show QR Code" in resp.data

    def test_user_download_config_returns_conf_file(self):
        _login(self.client, "vpnuser", "vpnuserpass123")
        resp = self.client.get("/user/download")
        assert resp.status_code == 200
        assert resp.mimetype == "text/plain"
        assert b"[Interface]" in resp.data
        assert b"PrivateKey" in resp.data
        assert b"[Peer]" in resp.data
        assert b"AllowedIPs" in resp.data

    def test_user_download_config_has_correct_filename(self):
        _login(self.client, "vpnuser", "vpnuserpass123")
        resp = self.client.get("/user/download")
        content_disposition = resp.headers.get("Content-Disposition", "")
        assert "MyLaptop.conf" in content_disposition

    def test_user_download_config_is_attachment(self):
        _login(self.client, "vpnuser", "vpnuserpass123")
        resp = self.client.get("/user/download")
        assert "attachment" in resp.headers.get("Content-Disposition", "")

    def test_user_qr_page_loads(self):
        _login(self.client, "vpnuser", "vpnuserpass123")
        resp = self.client.get("/user/qr")
        assert resp.status_code == 200
        assert b"MyLaptop" in resp.data

    def test_user_qr_contains_png_data_uri(self):
        _login(self.client, "vpnuser", "vpnuserpass123")
        resp = self.client.get("/user/qr")
        assert b"data:image/png;base64," in resp.data

    def test_user_cannot_access_other_user_data(self, db):
        """Second user should only see their own peer."""
        # Create a second user while still logged in as admin — re-login
        _login(self.client, "admin", "adminpass123")
        _create_user_via_admin(
            self.client, "otheruser", "otheruserpass123", "OtherDevice"
        )
        self.client.get("/auth/logout")

        _login(self.client, "vpnuser", "vpnuserpass123")
        resp = self.client.get("/user/")
        assert b"MyLaptop" in resp.data
        assert b"OtherDevice" not in resp.data


# ---------------------------------------------------------------------------
# No peer edge cases
# ---------------------------------------------------------------------------


class TestNoPeer:
    def test_user_without_peer_sees_placeholder(self, client, db):
        user = User(username="nopeer", role="user")
        user.set_password("nopeerpass123")
        db.session.add(user)
        db.session.commit()
        _login(client, "nopeer", "nopeerpass123")
        resp = client.get("/user/")
        assert resp.status_code == 200
        assert b"No active VPN peer" in resp.data

    def test_user_without_peer_download_returns_404(self, client, db):
        user = User(username="nopeer2", role="user")
        user.set_password("nopeerpass123")
        db.session.add(user)
        db.session.commit()
        _login(client, "nopeer2", "nopeerpass123")
        resp = client.get("/user/download")
        assert resp.status_code == 404

    def test_user_without_peer_qr_returns_404(self, client, db):
        user = User(username="nopeer3", role="user")
        user.set_password("nopeerpass123")
        db.session.add(user)
        db.session.commit()
        _login(client, "nopeer3", "nopeerpass123")
        resp = client.get("/user/qr")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Open redirect
# ---------------------------------------------------------------------------


class TestOpenRedirect:
    def test_absolute_url_next_param_is_rejected(self, client, db):
        _make_admin(db)
        resp = _login(
            client,
            "admin",
            "adminpass123",
            follow_redirects=False,
        )
        # When no next param: redirects to index
        location = resp.headers.get("Location", "")
        assert "evil.com" not in location

    def test_absolute_evil_next_param_is_rejected(self, client, db):
        _make_admin(db)
        resp = client.post(
            "/auth/login?next=http://evil.com/steal",
            data={"username": "admin", "password": "adminpass123"},
            follow_redirects=False,
        )
        location = resp.headers.get("Location", "")
        assert "evil.com" not in location

    def test_relative_next_param_is_accepted(self, client, db):
        _make_admin(db)
        resp = client.post(
            "/auth/login?next=/admin/",
            data={"username": "admin", "password": "adminpass123"},
            follow_redirects=False,
        )
        location = resp.headers.get("Location", "")
        assert "/admin/" in location
