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


def _bool(name: str, default: bool = True) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _int_list(name: str) -> list[int]:
    out: list[int] = []
    for part in os.getenv(name, "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


TOKEN: str = os.getenv("DISCORD_TOKEN", "")
GUILD_ID: int | None = _int("GUILD_ID")
PREFIX: str = os.getenv("PREFIX", "!")

# Privileged intents. These MUST also be enabled in the Discord Developer
# Portal (application -> Bot -> Privileged Gateway Intents), otherwise
# Discord rejects the connection with PrivilegedIntentsRequired.
# Only disable as a last resort (welcome/autorole + member lookups degrade).
MEMBERS_INTENT: bool = _bool("MEMBERS_INTENT", True)
MESSAGE_CONTENT_INTENT: bool = _bool("MESSAGE_CONTENT_INTENT", True)

TICKET_CATEGORY_ID: int | None = _int("TICKET_CATEGORY_ID")
TICKET_LOG_CHANNEL_ID: int | None = _int("TICKET_LOG_CHANNEL_ID")
# All staff ranks that can see + handle tickets (comma-separated role IDs).
# The old single TICKET_STAFF_ROLE_ID still works and is merged in.
TICKET_STAFF_ROLE_ID: int | None = _int("TICKET_STAFF_ROLE_ID")
TICKET_STAFF_ROLE_IDS: list[int] = list(dict.fromkeys(
    _int_list("TICKET_STAFF_ROLE_IDS") + ([TICKET_STAFF_ROLE_ID] if TICKET_STAFF_ROLE_ID else [])
))
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

# --- Anti-alt / VPN verification ---
# Website forwards the user's IP on /verify; bot checks VPN/proxy + flags
# duplicate accounts. Flag-only by default; set BLOCK_VPN_LINKS=true to reject.
VPN_CHECK_PROVIDER: str = os.getenv("VPN_CHECK_PROVIDER", "off").strip().lower()  # off | proxycheck | ipqualityscore
PROXYCHECK_KEY: str = os.getenv("PROXYCHECK_KEY", "")
IPQUALITYSCORE_KEY: str = os.getenv("IPQUALITYSCORE_KEY", "")
BLOCK_VPN_LINKS: bool = _bool("BLOCK_VPN_LINKS", False)
# Join screening: flag accounts younger than this (days) to the log channel.
MIN_ACCOUNT_AGE_DAYS: int = int(os.getenv("MIN_ACCOUNT_AGE_DAYS", "7") or 7)
SCREEN_ON_JOIN: bool = _bool("SCREEN_ON_JOIN", True)

WELCOME_CHANNEL_ID: int | None = _int("WELCOME_CHANNEL_ID")
AUTOROLE_ID: int | None = _int("AUTOROLE_ID")
LOG_CHANNEL_ID: int | None = _int("LOG_CHANNEL_ID")
BOT_ACTIVITY: str = os.getenv("BOT_ACTIVITY", "PvPHaven | /help")

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "pvp_haven.db")
