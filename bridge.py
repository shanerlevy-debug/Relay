"""Relay — multi-agent Slack <-> Claude Managed Agents bridge.

Slack delivers events over an outbound WebSocket (Socket Mode). The bridge
parses an agent slug, looks up its Anthropic agent_id, spins up (or chains)
a CMA session, streams the reply back, and edits a Slack placeholder with
the result. SQLite pins (channel_id, thread_ts) -> agent_slug so threaded
follow-ups keep talking to the same agent and carry session memory via
parent_session_id chaining.

No auth, no identity, no multi-tenant. Demo-quality.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import sys
from pathlib import Path

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("relay")

LOG_EVENT_TYPES = os.environ.get("LOG_EVENT_TYPES", "0") == "1"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(os.environ.get("AGENTS_CONFIG", "./agents.yaml"))
DB_PATH = Path(os.environ.get("DB_PATH", "./threads.db"))

if not CONFIG_PATH.exists():
    sys.exit(f"agents config not found at {CONFIG_PATH} — copy agents.yaml.example to agents.yaml")

with CONFIG_PATH.open(encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

ENVIRONMENT_ID = CFG.get("environment_id")
if not ENVIRONMENT_ID or ENVIRONMENT_ID == "env_replace_me":
    sys.exit(f"environment_id is required in {CONFIG_PATH} (set to a real env_... id)")

AGENTS = {slug.lower(): spec for slug, spec in (CFG.get("agents") or {}).items()}
if not AGENTS:
    sys.exit(f"no agents defined in {CONFIG_PATH}")

DEFAULT_SLUG = (CFG.get("default") or "").lower()
if DEFAULT_SLUG not in AGENTS:
    sys.exit(f"default agent {DEFAULT_SLUG!r} not in agents: {list(AGENTS)}")

for slug, spec in AGENTS.items():
    if not spec.get("anthropic_agent_id"):
        sys.exit(f"agent {slug!r} missing anthropic_agent_id")

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
DB = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
DB.execute("PRAGMA journal_mode=WAL;")
DB.execute("""
    CREATE TABLE IF NOT EXISTS slack_threads (
        channel_id      TEXT NOT NULL,
        thread_ts       TEXT NOT NULL,
        agent_slug      TEXT NOT NULL,
        last_session_id TEXT,
        updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (channel_id, thread_ts)
    )
""")

claude = Anthropic()
app = App(token=os.environ["SLACK_BOT_TOKEN"])

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

_MENTION_RE = re.compile(r"^<@[A-Z0-9]+>\s*")


def pick_agent(text: str, channel_id: str, thread_ts: str) -> tuple[str, str, str]:
    """Return (slug, prompt, reason). Priority: thread_pin > explicit_slug > default."""
    pinned = DB.execute(
        "SELECT agent_slug FROM slack_threads WHERE channel_id=? AND thread_ts=?",
        (channel_id, thread_ts),
    ).fetchone()
    cleaned = _MENTION_RE.sub("", text or "").strip()

    if pinned:
        return pinned[0], cleaned, "thread_pin"

    parts = cleaned.split(None, 1)
    if parts and parts[0].lower() in AGENTS:
        return parts[0].lower(), parts[1] if len(parts) > 1 else "", "explicit"

    return DEFAULT_SLUG, cleaned, "default"


# ---------------------------------------------------------------------------
# CMA invocation
# ---------------------------------------------------------------------------

def _extract_text(content) -> str:
    """Coerce the various agent.message content shapes into a string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for c in content:
            text = getattr(c, "text", None)
            if text is None and isinstance(c, dict):
                text = c.get("text")
            if text:
                out.append(text)
        return "".join(out)
    text = getattr(content, "text", None)
    return text or ""


def invoke_agent(slug: str, prompt: str, channel_id: str, thread_ts: str) -> str:
    """Create or reuse a CMA session and return the collected reply text.

    First turn in a Slack thread: create a fresh session, persist its ID.
    Follow-up turns: reuse the same session_id — CMA preserves conversation
    history within a session, so the agent remembers prior turns automatically.
    """
    agent_id = AGENTS[slug]["anthropic_agent_id"]
    row = DB.execute(
        "SELECT last_session_id FROM slack_threads WHERE channel_id=? AND thread_ts=?",
        (channel_id, thread_ts),
    ).fetchone()
    session_id = row[0] if row and row[0] else None

    if session_id is None:
        session = claude.beta.sessions.create(
            agent=agent_id,
            environment_id=ENVIRONMENT_ID,
        )
        session_id = session.id
        log.info("session created slug=%s session_id=%s", slug, session_id)
    else:
        log.info("session reused slug=%s session_id=%s", slug, session_id)

    chunks: list[str] = []

    # Per the CMA SDK contract: open the stream BEFORE sending so we don't
    # miss early events. Terminal condition is session.status_terminated, or
    # session.status_idle with stop_reason.type != "requires_action".
    with claude.beta.sessions.events.stream(session_id=session_id) as stream:
        claude.beta.sessions.events.send(
            session_id,
            events=[{
                "type": "user.message",
                "content": [{"type": "text", "text": prompt}],
            }],
        )

        for ev in stream:
            ev_type = getattr(ev, "type", "") or ""
            if LOG_EVENT_TYPES:
                log.info("stream ev type=%r", ev_type)

            if ev_type == "agent.message":
                chunks.append(_extract_text(getattr(ev, "content", None)))
                continue

            if ev_type == "session.status_terminated":
                break

            if ev_type == "session.status_idle":
                stop_reason = getattr(ev, "stop_reason", None)
                reason_type = getattr(stop_reason, "type", None) if stop_reason else None
                if reason_type == "requires_action":
                    log.warning("session %s idled awaiting tool confirmation; returning partial reply", session_id)
                break

    DB.execute(
        """
        INSERT INTO slack_threads(channel_id, thread_ts, agent_slug, last_session_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(channel_id, thread_ts) DO UPDATE SET
            agent_slug = excluded.agent_slug,
            last_session_id = excluded.last_session_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        (channel_id, thread_ts, slug, session_id),
    )

    return "".join(chunks).strip() or "_(no reply from agent)_"


# ---------------------------------------------------------------------------
# Slack handlers
# ---------------------------------------------------------------------------

SLACK_TEXT_LIMIT = 3500  # safe display ceiling; Slack hard limit is 40000


def _chunk_text(text: str, max_chars: int = SLACK_TEXT_LIMIT) -> list[str]:
    """Split text into Slack-safe chunks, preferring paragraph/line/word boundaries."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        split_at = -1
        for sep in ("\n\n", "\n", " "):
            idx = remaining.rfind(sep, 0, max_chars)
            if idx > max_chars // 2:
                split_at = idx
                break
        if split_at < 0:
            chunks.append(remaining[:max_chars])
            remaining = remaining[max_chars:]
        else:
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _post_reply(channel_id: str, placeholder_ts: str, anchor_ts: str, reply: str) -> None:
    """Update the placeholder with the reply, falling back to threaded chunks for long output."""
    chunks = _chunk_text(reply)
    try:
        app.client.chat_update(channel=channel_id, ts=placeholder_ts, text=chunks[0])
    except SlackApiError as e:
        log.warning("chat_update failed (%s); posting as thread reply instead", e.response.get("error"))
        app.client.chat_postMessage(channel=channel_id, thread_ts=anchor_ts, text=chunks[0])
    for chunk in chunks[1:]:
        app.client.chat_postMessage(channel=channel_id, thread_ts=anchor_ts, text=chunk)


def handle_event(text: str, channel_id: str, slack_thread_ts: str | None) -> None:
    """Drive one user turn end-to-end.

    slack_thread_ts is the Slack thread to reply in (for @mentions, DMs, threaded
    follow-ups). For slash commands it's None — we post top-level and use the
    placeholder's own ts as the pin/anchor for any later replies in its thread.
    """
    try:
        placeholder = app.client.chat_postMessage(
            channel=channel_id,
            thread_ts=slack_thread_ts,
            text="_thinking…_",
        )
    except SlackApiError:
        log.exception("placeholder chat_postMessage failed")
        return

    pin_key = slack_thread_ts or placeholder["ts"]
    anchor_ts = slack_thread_ts or placeholder["ts"]

    slug, prompt, reason = pick_agent(text, channel_id, pin_key)
    log.info("routed slug=%s reason=%s channel=%s pin=%s", slug, reason, channel_id, pin_key)

    if not prompt:
        slug_list = ", ".join(f"`{s}`" for s in AGENTS)
        try:
            app.client.chat_update(
                channel=channel_id,
                ts=placeholder["ts"],
                text=(
                    f"Hi! I routed to *{slug}* ({reason}) but didn't catch a question. "
                    f"Try `@Relay <slug> <message>` — available slugs: {slug_list}"
                ),
            )
        except SlackApiError:
            log.exception("chat_update for empty-prompt help failed")
        return

    try:
        app.client.chat_update(channel=channel_id, ts=placeholder["ts"], text=f"_{slug} is thinking…_")
    except SlackApiError:
        pass

    try:
        reply = invoke_agent(slug, prompt, channel_id, pin_key)
    except Exception as e:
        log.exception("invoke_agent failed slug=%s", slug)
        reply = f"_(agent {slug} errored: `{type(e).__name__}: {e}`)_"

    _post_reply(channel_id, placeholder["ts"], anchor_ts, reply)


@app.event("app_mention")
def on_app_mention(event, logger):
    channel_id = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    handle_event(event.get("text", ""), channel_id, thread_ts)


@app.event("message")
def on_message(event, logger):
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return
    if event.get("channel_type") == "im":
        channel_id = event["channel"]
        thread_ts = event.get("thread_ts") or event["ts"]
        handle_event(event.get("text", ""), channel_id, thread_ts)
        return
    # Channel messages: only respond inside a thread we've already pinned.
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return
    channel_id = event["channel"]
    pinned = DB.execute(
        "SELECT 1 FROM slack_threads WHERE channel_id=? AND thread_ts=?",
        (channel_id, thread_ts),
    ).fetchone()
    if pinned:
        handle_event(event.get("text", ""), channel_id, thread_ts)


@app.command(os.environ.get("SLASH_COMMAND", "/ask"))
def on_slash(ack, command):
    ack()
    handle_event(command.get("text", ""), command["channel_id"], slack_thread_ts=None)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info(
        "relay starting; %d agents loaded; default=%s; slugs=%s",
        len(AGENTS), DEFAULT_SLUG, list(AGENTS),
    )
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
