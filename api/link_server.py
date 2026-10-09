"""Built-in link-verification HTTP API (aiohttp, no extra web framework).

Website (pvphaven.cc, Next.js) calls:
    GET /verify?code=ABC123&site_user=<id>&ip=<user ip>   Header: X-API-Key: <LINK_API_KEY>
    GET /user/123456789       Header: X-API-Key  -> linked website_user

/verify runs anti-alt + VPN checks and returns warnings, e.g.:
    {"ok": true, "discord_id": ..., "vpn": false,
     "warnings": ["discord_linked_to_other_account:oldname", "shared_ip_with:othername"]}

Run standalone:  python -m api.link_server
Or auto-started by bot.py alongside the bot.
"""
from __future__ import annotations

import aiosqlite
from aiohttp import web

import config
from api.ipintel import check_ip
from config import DB_PATH, LINK_API_HOST, LINK_API_KEY, LINK_API_PORT
from database.db import init_db, now


async def verify(request: web.Request) -> web.Response:
    if request.headers.get("X-API-Key", "") != LINK_API_KEY:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    code = (request.query.get("code") or "").strip().upper()
    if not code:
        return web.json_response({"ok": False, "error": "missing code"}, status=400)
    website_user = (request.query.get("site_user") or "").strip()[:64]
    ip = (request.query.get("ip") or "").strip()[:64]

    vpn: bool | None = None
    if ip and config.VPN_CHECK_PROVIDER != "off":
        vpn = await check_ip(ip, config.VPN_CHECK_PROVIDER,
                             config.PROXYCHECK_KEY, config.IPQUALITYSCORE_KEY)
        if vpn and config.BLOCK_VPN_LINKS:
            return web.json_response({"ok": False, "error": "vpn_blocked",
                                      "detail": "Linking over VPN/proxy is not allowed."}, status=403)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT guild_id, user_id, username, expires_at, used FROM link_codes WHERE code=?", (code,))
        row = await cur.fetchone()
        if not row:
            return web.json_response({"ok": False, "error": "invalid code"}, status=404)
        guild_id, user_id, username, expires_at, used = row
        if used:
            return web.json_response({"ok": False, "error": "code already used"}, status=410)
        if expires_at < now():
            return web.json_response({"ok": False, "error": "code expired"}, status=410)

        warnings: list[str] = []
        if vpn:
            warnings.append("vpn_detected")
        # This Discord was linked to a DIFFERENT site account before?
        cur = await db.execute(
            "SELECT website_user FROM linked_accounts WHERE guild_id=? AND user_id=?",
            (guild_id, user_id))
        prev = await cur.fetchone()
        if prev and prev[0] and prev[0] != website_user:
            warnings.append(f"discord_linked_to_other_account:{prev[0]}")
        # Same site account linked to other Discord(s)?
        if website_user:
            cur = await db.execute(
                "SELECT user_id FROM linked_accounts WHERE website_user=? AND NOT (guild_id=? AND user_id=?)",
                (website_user, guild_id, user_id))
            for (other_id,) in await cur.fetchall():
                warnings.append(f"site_account_linked_to_other_discord:{other_id}")
        # Same IP used by other accounts?
        if ip:
            cur = await db.execute(
                "SELECT DISTINCT website_user, user_id FROM link_history "
                "WHERE ip=? AND NOT (guild_id=? AND user_id=?) LIMIT 10",
                (ip, guild_id, user_id))
            for site_u, disc_id in await cur.fetchall():
                if site_u and site_u != website_user:
                    warnings.append(f"shared_ip_with_site_account:{site_u}")
                elif disc_id != user_id:
                    warnings.append(f"shared_ip_with_discord:{disc_id}")

        # mark used + record link + history
        await db.execute("UPDATE link_codes SET used=1 WHERE code=?", (code,))
        await db.execute(
            "INSERT INTO linked_accounts (guild_id, user_id, website_user, linked_at) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET website_user=excluded.website_user, linked_at=excluded.linked_at",
            (guild_id, user_id, website_user, now()))
        await db.execute(
            "INSERT INTO link_history (guild_id, user_id, website_user, ip, vpn, created_at) VALUES (?,?,?,?,?,?)",
            (guild_id, user_id, website_user, ip, None if vpn is None else int(vpn), now()))
        await db.commit()

    # NOTE: the Verified role is NOT granted here. The user presses Verify in
    # the Discord panel, which re-checks VPN + multi-accounts before granting.
    return web.json_response({"ok": True, "discord_id": str(user_id),
                              "guild_id": str(guild_id), "username": username,
                              "vpn": vpn, "warnings": warnings})


async def lookup(request: web.Request) -> web.Response:
    if request.headers.get("X-API-Key", "") != LINK_API_KEY:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    user_id = request.match_info["user_id"]
    guild_id = request.query.get("guild_id")
    async with aiosqlite.connect(DB_PATH) as db:
        if guild_id:
            cur = await db.execute(
                "SELECT website_user, linked_at FROM linked_accounts WHERE guild_id=? AND user_id=?",
                (int(guild_id), int(user_id)))
        else:
            cur = await db.execute(
                "SELECT website_user, linked_at FROM linked_accounts WHERE user_id=? LIMIT 1", (int(user_id),))
        row = await cur.fetchone()
    if not row:
        return web.json_response({"ok": False, "error": "not linked"}, status=404)
    return web.json_response({"ok": True, "discord_id": user_id, "website_user": row[0], "linked_at": row[1]})


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "pvp-haven-link-api"})


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/verify", verify)
    app.router.add_get("/user/{user_id}", lookup)
    app.router.add_get("/health", health)
    return app


async def run_standalone():
    await init_db()
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, LINK_API_HOST, LINK_API_PORT)
    await site.start()
    print(f"Link API on http://{LINK_API_HOST}:{LINK_API_PORT}  (endpoints: /verify /user/{{id}} /health)")
    import asyncio
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_standalone())
