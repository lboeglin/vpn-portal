# Production Deployment Guide

## How it works

```
git push main  ->  GitHub Actions
                        |
                        +- Builds container image from Containerfile
                        +- Pushes image to ghcr.io/<owner>/<repo>:latest
                        +- SSHes into VPS
                               |
                               +- podman pull ghcr.io/<owner>/<repo>:latest
                               +- podman-compose up -d --no-build
```

The VPS never clones the repo. The source code lives in the container image, built
by CI on every push to `main`. The VPS only needs two files: `podman-compose.yml`
(copied once via scp) and `.env` (created directly on the VPS).

---

## Prerequisites

- A Rocky Linux VPS with a public IP
- A domain pointing to that IP (e.g. `vpn.yourdomain.com`)
- SSH access to the VPS
- The repo cloned on your local machine

---

## Step 1 - GitHub: create secrets and the Actions environment

### 1.1 Create the production environment

Go to your repo on GitHub:
**Settings > Environments > New environment** and name it `production`.

You can optionally add required reviewers to gate production deploys.

### 1.2 Add repository secrets

Go to **Settings > Secrets and variables > Actions > New repository secret** and add:

| Secret name | Value |
|---|---|
| `VPS_HOST` | VPS IP or domain (e.g. `203.0.113.10`) |
| `VPS_USER` | SSH user on the VPS (e.g. `root` or `deploy`) |
| `VPS_SSH_KEY` | Full content of the private SSH key that can connect to the VPS |

`GITHUB_TOKEN` is provided automatically by GitHub; no secret needed.

### 1.3 Generate a deploy SSH key pair (if you don't have one)

On your local machine:

```bash
ssh-keygen -t ed25519 -C "github-actions-vpn-portal" -f ~/.ssh/vpn_deploy_key
```

This creates:
- `~/.ssh/vpn_deploy_key` - private key - paste into `VPS_SSH_KEY` secret
- `~/.ssh/vpn_deploy_key.pub` - public key - add to the VPS (see Step 2.2)

---

## Step 2 - VPS: one-time system setup

### 2.1 Install required packages

```bash
sudo dnf install -y epel-release
sudo dnf install -y wireguard-tools podman podman-compose nginx certbot python3-certbot-nginx
```

### 2.2 Add the deploy SSH public key

If you created a dedicated key in Step 1.3, authorize it on the VPS:

```bash
ssh-copy-id -i ~/.ssh/vpn_deploy_key.pub YOUR_USER@YOUR_VPS_IP
```

Or manually append the public key to `~/.ssh/authorized_keys` on the VPS.

> **Note on users**: You can deploy as `root` (simpler) or create a dedicated `deploy`
> user (better practice). If you create a `deploy` user:
> ```bash
> sudo useradd -m -s /bin/bash deploy
> sudo usermod -aG wheel deploy
> sudo loginctl enable-linger deploy   # allows rootless podman as this user
> ```
> Then add the public key to `/home/deploy/.ssh/authorized_keys`.

### 2.3 Set up WireGuard on the host

The WireGuard server interface runs on the VPS host, not inside the container. The
container writes peer configs to `/var/lib/vpn-portal/peers.conf`; a privileged host
service watches that file and calls `wg addconf` to apply changes to the live interface.

```bash
# Generate server keys
wg genkey | sudo tee /etc/wireguard/server_private_key | wg pubkey | sudo tee /etc/wireguard/server_public_key
sudo chmod 600 /etc/wireguard/server_private_key

# Note the public key; you will need it in .env
sudo cat /etc/wireguard/server_public_key
```

Create the initial `wg0.conf` (replace the private key and network interface name):

```bash
sudo bash -c "cat > /etc/wireguard/wg0.conf" << 'EOF'
[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = PASTE_SERVER_PRIVATE_KEY_HERE

# Replace eth0 with your actual public network interface (check with: ip route | grep default)
PostUp   = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
EOF

sudo chmod 600 /etc/wireguard/wg0.conf
```

Enable IP forwarding and start WireGuard:

```bash
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

sudo systemctl enable --now wg-quick@wg0

# Open the WireGuard UDP port
sudo firewall-cmd --permanent --add-port=51820/udp
sudo firewall-cmd --reload

# Verify the interface is up
sudo wg show
```

### 2.4 Set up the host WireGuard sync service

The container writes active peer configs to `/var/lib/vpn-portal/peers.conf`. A
lightweight systemd path unit watches that file and calls `wg addconf` plus persists
the peers to `wg0.conf` when it changes.

```bash
# Shared directory (writable by the deploy user / container)
sudo mkdir -p /var/lib/vpn-portal
sudo chown YOUR_USER:YOUR_USER /var/lib/vpn-portal
sudo touch /var/lib/vpn-portal/peers.conf
sudo chown YOUR_USER:YOUR_USER /var/lib/vpn-portal/peers.conf

# Sync script
sudo tee /usr/local/bin/vpn-portal-wg-sync << 'EOF'
#!/bin/bash
set -e
PEERS_FILE="/var/lib/vpn-portal/peers.conf"
WG_CONF="/etc/wireguard/wg0.conf"
INTERFACE="wg0"

[ -s "$PEERS_FILE" ] || exit 0

wg addconf "$INTERFACE" "$PEERS_FILE"

sed -i '/^# BEGIN VPN PORTAL PEERS/,$d' "$WG_CONF"
printf '# BEGIN VPN PORTAL PEERS\n' >> "$WG_CONF"
cat "$PEERS_FILE" >> "$WG_CONF"

logger "vpn-portal: synced $(grep -c '^\[Peer\]' "$PEERS_FILE") peer(s) to $INTERFACE"
EOF
sudo chmod +x /usr/local/bin/vpn-portal-wg-sync

# systemd service unit
sudo tee /etc/systemd/system/vpn-portal-wg-sync.service << 'EOF'
[Unit]
Description=Apply VPN Portal WireGuard peer changes
After=wg-quick@wg0.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/vpn-portal-wg-sync
EOF

# systemd path unit - triggers on file change
sudo tee /etc/systemd/system/vpn-portal-wg-sync.path << 'EOF'
[Unit]
Description=Watch VPN Portal WireGuard peers config

[Path]
PathChanged=/var/lib/vpn-portal/peers.conf
Unit=vpn-portal-wg-sync.service

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now vpn-portal-wg-sync.path
```

---

## Step 3 - VPS: create the app directory and config files

### 3.1 Create the directory

```bash
sudo mkdir -p /opt/vpn-portal
sudo chown YOUR_USER:YOUR_USER /opt/vpn-portal
```

Replace `YOUR_USER` with `root`, `deploy`, or whoever will run the container.

### 3.2 Copy podman-compose.yml from your local machine

The `podman-compose.yml` is already in your repo. Copy it once to the VPS; it never
needs to change unless you update the compose config:

```bash
# Run this on your LOCAL machine from the repo root
scp podman-compose.yml YOUR_USER@YOUR_VPS_IP:/opt/vpn-portal/
```

You do not need to clone the repo on the VPS. This is the only file you copy from it.

### 3.3 Create the .env file on the VPS

This file contains secrets; create it directly on the VPS and never commit it.

```bash
# On the VPS
nano /opt/vpn-portal/.env
```

Paste and fill in:

```dotenv
# Flask
FLASK_APP=app
FLASK_ENV=production
SECRET_KEY=<run: python3 -c "import secrets; print(secrets.token_hex(32))">

# Database (path inside the container volume - do not change)
DATABASE_URL=sqlite:////data/vpn_portal.db

# WireGuard server info
WG_SERVER_PUBLIC_KEY=<content of: sudo cat /etc/wireguard/server_public_key>
WG_SERVER_ENDPOINT=vpn.yourdomain.com:51820
WG_DNS=1.1.1.1
WG_SUBNET=10.0.0.0/24
WG_SERVER_IP=10.0.0.1
WG_INTERFACE=wg0

# Production: must be false
WG_DEV_MODE=false

# Rate limiting
RATELIMIT_STORAGE_URL=memory://

# Admin user seeded on first boot
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<a strong password>
```

Lock down the file:

```bash
chmod 600 /opt/vpn-portal/.env
```

---

## Step 4 - VPS: Nginx and TLS

### 4.1 Install the Nginx config

Edit `nginx.conf` in your repo: replace every occurrence of `vpn.example.com`
with your real domain. Then copy it to the VPS:

```bash
# On your LOCAL machine
scp nginx.conf YOUR_USER@YOUR_VPS_IP:/tmp/vpn-portal.conf

# On the VPS
sudo mv /tmp/vpn-portal.conf /etc/nginx/conf.d/vpn-portal.conf
sudo nginx -t
sudo systemctl enable --now nginx
```

Open HTTP and HTTPS in the firewall:

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### 4.2 Get a Let's Encrypt TLS certificate

Your DNS A record must point to the VPS before running this.

```bash
sudo certbot --nginx -d vpn.yourdomain.com
```

Certbot automatically edits the Nginx config to add certificate paths and sets up
auto-renewal via a systemd timer. Verify:

```bash
sudo systemctl status certbot-renew.timer
```

---

## Step 5 - Allow the VPS to pull the container image from ghcr.io

The image is pushed to `ghcr.io/<github-username>/<repo-name>`. By default packages
are private.

**Option A - Make the package public** (easiest, fine for an open-source project):
GitHub profile > **Packages** > select your package > **Package settings > Change visibility > Public**

**Option B - Log in to ghcr.io on the VPS** (for private repos):

```bash
# Create a GitHub Personal Access Token with read:packages scope
echo "YOUR_GITHUB_PAT" | podman login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

---

## Step 6 - First deploy

Push any commit to `main` (or re-run the Actions workflow manually).
Watch it at: **your repo > Actions tab**.

After the workflow succeeds, seed the admin user:

```bash
# On the VPS
podman exec vpn-portal flask seed-admin
```

Open `https://vpn.yourdomain.com` and log in with the credentials from your `.env`.

**Alternative: manual deploy without CI/CD**

If you prefer to build and deploy without GitHub Actions:

```bash
cd /opt/vpn-portal
podman build -t vpn-portal:latest .
podman-compose up -d
podman exec vpn-portal flask seed-admin
```

---

## What lives where

| Location | Content | How it gets there |
|---|---|---|
| **GitHub Secrets** | `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` | Set manually in GitHub UI |
| **ghcr.io** | Container image | Built and pushed by CI on every push to `main` |
| **VPS `/opt/vpn-portal/`** | `podman-compose.yml` + `.env` | `scp` once / created manually |
| **VPS `/etc/wireguard/`** | `wg0.conf` | Created manually, peers managed by app |
| **VPS `/etc/nginx/conf.d/`** | `vpn-portal.conf` | `scp` once from repo |
| **VPS Podman volume** | `vpn-portal-data` - SQLite DB at `/data/vpn_portal.db` | Created automatically on first run |
| **Source code** | Lives in the container image only | Never cloned on VPS |

---

## Day-to-day workflow after initial setup

```
git commit + git push main
        |
GitHub Actions builds new image -> pushes to ghcr.io
        |
GitHub Actions SSHes into VPS -> pulls new image -> restarts container
        |
Done. Zero manual steps.
```

Migrations run automatically on every container start (`entrypoint.sh` runs `flask db upgrade`).

---

## Useful commands on the VPS

```bash
# View running containers
podman ps

# View app logs
podman logs -f vpn-portal

# Restart the app manually
cd /opt/vpn-portal && podman-compose restart

# Run a flask CLI command
podman exec vpn-portal flask <command>

# Check WireGuard status
sudo wg show

# Check Nginx status
sudo systemctl status nginx

# Renew TLS certificate manually (normally automatic)
sudo certbot renew
```
