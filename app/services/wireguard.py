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
    """Add or update a peer on the running WireGuard interface.

    Runs: wg set <interface> peer <pubkey> allowed-ips <ip>/32

    In WG_DEV_MODE the command is logged but not executed.

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

    subprocess.run(cmd, check=True, capture_output=True, text=True)
    logger.info("Applied peer %s… to interface %s", peer.public_key[:8], interface)


def sync_config_file() -> None:
    """Rewrite the WireGuard config file and sync it with the running interface.

    Reads the [Interface] block from the existing on-disk config, replaces all
    [Peer] sections with the currently active peers from the database, writes the
    result back, then runs ``wg syncconf`` to apply changes atomically.

    In WG_DEV_MODE the file content and command are logged but not applied.
    """
    from ..models import Peer  # local import to avoid circular deps at module load

    interface = current_app.config["WG_INTERFACE"]
    config_path = f"/etc/wireguard/{interface}.conf"

    active_peers = Peer.query.filter_by(is_active=True).all()
    peer_blocks = [
        f"[Peer]\n# {p.name}\nPublicKey = {p.public_key}\n"
        f"AllowedIPs = {p.assigned_ip}/32\n"
        for p in active_peers
    ]
    peer_section = "\n".join(peer_blocks)

    if current_app.config["WG_DEV_MODE"]:
        logger.info(
            "[DEV MODE] Would write peer section to %s:\n%s",
            config_path,
            peer_section,
        )
        logger.info("[DEV MODE] Would run: wg syncconf %s %s", interface, config_path)
        return

    interface_block = _read_interface_block(config_path)
    full_config = interface_block + "\n" + peer_section

    with open(config_path, "w") as fh:
        fh.write(full_config)

    subprocess.run(
        ["wg", "syncconf", interface, config_path],
        check=True,
        capture_output=True,
        text=True,
    )
    logger.info("Synced %d active peer(s) to %s", len(active_peers), config_path)


def _read_interface_block(config_path: str) -> str:
    """Extract and return the [Interface] section from an existing wg conf file.

    Returns an empty string if the file does not exist or has no [Interface] block.
    """
    try:
        with open(config_path) as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return ""

    interface_lines: list[str] = []
    in_interface = False
    for line in lines:
        stripped = line.strip()
        if stripped == "[Interface]":
            in_interface = True
        elif stripped.startswith("[") and stripped.endswith("]") and in_interface:
            break  # reached the next section
        if in_interface:
            interface_lines.append(line)

    return "".join(interface_lines)
