"""Built-in link-verification HTTP API (aiohttp, no extra web framework).

Website (pvphaven.cc, Next.js) calls:
    GET /verify?code=ABC123   Header: X-API-Key: <LINK_API_KEY>
    GET /user/123456789       Header: X-API-Key  -> linked website_user

Run standalone:  python -m api.link_server
Or auto-started by bot.py alongside the bot.
"""
from __future__ import annotations

import json

import aiosqlite
from aiohttp import web

from config import DB_PATH, LINK_API_HOST, LINK_API_KEY, LINK_API_PORT
from database.db import init_db, now


async def verify(request: web.Request) -> web.Response:
    if request.headers.get("X-API-Key", "") != LINK_API_KEY:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    code = (request.query.get("code") or "").strip().upper()
    if not code:
        return web.json_response({"ok": False, "error": "missing code"}, status=400)
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
        website_user = request.query.get("site_user", "")
        # mark used + record link
        await db.execute("UPDATE link_codes SET used=1 WHERE code=?", (code,))
        await db.execute(
            "INSERT INTO linked_accounts (guild_id, user_id, website_user, linked_at) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET website_user=excluded.website_user, linked_at=excluded.linked_at",
            (guild_id, user_id, website_user, now()))
        await db.commit()
    return web.json_response({"ok": True, "discord_id": str(user_id),
                              "guild_id": str(guild_id), "username": username})


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
