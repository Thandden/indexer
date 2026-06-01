#!/usr/bin/env bash
# Pull latest code and restart both apps. Run on the server after a git push.
set -euo pipefail
APP_DIR="$HOME/indexer"
export PATH="$HOME/.local/bin:$PATH"

git -C "$APP_DIR" pull
(cd "$APP_DIR" && uv sync)
sudo systemctl restart indexer-hub indexer-target
echo "redeployed. status:"
sudo systemctl --no-pager --lines=0 status indexer-hub indexer-target || true
