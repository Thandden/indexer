#!/usr/bin/env bash
# Bootstrap the indexer test rig on a fresh Lightsail/EC2 instance.
# Tested on Ubuntu 22.04/24.04. Run as a sudo-capable user (e.g. 'ubuntu').
#
#   curl -fsSL https://raw.githubusercontent.com/Thandden/indexer/main/deploy/bootstrap.sh | bash
# or: scp this up and `bash bootstrap.sh`
#
# Installs uv + Caddy, clones the repo, runs both Flask apps as systemd
# services (auto-restart, survive reboot), and serves them over HTTPS via Caddy.
set -euo pipefail

REPO="https://github.com/Thandden/indexer.git"
APP_DIR="$HOME/indexer"
HUB_DOMAIN="ozymandias.space"
TARGET_DOMAIN="coffeeclubguide.site"

echo "==> system packages"
sudo apt-get update -y
sudo apt-get install -y git curl debian-keyring debian-archive-keyring apt-transport-https

echo "==> uv"
if ! command -v uv >/dev/null; then
	curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
UV="$(command -v uv)"

echo "==> clone / update repo"
if [ -d "$APP_DIR/.git" ]; then
	git -C "$APP_DIR" pull
else
	git clone "$REPO" "$APP_DIR"
fi

echo "==> python deps"
cd "$APP_DIR"
"$UV" sync

echo "==> Caddy (reverse proxy + auto HTTPS)"
if ! command -v caddy >/dev/null; then
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
		| sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
	curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
		| sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
	sudo apt-get update -y
	sudo apt-get install -y caddy
fi
sudo cp "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
sudo systemctl restart caddy

echo "==> systemd services for both apps"
USER_NAME="$(whoami)"

sudo tee /etc/systemd/system/indexer-hub.service >/dev/null <<EOF
[Unit]
Description=Indexer hub app (${HUB_DOMAIN})
After=network.target

[Service]
User=${USER_NAME}
WorkingDirectory=${APP_DIR}
Environment=BASE_URL=https://${HUB_DOMAIN}
ExecStart=${UV} run python app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/indexer-target.service >/dev/null <<EOF
[Unit]
Description=Indexer target app (${TARGET_DOMAIN})
After=network.target

[Service]
User=${USER_NAME}
WorkingDirectory=${APP_DIR}
Environment=TARGET_BASE_URL=https://${TARGET_DOMAIN}
ExecStart=${UV} run python target_app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now indexer-hub indexer-target

echo
echo "==> done. status:"
sudo systemctl --no-pager --lines=0 status indexer-hub indexer-target caddy || true
echo
echo "Hub:    https://${HUB_DOMAIN}    (-> :5000)"
echo "Target: https://${TARGET_DOMAIN} (-> :5001)"
echo
echo "Caddy will issue HTTPS certs automatically ONCE the domains' DNS A records"
echo "point at this server's public IP. Until then you'll see cert errors."
echo
echo "Redeploy after a push:  bash ${APP_DIR}/deploy/redeploy.sh"
