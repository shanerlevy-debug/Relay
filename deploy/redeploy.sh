#!/usr/bin/env bash
# Pull repo updates and reload the bridge if anything material changed.
# Driven by cron (every 5 min) AND by the GitHub Actions SSH workflow on merge.
# Idempotent — safe to run frequently. Exits 0 silently when nothing changed.

set -euo pipefail

APP_DIR=/opt/slack-cma-bridge
SERVICE=slack-cma-bridge

cd "$APP_DIR"

BEFORE=$(sudo -u slackbridge git rev-parse HEAD)
sudo -u slackbridge git fetch --quiet origin main
sudo -u slackbridge git reset --quiet --hard origin/main
AFTER=$(sudo -u slackbridge git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
  exit 0
fi

echo "[$(date -Is)] redeploy: $BEFORE -> $AFTER"
CHANGED=$(sudo -u slackbridge git diff --name-only "$BEFORE..$AFTER")
echo "[$(date -Is)] changed files:"
echo "$CHANGED" | sed 's/^/  /'

# Reinstall deps only when requirements changed.
if echo "$CHANGED" | grep -qx 'requirements.txt'; then
  echo "[$(date -Is)] requirements.txt changed — reinstalling deps"
  sudo -u slackbridge "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
fi

# Reinstall systemd unit if it changed.
if echo "$CHANGED" | grep -qx 'deploy/slack-cma-bridge.service'; then
  echo "[$(date -Is)] systemd unit changed — reinstalling"
  install -m 644 "$APP_DIR/deploy/slack-cma-bridge.service" /etc/systemd/system/
  systemctl daemon-reload
fi

echo "[$(date -Is)] restarting $SERVICE"
systemctl restart "$SERVICE"
echo "[$(date -Is)] redeploy done"
