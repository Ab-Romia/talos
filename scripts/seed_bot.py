"""Idempotently seed the Slack/MCP bot's identity rows.

Creates (or finds) the bot service-user, its workspace, and default channel,
plus the system permission roles, then prints the UUIDs to put in `.env`
(BOT__BOT_USER_ID / BOT__DEFAULT_WORKSPACE_ID / BOT__DEFAULT_CHANNEL_ID and
SLACK__DEFAULT_TALOS_USER_ID).

Run from the repo root against the configured database:

    PYTHONPATH=src:. python scripts/seed_bot.py
"""
from sqlalchemy import select, text

from database import Base, engine, SessionLocal

# Import every model module so create_all sees all tables.
from utils.import_sa_models import import_sa_models

import_sa_models()

BOT_USERNAME = "talos-bot"
WORKSPACE_NAME = "talos"
CHANNEL_NAME = "general"


def main() -> None:
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext;"))
        conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto";'))
        conn.commit()

    Base.metadata.create_all(engine)

    from auth.model import User
    from permissions.model import Role, STATIC_ROLE_ID, system_roles
    from workspace.model import Channel, Workspace

    with SessionLocal() as db:
        if db.get(Role, STATIC_ROLE_ID) is None:
            db.add_all(system_roles())
            db.flush()

        bot = db.scalar(select(User).where(User.username == BOT_USERNAME))
        if bot is None:
            bot = User(
                username=BOT_USERNAME,
                primary_email=f"{BOT_USERNAME}@example.com",
                signup_complete=True,
                name="Talos Bot",
                data={},
            )
            db.add(bot)
            db.flush()

        ws = db.scalar(select(Workspace).where(Workspace.name == WORKSPACE_NAME))
        if ws is None:
            ws = Workspace(name=WORKSPACE_NAME, owner=bot)
            db.add(ws)
            db.flush()

        ch = db.scalar(
            select(Channel).where(
                Channel.name == CHANNEL_NAME, Channel.workspace_id == ws.id
            )
        )
        if ch is None:
            ch = Channel(name=CHANNEL_NAME, workspace_id=ws.id)
            db.add(ch)
            db.flush()

        db.commit()

        print(f"BOT__BOT_USER_ID={bot.id}")
        print(f"SLACK__DEFAULT_TALOS_USER_ID={bot.id}")
        print(f"BOT__DEFAULT_WORKSPACE_ID={ws.id}")
        print(f"BOT__DEFAULT_CHANNEL_ID={ch.id}")


if __name__ == "__main__":
    main()
