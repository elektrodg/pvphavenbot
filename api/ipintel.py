"""IP intelligence (VPN/proxy/datacenter detection) for link verification.

Providers (pick one via config, or 'off'):
  - proxycheck.io : free tier, works with or without key (key raises limits).
                    Get one at https://proxycheck.io/ (free: 1000 lookups/day with key).
  - ipqualityscore: needs a key from https://www.ipqualityscore.com/.

Results are cached in SQLite for 7 days. Any failure returns None
(unknown) — verification degrades to 'no signal', never blocks by itself.
"""
from __future__ import annotations

import ipaddress
import time

import aiohttp
import aiosqlite

from config import DB_PATH

CACHE_TTL = 7 * 24 * 3600


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.strip())
        return addr.is_global
    except ValueError:
        return False


async def _proxycheck(ip: str, key: str) -> bool | None:
    params = {"vpn": "1", "asn": "1"}
    if key and key != "CHANGE_ME":
        params["key"] = key
    url = f"https://proxycheck.io/v2/{ip}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as r:
                data = await r.json()
    except Exception:
        return None
    if data.get("status") != "ok":
        return None
    info = data.get(ip, {})
    return info.get("proxy") == "yes"


async def _ipqs(ip: str, key: str) -> bool | None:
    if not key or key == "CHANGE_ME":
        return None
    url = f"https://ipqualityscore.com/api/json/ip/{key}/{ip}?strictness=1&allow_public_access_points=true"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                data = await r.json()
    except Exception:
        return None
    if not data.get("success"):
        return None
    return bool(data.get("proxy") or data.get("vpn") or data.get("tor"))


async def check_ip(ip: str, provider: str, proxycheck_key: str, ipqs_key: str) -> bool | None:
    """True = VPN/proxy, False = clean, None = unknown/off/private."""
    ip = (ip or "").strip()
    if provider == "off" or not _is_public_ip(ip):
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT vpn, checked_at FROM ip_intel_cache WHERE ip=?", (ip,))
        row = await cur.fetchone()
        if row and (int(time.time()) - row[1]) < CACHE_TTL:
            return bool(row[0])
    if provider == "ipqualityscore":
        result = await _ipqs(ip, ipqs_key)
    else:
        result = await _proxycheck(ip, proxycheck_key)
    if result is not None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO ip_intel_cache (ip, vpn, provider, checked_at) VALUES (?,?,?,?) "
                "ON CONFLICT(ip) DO UPDATE SET vpn=excluded.vpn, provider=excluded.provider, checked_at=excluded.checked_at",
                (ip, int(result), provider, int(time.time())))
            await db.commit()
    return result
