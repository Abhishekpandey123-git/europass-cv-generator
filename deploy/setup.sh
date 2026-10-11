#!/usr/bin/env bash
# One-time setup of the Europass CV service on a fresh Ubuntu 22.04/24.04 server.
#
#   sudo bash deploy/setup.sh [your-domain.com]
#
# Without a domain it serves plain HTTP on the server's IP (testing only).
# Re-running is safe.

set -euo pipefail

DOMAIN="${1:-}"
APP_USER="europass"
APP_DIR="/opt/europass-cv"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip nginx rsync sqlite3 curl \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev \
    fonts-liberation ufw

echo "==> Creating service user and folders"
id -u "$APP_USER" &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR"

echo "==> Copying the application"
rsync -a --delete \
    --exclude venv --exclude .venv --exclude __pycache__ --exclude .git \
    --exclude data --exclude output --exclude .env \
    "$SRC_DIR"/ "$APP_DIR"/
mkdir -p "$APP_DIR/data" "$APP_DIR/output"

echo "==> Python environment"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# --- .env: created once, then left alone so upgrades never lose the keys ----
if [[ ! -f "$APP_DIR/.env" ]]; then
    echo "==> Creating .env with fresh secrets"
    ADMIN_PW="$(python3 -c 'import secrets;print(secrets.token_urlsafe(12))')"
    API_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
    PUBLIC="${DOMAIN:+https://$DOMAIN}"
    PUBLIC="${PUBLIC:-http://$(curl -s --max-time 5 ifconfig.me || echo localhost)}"
    cat > "$APP_DIR/.env" <<ENV
ADMIN_PASSWORD=$ADMIN_PW
API_KEYS=$API_KEY
PUBLIC_URL=$PUBLIC
HOST=127.0.0.1
PORT=8000
DATA_DIR=$APP_DIR/data
ENV
    NEW_ENV=1
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"
chmod 700 "$APP_DIR/data"

echo "==> systemd service"
sed "s|__APP_DIR__|$APP_DIR|g; s|__APP_USER__|$APP_USER|g" \
    "$SRC_DIR/deploy/europass-cv.service" > /etc/systemd/system/europass-cv.service
systemctl daemon-reload
systemctl enable --now europass-cv
sleep 2

echo "==> nginx"
SERVER_NAME="${DOMAIN:-_}"
sed "s|__SERVER_NAME__|$SERVER_NAME|g" "$SRC_DIR/deploy/nginx.conf" \
    > /etc/nginx/sites-available/europass-cv
ln -sf /etc/nginx/sites-available/europass-cv /etc/nginx/sites-enabled/europass-cv
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "==> Firewall"
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null

if [[ -n "$DOMAIN" ]]; then
    echo "==> HTTPS certificate for $DOMAIN"
    apt-get install -y -qq certbot python3-certbot-nginx
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        --register-unsafely-without-email --redirect || \
        echo "!! certbot failed - check that $DOMAIN points to this server, then run: certbot --nginx -d $DOMAIN"
fi

echo
echo "================================================================"
systemctl is-active --quiet europass-cv && echo "Service: running" || { echo "Service: FAILED"; journalctl -u europass-cv -n 20 --no-pager; }
if [[ -n "${NEW_ENV:-}" ]]; then
    echo
    echo "Save these now - they are in $APP_DIR/.env"
    grep -E '^(ADMIN_PASSWORD|API_KEYS|PUBLIC_URL)=' "$APP_DIR/.env"
else
    echo "Existing .env kept unchanged."
fi
echo
echo "Open:      $(grep ^PUBLIC_URL "$APP_DIR/.env" | cut -d= -f2-)"
echo "Logs:      journalctl -u europass-cv -f"
echo "Restart:   systemctl restart europass-cv"
echo "================================================================"
