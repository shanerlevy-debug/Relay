# Relay

A single-workspace Slack bot that routes messages to multiple Claude Managed Agents (CMAs) by slug.

```
@Relay alfred summarize this thread
@Relay researcher what are the latest papers on X
/ask researcher who founded Anthropic?
```

No public URL, no OAuth, no multi-tenancy. ~250 lines of Python + Slack's Socket Mode. Single Slack workspace, N agents, thread continuity via SQLite.

For the polished deployment runbook (the client-facing Blueprint deliverable), see [`docs/RUNBOOK.md`](docs/RUNBOOK.md) (or the rendered [`docs/RUNBOOK.pdf`](docs/RUNBOOK.pdf)).

For the architectural rationale, see `../slack-cma-direct-feasibility.md`. For the full handoff context, see `../slack-cma-multi-agent-mvp-handoff.md`.

## Local demo (Windows)

Prerequisites:
- Python 3.10+
- A Slack workspace where you have admin
- An Anthropic API key with CMA beta access
- At least 2 CMAs created in the Anthropic Console (you need their `agent_*` IDs)

Setup:
```powershell
.\scripts\setup.ps1
copy .env.example .env
copy agents.yaml.example agents.yaml
# Edit .env with your tokens (Slack bot, Slack app, Anthropic API key).
# Edit agents.yaml with your agent_ids + slugs.
.\scripts\run-bridge.ps1
```

`.env` is gitignored. On a Lightsail deploy this same file lives at `/etc/slack-cma-bridge/bridge.env` (chmod 600, root:slackbridge) and is loaded by the systemd unit — same shape, same secrets, just a different path.

You should see:
```
relay starting; 2 agents loaded; default=alfred; slugs=['alfred', 'researcher']
```

On the Slack app's **Settings → Socket Mode** page, the connection indicator flips green within a few seconds.

## Slack app setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From Manifest**.
2. Paste `slack-app-manifest.yaml`.
3. **Basic Information → App-Level Tokens → Generate** with scope `connections:write`. Save the `xapp-...` token as `SLACK_APP_TOKEN` in `.env`.
4. **Install to Workspace**. Save the Bot User OAuth Token (`xoxb-...`) as `SLACK_BOT_TOKEN` in `.env`.
5. In a test channel: `/invite @Relay`.

## Smoke tests

| Step | What to do | Expected |
|---|---|---|
| Explicit slug | `@Relay alfred ping` | Placeholder appears, then edits to alfred's reply within ~5s |
| Default routing | `@Relay hello there` (no slug) | Routes to default agent |
| Thread continuity | Reply in the same thread without re-tagging | Same agent answers, with memory of prior turn |
| DM | DM the bot directly | Routes to default agent |
| Slash command | `/ask researcher who founded Anthropic?` | Routes to researcher |

## Editing agents

Add or remove agents by editing `agents.yaml`:

```yaml
environment_id: env_018YFpVVwTNWu8TRef2jfbvq
default: alfred

agents:
  alfred:
    anthropic_agent_id: agent_0112NyBraSMpk7Tjub9mMAWh
    description: General-purpose assistant.

  researcher:
    anthropic_agent_id: agent_011CaPqFYYtWssBNheHKPA5g
    description: Deep research and synthesis.
```

Locally: stop the bridge (Ctrl+C), edit, restart.
On a deployed Lightsail box: see [Deploy](#deploy) below — agents are managed via git-ops.

## Deploy

The deployed shape: one Ubuntu Lightsail instance ($3.50/mo) running the bridge under systemd, pulling agent config from this repo every 5 minutes.

```
/opt/slack-cma-bridge/        git clone of this repo (read-write by slackbridge user)
  ├── bridge.py
  ├── agents.yaml             edited via git-ops; pulled fresh by redeploy
  ├── .venv/
  └── deploy/
       ├── slack-cma-bridge.service
       ├── bootstrap.sh
       └── redeploy.sh

/etc/slack-cma-bridge/
  └── bridge.env              tokens (chmod 640, root:slackbridge) — NEVER committed

/var/lib/slack-cma-bridge/
  └── threads.db              SQLite, persists across deploys
```

### One-time provisioning

1. Create a $3.50/mo Lightsail instance (Ubuntu 22.04, any region near you).
2. SSH in.
3. ```bash
   sudo git clone https://github.com/shanerlevy-debug/Relay.git /opt/slack-cma-bridge
   cd /opt/slack-cma-bridge
   sudo bash deploy/bootstrap.sh
   sudo vi /etc/slack-cma-bridge/bridge.env       # paste real tokens
   sudo systemctl enable --now slack-cma-bridge
   sudo journalctl -u slack-cma-bridge -f
   ```

Bootstrap installs the systemd unit, creates the `slackbridge` user, sets up a venv, installs deps, and registers a cron entry that runs `redeploy.sh` every 5 minutes.

### Editing agents post-deploy (git-ops)

```
edit agents.yaml in this repo → PR → merge to main
                                       │
                                       ├─► GitHub Action SSHes to the box and
                                       │   runs redeploy.sh (instant fast-path,
                                       │   optional — needs SSH key secret)
                                       └─► Cron on the box pulls every 5 min
                                           and runs redeploy.sh (always-on fallback)
```

`redeploy.sh` does a `git fetch + reset --hard origin/main`, reinstalls deps if `requirements.txt` changed, and `systemctl restart`s the bridge. **Local edits to `/opt/slack-cma-bridge/` are destructive** — anything not in the repo is wiped on the next pull. Edit in the repo only.

To wire the GitHub Action fast-path: in repo Settings → Secrets and variables → Actions, add `LIGHTSAIL_HOST`, `LIGHTSAIL_USER`, `LIGHTSAIL_SSH_KEY`. Without these the workflow no-ops cleanly — cron still picks up the change within 5 min.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `agents config not found at ./agents.yaml` | `copy agents.yaml.example agents.yaml` and fill in agent_ids |
| Socket Mode shows red in Slack | `SLACK_APP_TOKEN` is wrong or missing `connections:write` scope |
| `@mention` produces no log line | Bot isn't invited to that channel — `/invite @Relay` |
| Bot replies `_(no reply from agent)_` every time | Set `LOG_EVENT_TYPES=1` in `.env` and restart — confirm what event types the SDK is emitting |
| `ModuleNotFoundError` on startup | Re-run `.\scripts\setup.ps1` to install deps into the venv |

## File layout

```
bridge/
├── bridge.py                  # The bridge (~250 lines)
├── agents.yaml.example        # Copy to agents.yaml and fill in
├── .env.example               # Copy to .env and fill in
├── requirements.txt
├── slack-app-manifest.yaml    # Paste at Slack app creation
├── scripts/
│   ├── setup.ps1              # Create venv, install deps (Windows)
│   └── run-bridge.ps1         # Load .env, run bridge (Windows)
├── deploy/                    # Lightsail deploy artifacts (Phase 2)
│   ├── bootstrap.sh
│   ├── slack-cma-bridge.service
│   └── redeploy.sh
└── .github/workflows/
    └── redeploy-on-merge.yml  # Optional: SSH-push redeploy on agents.yaml change
```
