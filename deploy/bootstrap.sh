#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 22.04 Lightsail instance.
# Run as root or via sudo. Idempotent — safe to re-run.
#
# After completion:
#   1. Edit /etc/slack-cma-bridge/bridge.env with real tokens
#   2. Verify /opt/slack-cma-bridge/agents.yaml has your agent_ids + environment_id
#   3. sudo systemctl enable --now slack-cma-bridge
#   4. sudo journalctl -u slack-cma-bridge -f

set -euo pipefail

APP_DIR=/opt/slack-cma-bridge
ETC_DIR=/etc/slack-cma-bridge
VAR_DIR=/var/lib/slack-cma-bridge
LOG_FILE=/var/log/slack-cma-bridge-redeploy.log
REPO_URL="${REPO_URL:-https://github.com/shanerlevy-debug/Relay.git}"

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "bootstrap.sh must be run as root (try: sudo $0)" >&2
  exit 1
fi

echo "==> Installing packages"
apt-get update -qq
apt-get install -y -qq python3-venv git

echo "==> Creating service user"
if ! id slackbridge >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin slackbridge
fi

echo "==> Cloning $REPO_URL to $APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --quiet "$REPO_URL" "$APP_DIR"
fi
chown -R slackbridge:slackbridge "$APP_DIR"

echo "==> Setting up Python venv"
if [ ! -d "$APP_DIR/.venv" ]; then
  sudo -u slackbridge python3 -m venv "$APP_DIR/.venv"
fi
sudo -u slackbridge "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u slackbridge "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "==> Creating runtime dirs"
mkdir -p "$ETC_DIR" "$VAR_DIR"
chown slackbridge:slackbridge "$VAR_DIR"
chmod 750 "$ETC_DIR"
touch "$LOG_FILE"
chown slackbridge:slackbridge "$LOG_FILE"

echo "==> Writing env file scaffold"
if [ ! -f "$ETC_DIR/bridge.env" ]; then
  cat > "$ETC_DIR/bridge.env" <<'EOF'
# Edit with real tokens. Mode 640 root:slackbridge — systemd reads as root and
# drops privileges to slackbridge for the bridge process itself.

SLACK_BOT_TOKEN=xoxb-replace-me
SLACK_APP_TOKEN=xapp-replace-me
ANTHROPIC_API_KEY=sk-ant-replace-me

# Service paths (override bridge.py defaults).
AGENTS_CONFIG=/opt/slack-cma-bridge/agents.yaml
DB_PATH=/var/lib/slack-cma-bridge/threads.db
SLASH_COMMAND=/ask
LOG_EVENT_TYPES=0
EOF
  chown root:slackbridge "$ETC_DIR/bridge.env"
  chmod 640 "$ETC_DIR/bridge.env"
  echo "    WROTE $ETC_DIR/bridge.env — edit with real tokens before starting the service"
else
  echo "    $ETC_DIR/bridge.env already exists, leaving alone"
fi

echo "==> Installing systemd unit"
install -m 644 "$APP_DIR/deploy/slack-cma-bridge.service" /etc/systemd/system/
systemctl daemon-reload

echo "==> Installing redeploy cron (every 5 min)"
cat > /etc/cron.d/slack-cma-bridge-redeploy <<EOF
# Git-ops: pull repo updates and reload bridge if anything changed.
# Belt-and-suspenders fallback to GitHub Actions SSH push.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/5 * * * * root $APP_DIR/deploy/redeploy.sh >> $LOG_FILE 2>&1
EOF
chmod 644 /etc/cron.d/slack-cma-bridge-redeploy

chmod +x "$APP_DIR/deploy/redeploy.sh"

echo ""
echo "==> Bootstrap complete. Next steps:"
echo "  1. sudo vi $ETC_DIR/bridge.env       # paste real tokens"
echo "  2. cat $APP_DIR/agents.yaml          # verify agent_ids + environment_id"
echo "  3. sudo systemctl enable --now slack-cma-bridge"
echo "  4. sudo journalctl -u slack-cma-bridge -f"
