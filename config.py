"""Central config loaded from environment / .env."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str) -> int | None:
    val = os.getenv(name, "").strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


TOKEN: str = os.getenv("DISCORD_TOKEN", "")
GUILD_ID: int | None = _int("GUILD_ID")
PREFIX: str = os.getenv("PREFIX", "!")

TICKET_CATEGORY_ID: int | None = _int("TICKET_CATEGORY_ID")
TICKET_STAFF_ROLE_ID: int | None = _int("TICKET_STAFF_ROLE_ID")
TICKET_LOG_CHANNEL_ID: int | None = _int("TICKET_LOG_CHANNEL_ID")
TICKET_PANEL_TITLE: str = os.getenv("TICKET_PANEL_TITLE", "PvPHaven Support")
TICKET_PANEL_OPTIONS: str = os.getenv(
    "TICKET_PANEL_OPTIONS",
    "support:Support:🎫,report:Report Player:🚨,appeal:Ban Appeal:⚖️,other:Other:📦",
)

WEBSITE_URL: str = os.getenv("WEBSITE_URL", "https://pvphaven.example.com").rstrip("/")
LINK_API_KEY: str = os.getenv("LINK_API_KEY", "CHANGE_ME")
LINK_API_HOST: str = os.getenv("LINK_API_HOST", "0.0.0.0")
LINK_API_PORT: int = int(os.getenv("LINK_API_PORT", "8090") or 8090)
LINK_CODE_TTL_MINUTES: int = int(os.getenv("LINK_CODE_TTL_MINUTES", "10") or 10)

WELCOME_CHANNEL_ID: int | None = _int("WELCOME_CHANNEL_ID")
AUTOROLE_ID: int | None = _int("AUTOROLE_ID")
LOG_CHANNEL_ID: int | None = _int("LOG_CHANNEL_ID")
BOT_ACTIVITY: str = os.getenv("BOT_ACTIVITY", "PvPHaven | /help")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pvp_haven.db")
