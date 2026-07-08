#!/usr/bin/env bash
# =============================================================================
# deploy.sh  —  Install / update the Chatwoot <-> Telegram Bridge on Ubuntu
# Usage: bash deploy.sh
# =============================================================================
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
INSTALL_DIR="/opt/chatwoot-bridge"
SERVICE_NAME="chatwoot-bridge"
SERVICE_USER="bridge"
GITHUB_REPO="https://github.com/ebanocalderon/OmniBot.git"
PYTHON="python3"

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Must run as root ──────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Run this script with sudo: sudo bash deploy.sh"

# ── 1. System packages ────────────────────────────────────────────────────────
info "Updating package index …"
apt-get update -qq

info "Installing system dependencies …"
apt-get install -y -qq git python3 python3-venv python3-pip curl

# ── 2. Dedicated service user ─────────────────────────────────────────────────
if ! id "$SERVICE_USER" &>/dev/null; then
    info "Creating system user '$SERVICE_USER' …"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# ── 3. Clone / update repo ────────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Updating existing installation …"
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning repository into $INSTALL_DIR …"
    git clone "$GITHUB_REPO" "$INSTALL_DIR"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ── 4. Python virtual environment ─────────────────────────────────────────────
info "Creating / updating Python virtual environment …"
sudo -u "$SERVICE_USER" bash -c "
    $PYTHON -m venv '$INSTALL_DIR/venv'
    '$INSTALL_DIR/venv/bin/pip' install --upgrade pip -q
    '$INSTALL_DIR/venv/bin/pip' install -r '$INSTALL_DIR/requirements.txt' -q
"

# ── 5. .env file ──────────────────────────────────────────────────────────────
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    warn ".env not found — copying .env.example"
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    warn "IMPORTANT: Edit $INSTALL_DIR/.env and fill in your secrets, then run:"
    warn "  sudo systemctl restart $SERVICE_NAME"
else
    info ".env already exists — skipping copy"
fi

# ── 6. Install systemd service ────────────────────────────────────────────────
info "Installing systemd service …"
cp "$INSTALL_DIR/deploy/chatwoot-bridge.service" "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# ── 7. Start / restart service ────────────────────────────────────────────────
info "Starting $SERVICE_NAME …"
systemctl restart "$SERVICE_NAME"
sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    info "✅ $SERVICE_NAME is running!"
    info "Health check: curl http://10.0.0.41:8000/health"
else
    warn "Service may not be running. Check with:"
    warn "  sudo journalctl -u $SERVICE_NAME -n 50 --no-pager"
fi

# ── 8. Firewall reminder ──────────────────────────────────────────────────────
warn "Firewall: make sure port 8000 is open if needed:"
warn "  sudo ufw allow 8000/tcp"

info "Deployment complete!"
