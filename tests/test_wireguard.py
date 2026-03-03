"""Unit tests for app/services/wireguard.py"""

import base64
import io
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.models import Peer, User
from app.services.wireguard import (
    _read_interface_block,
    apply_peer_to_interface,
    generate_client_config,
    generate_keypair,
    generate_qr_code,
    get_next_available_ip,
    sync_config_file,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_user(db):
    user = User(username="testuser", role="user")
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def peer(db, test_user):
    kp = generate_keypair()
    p = Peer(
        user_id=test_user.id,
        name="laptop",
        private_key=kp["private_key"],
        public_key=kp["public_key"],
        assigned_ip="10.0.0.2",
        is_active=True,
    )
    db.session.add(p)
    db.session.commit()
    return p


# ---------------------------------------------------------------------------
# generate_keypair
# ---------------------------------------------------------------------------


class TestGenerateKeypair:
    def test_returns_expected_keys(self):
        result = generate_keypair()
        assert set(result) == {"private_key", "public_key"}

    def test_keys_are_valid_32_byte_base64(self):
        result = generate_keypair()
        for key in ("private_key", "public_key"):
            raw = base64.b64decode(result[key])
            assert len(raw) == 32, f"{key} should decode to 32 bytes"

    def test_each_call_produces_unique_keys(self):
        a, b = generate_keypair(), generate_keypair()
        assert a["private_key"] != b["private_key"]
        assert a["public_key"] != b["public_key"]

    def test_public_key_derives_from_private_key(self):
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        result = generate_keypair()
        priv_bytes = base64.b64decode(result["private_key"])
        expected_pub = base64.b64encode(
            X25519PrivateKey.from_private_bytes(priv_bytes)
            .public_key()
            .public_bytes_raw()
        ).decode()
        assert expected_pub == result["public_key"]


# ---------------------------------------------------------------------------
# get_next_available_ip
# ---------------------------------------------------------------------------


class TestGetNextAvailableIp:
    def test_returns_first_non_server_host(self, app):
        # Fresh DB: no peers assigned yet, server is 10.0.0.1
        ip = get_next_available_ip()
        assert ip == "10.0.0.2"

    def test_skips_already_assigned_ips(self, app, peer):
        # peer fixture holds 10.0.0.2
        ip = get_next_available_ip()
        assert ip == "10.0.0.3"

    def test_raises_when_subnet_exhausted(self, app, db, test_user):
        # Use a /30: hosts are .1 (server) and .2 — fill .2 to exhaust
        with patch.dict(
            app.config, {"WG_SUBNET": "10.0.0.0/30", "WG_SERVER_IP": "10.0.0.1"}
        ):
            p = Peer(
                user_id=test_user.id,
                name="full",
                private_key="x",
                public_key="x",
                assigned_ip="10.0.0.2",
                is_active=True,
            )
            db.session.add(p)
            db.session.commit()

            with pytest.raises(RuntimeError, match="No available IP"):
                get_next_available_ip()


# ---------------------------------------------------------------------------
# generate_client_config
# ---------------------------------------------------------------------------


class TestGenerateClientConfig:
    def test_has_interface_and_peer_sections(self, app, peer):
        cfg = generate_client_config(peer)
        assert "[Interface]" in cfg
        assert "[Peer]" in cfg

    def test_includes_peer_private_key(self, app, peer):
        cfg = generate_client_config(peer)
        assert f"PrivateKey = {peer.private_key}" in cfg

    def test_includes_assigned_ip_with_prefix(self, app, peer):
        cfg = generate_client_config(peer)
        # Default subnet 10.0.0.0/24 → prefix 24
        assert "10.0.0.2/24" in cfg

    def test_includes_server_public_key(self, app, peer):
        with patch.dict(app.config, {"WG_SERVER_PUBLIC_KEY": "SRV_PUB=="}):
            cfg = generate_client_config(peer)
        assert "SRV_PUB==" in cfg

    def test_includes_server_endpoint(self, app, peer):
        cfg = generate_client_config(peer)
        assert app.config["WG_SERVER_ENDPOINT"] in cfg

    def test_includes_dns(self, app, peer):
        cfg = generate_client_config(peer)
        assert app.config["WG_DNS"] in cfg

    def test_includes_allowed_ips(self, app, peer):
        cfg = generate_client_config(peer)
        assert "AllowedIPs = 0.0.0.0/0" in cfg

    def test_includes_keepalive(self, app, peer):
        cfg = generate_client_config(peer)
        assert "PersistentKeepalive = 25" in cfg


# ---------------------------------------------------------------------------
# generate_qr_code
# ---------------------------------------------------------------------------


class TestGenerateQrCode:
    def test_returns_png_magic_bytes(self):
        png = generate_qr_code("[Interface]\nPrivateKey = abc\n")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_returns_non_empty_bytes(self):
        png = generate_qr_code("some config text")
        assert len(png) > 100  # a real PNG will be much larger than this

    def test_different_configs_produce_different_qr(self):
        png_a = generate_qr_code("config_a")
        png_b = generate_qr_code("config_b")
        assert png_a != png_b

    def test_roundtrip_via_pil(self):
        """Verify the returned bytes can be read back as a valid image."""
        from PIL import Image

        png = generate_qr_code("test config")
        img = Image.open(io.BytesIO(png))
        assert img.format == "PNG"


# ---------------------------------------------------------------------------
# apply_peer_to_interface
# ---------------------------------------------------------------------------


class TestApplyPeerToInterface:
    def test_dev_mode_does_not_call_subprocess(self, app, peer):
        assert app.config["WG_DEV_MODE"] is True
        with patch("app.services.wireguard.subprocess.run") as mock_run:
            apply_peer_to_interface(peer)
            mock_run.assert_not_called()

    def test_dev_mode_logs_wg_set_command(self, app, peer, caplog):
        with caplog.at_level(logging.INFO, logger="app.services.wireguard"):
            apply_peer_to_interface(peer)
        assert "DEV MODE" in caplog.text
        assert "wg set" in caplog.text

    def test_dev_mode_logs_interface_name(self, app, peer, caplog):
        with caplog.at_level(logging.INFO, logger="app.services.wireguard"):
            apply_peer_to_interface(peer)
        assert app.config["WG_INTERFACE"] in caplog.text

    def test_production_calls_wg_set_with_correct_args(self, app, peer):
        with patch.dict(app.config, {"WG_DEV_MODE": False}):
            with patch("app.services.wireguard.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                apply_peer_to_interface(peer)

                mock_run.assert_called_once()
                cmd = mock_run.call_args[0][0]
                assert cmd[0] == "wg"
                assert cmd[1] == "set"
                assert "peer" in cmd
                assert peer.public_key in cmd
                assert f"{peer.assigned_ip}/32" in cmd

    def test_production_uses_configured_interface(self, app, peer):
        with patch.dict(app.config, {"WG_DEV_MODE": False, "WG_INTERFACE": "wg1"}):
            with patch("app.services.wireguard.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                apply_peer_to_interface(peer)

                cmd = mock_run.call_args[0][0]
                assert "wg1" in cmd


# ---------------------------------------------------------------------------
# sync_config_file
# ---------------------------------------------------------------------------


class TestSyncConfigFile:
    def test_dev_mode_does_not_write_file(self, app, peer):
        assert app.config["WG_DEV_MODE"] is True
        with patch("builtins.open") as mock_open_fn:
            with patch("app.services.wireguard.subprocess.run"):
                sync_config_file()
            mock_open_fn.assert_not_called()

    def test_dev_mode_does_not_call_subprocess(self, app, peer):
        with patch("app.services.wireguard.subprocess.run") as mock_run:
            sync_config_file()
            mock_run.assert_not_called()

    def test_dev_mode_logs_peer_public_key(self, app, peer, caplog):
        with caplog.at_level(logging.INFO, logger="app.services.wireguard"):
            sync_config_file()
        assert peer.public_key in caplog.text

    def test_dev_mode_logs_syncconf_command(self, app, peer, caplog):
        with caplog.at_level(logging.INFO, logger="app.services.wireguard"):
            sync_config_file()
        assert "syncconf" in caplog.text

    def test_production_writes_config_file(self, app, peer):
        buf = io.StringIO()
        mock_file = MagicMock()
        mock_file.__enter__ = lambda s: buf
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch.dict(app.config, {"WG_DEV_MODE": False}):
            with patch(
                "app.services.wireguard._read_interface_block",
                return_value="[Interface]\n",
            ):
                with patch("builtins.open", return_value=mock_file):
                    with patch("app.services.wireguard.subprocess.run"):
                        sync_config_file()

        assert buf.getvalue() != ""

    def test_production_calls_wg_syncconf(self, app, peer):
        buf = io.StringIO()
        mock_file = MagicMock()
        mock_file.__enter__ = lambda s: buf
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch.dict(app.config, {"WG_DEV_MODE": False}):
            with patch(
                "app.services.wireguard._read_interface_block",
                return_value="[Interface]\n",
            ):
                with patch("builtins.open", return_value=mock_file):
                    with patch("app.services.wireguard.subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        sync_config_file()

                        mock_run.assert_called_once()
                        cmd = mock_run.call_args[0][0]
                        assert "syncconf" in cmd
                        assert app.config["WG_INTERFACE"] in cmd

    def test_production_includes_only_active_peers(self, app, db, test_user):
        kp1, kp2 = generate_keypair(), generate_keypair()
        active = Peer(
            user_id=test_user.id,
            name="active",
            private_key=kp1["private_key"],
            public_key=kp1["public_key"],
            assigned_ip="10.0.0.2",
            is_active=True,
        )
        inactive = Peer(
            user_id=test_user.id,
            name="inactive",
            private_key=kp2["private_key"],
            public_key=kp2["public_key"],
            assigned_ip="10.0.0.3",
            is_active=False,
        )
        db.session.add_all([active, inactive])
        db.session.commit()

        buf = io.StringIO()
        mock_file = MagicMock()
        mock_file.__enter__ = lambda s: buf
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch.dict(app.config, {"WG_DEV_MODE": False}):
            with patch(
                "app.services.wireguard._read_interface_block",
                return_value="[Interface]\n",
            ):
                with patch("builtins.open", return_value=mock_file):
                    with patch("app.services.wireguard.subprocess.run"):
                        sync_config_file()

        content = buf.getvalue()
        assert active.public_key in content
        assert inactive.public_key not in content

    def test_production_preserves_interface_block(self, app, db, test_user):
        kp = generate_keypair()
        p = Peer(
            user_id=test_user.id,
            name="p",
            private_key=kp["private_key"],
            public_key=kp["public_key"],
            assigned_ip="10.0.0.2",
            is_active=True,
        )
        db.session.add(p)
        db.session.commit()

        interface_block = (
            "[Interface]\nPrivateKey = SERVER_PRIV==\nListenPort = 51820\n"
        )
        buf = io.StringIO()
        mock_file = MagicMock()
        mock_file.__enter__ = lambda s: buf
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch.dict(app.config, {"WG_DEV_MODE": False}):
            with patch(
                "app.services.wireguard._read_interface_block",
                return_value=interface_block,
            ):
                with patch("builtins.open", return_value=mock_file):
                    with patch("app.services.wireguard.subprocess.run"):
                        sync_config_file()

        content = buf.getvalue()
        assert "SERVER_PRIV==" in content
        assert "ListenPort = 51820" in content


# ---------------------------------------------------------------------------
# _read_interface_block (internal helper)
# ---------------------------------------------------------------------------


class TestReadInterfaceBlock:
    def test_returns_empty_string_when_file_missing(self, tmp_path):
        result = _read_interface_block(str(tmp_path / "nonexistent.conf"))
        assert result == ""

    def test_extracts_interface_section(self, tmp_path):
        conf = tmp_path / "wg0.conf"
        conf.write_text(
            "[Interface]\n"
            "PrivateKey = SERVER_KEY\n"
            "ListenPort = 51820\n"
            "\n"
            "[Peer]\n"
            "PublicKey = CLIENT_KEY\n"
            "AllowedIPs = 10.0.0.2/32\n"
        )
        block = _read_interface_block(str(conf))
        assert "[Interface]" in block
        assert "SERVER_KEY" in block
        assert "ListenPort = 51820" in block

    def test_excludes_peer_sections(self, tmp_path):
        conf = tmp_path / "wg0.conf"
        conf.write_text("[Interface]\nPrivateKey = X\n\n[Peer]\nPublicKey = Y\n")
        block = _read_interface_block(str(conf))
        assert "Y" not in block

    def test_returns_empty_when_no_interface_section(self, tmp_path):
        conf = tmp_path / "wg0.conf"
        conf.write_text("[Peer]\nPublicKey = Y\nAllowedIPs = 10.0.0.2/32\n")
        block = _read_interface_block(str(conf))
        assert block == ""
