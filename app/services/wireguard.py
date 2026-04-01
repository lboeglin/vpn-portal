"""WireGuard service layer.

All functions that touch the OS (subprocess / filesystem) respect WG_DEV_MODE:
when True they log the command/content they *would* execute and return without
side-effects, enabling full local development without root or a wg0 interface.
"""

import base64
import io
import ipaddress
import logging
import subprocess
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
    """Add a peer to the live WireGuard interface via ``wg set``.

    Args:
        peer: a Peer model instance (must have public_key, assigned_ip).
    """
    interface = current_app.config["WG_INTERFACE"]
    cmd = [
        "wg",
        "set",
        interface,
        "peer",
        peer.public_key,
        "allowed-ips",
        f"{peer.assigned_ip}/32",
    ]
    if current_app.config["WG_DEV_MODE"]:
        logger.info("[DEV MODE] Would run: %s", " ".join(cmd))
        return
    subprocess.run(cmd, check=True)


def _read_interface_block(path: str) -> str:
    """Return the [Interface] section from a wg conf file, or '' if absent/missing."""
    try:
        with open(path) as fh:
            content = fh.read()
    except FileNotFoundError:
        return ""

    lines = []
    in_interface = False
    for line in content.splitlines(keepends=True):
        if line.strip() == "[Interface]":
            in_interface = True
        elif line.strip().startswith("[") and in_interface:
            break
        if in_interface:
            lines.append(line)

    return "".join(lines)


def sync_config_file() -> None:
    """Rewrite wg0.conf with the current active peers and run ``wg syncconf``.

    Preserves the existing [Interface] block, replaces all [Peer] sections
    with the current active peers from the database.

    In WG_DEV_MODE the operation is logged but not executed.
    """
    from ..models import Peer  # local import to avoid circular deps at module load

    interface = current_app.config["WG_INTERFACE"]
    conf_path = f"/etc/wireguard/{interface}.conf"

    active_peers = Peer.query.filter_by(is_active=True).all()
    peer_blocks = [
        f"[Peer]\n# {p.name.replace(chr(10), ' ').replace(chr(13), ' ')}\n"
        f"PublicKey = {p.public_key}\n"
        f"AllowedIPs = {p.assigned_ip}/32\n"
        for p in active_peers
    ]
    peer_section = "\n".join(peer_blocks)

    syncconf_cmd = ["wg", "syncconf", interface, conf_path]

    if current_app.config["WG_DEV_MODE"]:
        logger.info(
            "[DEV MODE] Would write %s:\n%s\nand run: %s",
            conf_path,
            peer_section,
            " ".join(syncconf_cmd),
        )
        return

    interface_block = _read_interface_block(conf_path)
    with open(conf_path, "w") as fh:
        fh.write(interface_block)
        if peer_section:
            fh.write("\n" + peer_section + "\n")
    subprocess.run(syncconf_cmd, check=True)
    logger.info("Synced %d active peer(s) to %s", len(active_peers), conf_path)
