"""PvPHaven Bot entrypoint. Run:  python bot.py"""
from __future__ import annotations

import asyncio
import logging

import discord
from aiohttp import web
from discord.ext import commands

import config
from api.link_server import build_app
from database.db import init_db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pvp_haven")

COGS = [
    "cogs.moderation",
    "cogs.utility",
    "cogs.fun_giveaway",
    "cogs.tickets",
    "cogs.linking",
    "cogs.welcome",
]


class PvPHavenBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix=config.PREFIX, intents=intents)

    async def setup_hook(self):
        await init_db()
        for ext in COGS:
            try:
                await self.load_extension(ext)
                log.info("Loaded %s", ext)
            except Exception:
                log.exception("Failed to load %s", ext)
        # start link API alongside bot
        try:
            app = build_app()
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, config.LINK_API_HOST, config.LINK_API_PORT)
            await site.start()
            log.info("Link API on http://%s:%s", config.LINK_API_HOST, config.LINK_API_PORT)
        except OSError:
            log.exception("Could not bind link API port (already in use?)")

    async def on_ready(self):
        activity = discord.Game(config.BOT_ACTIVITY)
        await self.change_presence(activity=activity)
        try:
            if config.GUILD_ID:
                guild = discord.Object(id=config.GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("Synced %d commands to guild %s", len(synced), config.GUILD_ID)
            else:
                synced = await self.tree.sync()
                log.info("Synced %d global commands", len(synced))
        except Exception:
            log.exception("Slash sync failed")
        log.info("Logged in as %s (%s)", self.user, self.user.id)


async def main():
    if not config.TOKEN or config.TOKEN == "PASTE_BOT_TOKEN_HERE":
        raise SystemExit("Set DISCORD_TOKEN in .env first (see .env.example).")
    bot = PvPHavenBot()
    async with bot:
        await bot.start(config.TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
