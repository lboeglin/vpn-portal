"""WireGuard service layer.

All functions that touch the OS (subprocess / filesystem) respect WG_DEV_MODE:
when True they log the command/content they *would* execute and return without
side-effects, enabling full local development without root or a wg0 interface.
"""

import base64
import io
import ipaddress
import logging
import textwrap

import qrcode
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from flask import current_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


def generate_keypair() -> dict[str, str]:
    """Return a new WireGuard keypair as base64-encoded strings.

    Returns:
        {"private_key": "<base64>", "public_key": "<base64>"}
    """
    priv = X25519PrivateKey.generate()
    return {
        "private_key": base64.b64encode(priv.private_bytes_raw()).decode(),
        "public_key": base64.b64encode(priv.public_key().public_bytes_raw()).decode(),
    }


# ---------------------------------------------------------------------------
# IP allocation
# ---------------------------------------------------------------------------


def get_next_available_ip() -> str:
    """Return the next unallocated host IP in the WireGuard subnet.

    Skips the network address, broadcast address, and the server IP.

    Raises:
        RuntimeError: if the subnet is exhausted.
    """
    from ..models import Peer  # local import to avoid circular deps at module load

    subnet = ipaddress.ip_network(current_app.config["WG_SUBNET"], strict=False)
    server_ip = ipaddress.ip_address(current_app.config["WG_SERVER_IP"])
    assigned = {row[0] for row in Peer.query.with_entities(Peer.assigned_ip).all()}

    for host in subnet.hosts():
        if host == server_ip:
            continue
        if str(host) not in assigned:
            return str(host)

    raise RuntimeError(
        f"No available IP addresses in subnet {current_app.config['WG_SUBNET']}."
    )


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------


def generate_client_config(peer) -> str:
    """Generate the WireGuard client config INI string for *peer*.

    Args:
        peer: a Peer model instance (must have private_key, assigned_ip).

    Returns:
        A multi-line WireGuard INI config string.
    """
    server_pubkey = current_app.config["WG_SERVER_PUBLIC_KEY"]
    endpoint = current_app.config["WG_SERVER_ENDPOINT"]
    dns = current_app.config["WG_DNS"]
    prefix_len = ipaddress.ip_network(
        current_app.config["WG_SUBNET"], strict=False
    ).prefixlen

    return textwrap.dedent(f"""\
        [Interface]
        PrivateKey = {peer.private_key}
        Address = {peer.assigned_ip}/{prefix_len}
        DNS = {dns}

        [Peer]
        PublicKey = {server_pubkey}
        Endpoint = {endpoint}
        AllowedIPs = 0.0.0.0/0
        PersistentKeepalive = 25
    """)


# ---------------------------------------------------------------------------
# QR code
# ---------------------------------------------------------------------------


def generate_qr_code(config_str: str) -> bytes:
    """Render *config_str* as a QR code and return PNG bytes.

    Args:
        config_str: the WireGuard config text (output of generate_client_config).

    Returns:
        Raw PNG image bytes.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(config_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Interface management
# ---------------------------------------------------------------------------


def apply_peer_to_interface(peer) -> None:
    """Signal that a peer should be applied to the WireGuard interface.

    In production the actual ``wg addconf`` is performed by the host-side
    vpn-portal-wg-sync systemd service that watches the peers config file.
    This function is a no-op beyond logging; call sync_config_file() to
    write the peers file that triggers the host service.

    Args:
        peer: a Peer model instance (must have public_key, assigned_ip).
    """
    interface = current_app.config["WG_INTERFACE"]
    if current_app.config["WG_DEV_MODE"]:
        logger.info(
            "[DEV MODE] Peer %s… would be applied to %s",
            peer.public_key[:8],
            interface,
        )
        return
    logger.info(
        "Peer %s… queued for interface %s (applied by host sync service)",
        peer.public_key[:8],
        interface,
    )


def sync_config_file() -> None:
    """Write all active peers to the vpn-portal peers config file.

    Writes /var/lib/vpn-portal/peers.conf with [Peer] blocks for every
    active peer in the database.  The host-side vpn-portal-wg-sync systemd
    path unit detects changes to this file and runs ``wg addconf`` +
    persists the peers to wg0.conf — no CAP_NET_ADMIN needed in the container.

    In WG_DEV_MODE the content is logged but the file is not written.
    """
    from ..models import Peer  # local import to avoid circular deps at module load

    peers_conf_path = "/var/lib/vpn-portal/peers.conf"

    active_peers = Peer.query.filter_by(is_active=True).all()
    peer_blocks = [
        f"[Peer]\n# {p.name.replace(chr(10), ' ').replace(chr(13), ' ')}\n"
        f"PublicKey = {p.public_key}\n"
        f"AllowedIPs = {p.assigned_ip}/32\n"
        for p in active_peers
    ]
    peer_section = "\n".join(peer_blocks)

    if current_app.config["WG_DEV_MODE"]:
        logger.info("[DEV MODE] Would write peer config to %s:\n%s", peers_conf_path, peer_section)
        return

    with open(peers_conf_path, "w") as fh:
        fh.write(peer_section + "\n")
    logger.info("Wrote %d active peer(s) to %s", len(active_peers), peers_conf_path)


