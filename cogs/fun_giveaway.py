"""Fun + giveaway commands (no external APIs needed)."""
from __future__ import annotations

import asyncio
import random
import time

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from config import DB_PATH
from database.db import now

JOKES = [
    "Why do PvP players never get lost? They always follow the damage numbers.",
    "I told my sword a joke... it was cutting-edge humor.",
    "Why did the creeper cross the road? To explode the other side's base.",
    "My ping is so high, I dodge attacks that happened yesterday.",
    "What do you call a fair PvP fight? A myth.",
]

BALL = ["Yes.", "No.", "Maybe.", "Ask again later.", "Definitely!", "Absolutely not.",
        "Signs point to yes.", "Don't count on it."]


class Fun(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="8ball", description="Ask the magic 8-ball")
    async def eightball(self, interaction: discord.Interaction, question: str):
        await interaction.response.send_message(f"🎱 **Q:** {question}\n**A:** {random.choice(BALL)}")

    @app_commands.command(name="coinflip", description="Flip a coin")
    async def coinflip(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🪙 **{random.choice(['Heads', 'Tails'])}!**")

    @app_commands.command(name="dice", description="Roll a dice (default d6)")
    async def dice(self, interaction: discord.Interaction, sides: int = 6):
        sides = max(2, min(100, sides))
        await interaction.response.send_message(f"🎲 You rolled **{random.randint(1, sides)}** (d{sides})")

    @app_commands.command(name="rps", description="Rock-paper-scissors vs the bot")
    async def rps(self, interaction: discord.Interaction, choice: str):
        choice = choice.lower()
        if choice not in ("rock", "paper", "scissors"):
            await interaction.response.send_message("Choose rock, paper, or scissors.", ephemeral=True)
            return
        bot_pick = random.choice(["rock", "paper", "scissors"])
        wins = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
        if bot_pick == choice:
            res = "Draw!"
        elif wins[choice] == bot_pick:
            res = "You win! 🎉"
        else:
            res = "Bot wins! 🤖"
        await interaction.response.send_message(f"You: **{choice}** vs Bot: **{bot_pick}** → {res}")

    @app_commands.command(name="joke", description="Get a PvP joke")
    async def joke(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"😂 {random.choice(JOKES)}")


class Giveaway(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._task: asyncio.Task | None = None

    async def cog_load(self):
        self._task = asyncio.create_task(self._loop())

    async def cog_unload(self):
        if self._task:
            self._task.cancel()

    async def _loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self._check_expired()
            except Exception:
                pass
            await asyncio.sleep(15)

    async def _check_expired(self):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT id, guild_id, channel_id, message_id, prize, winners, host_id FROM giveaways WHERE ended=0 AND ends_at<=?",
                (now(),))
            rows = await cur.fetchall()
        for gid, guild_id, channel_id, message_id, prize, winner_count, host_id in rows:
            await self._finish(guild_id, channel_id, message_id, prize, winner_count, host_id)

    async def _finish(self, guild_id: int, channel_id: int, message_id: int, prize: str, winner_count: int, host_id: int):
        channel = self.bot.get_channel(channel_id)
        winners_mentions = "no valid entries"
        if channel:
            try:
                msg = await channel.fetch_message(message_id)
                users = set()
                for reaction in msg.reactions:
                    if str(reaction.emoji) == "🎉":
                        async for u in reaction.users():
                            if not u.bot:
                                users.add(u)
                picked = random.sample(sorted(users, key=lambda u: u.id), min(winner_count, len(users))) if users else []
                if picked:
                    winners_mentions = ", ".join(u.mention for u in picked)
                await channel.send(f"🎉 Giveaway ended! Prize **{prize}** → Winners: {winners_mentions}")
            except discord.HTTPException:
                pass
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE giveaways SET ended=1 WHERE message_id=?", (message_id,))
            await db.commit()

    @app_commands.command(name="gstart", description="Start a giveaway (minutes, winners, prize)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def gstart(self, interaction: discord.Interaction, minutes: int, winners: int, prize: str):
        minutes = max(1, min(60 * 24 * 7, minutes))
        winners = max(1, min(20, winners))
        ends = now() + minutes * 60
        em = discord.Embed(title=f"🎉 {prize}", color=0xE91E63,
                           description=f"React with 🎉 to enter!\nEnds <t:{ends}:R> • {winners} winner(s)\nHosted by {interaction.user.mention}")
        await interaction.response.send_message(embed=em)
        msg = await interaction.original_response()
        await msg.add_reaction("🎉")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, winners, ends_at, host_id) VALUES (?,?,?,?,?,?,?)",
                (interaction.guild.id, interaction.channel.id, msg.id, prize, winners, ends, interaction.user.id))
            await db.commit()

    @app_commands.command(name="gend", description="End a giveaway early (message ID)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def gend(self, interaction: discord.Interaction, message_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT guild_id, channel_id, message_id, prize, winners, host_id FROM giveaways WHERE message_id=? AND ended=0",
                (int(message_id),))
            row = await cur.fetchone()
        if not row:
            await interaction.response.send_message("Giveaway not found or already ended.", ephemeral=True)
            return
        await interaction.response.send_message("Ending giveaway...", ephemeral=True)
        await self._finish(*row)

    @app_commands.command(name="greroll", description="Re-roll a past giveaway (message ID)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def greroll(self, interaction: discord.Interaction, message_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT guild_id, channel_id, message_id, prize, winners, host_id FROM giveaways WHERE message_id=?",
                (int(message_id),))
            row = await cur.fetchone()
        if not row:
            await interaction.response.send_message("Giveaway not found.", ephemeral=True)
            return
        _gid, guild_id, channel_id, msg_id, prize, winner_count, _host = row
        channel = interaction.guild.get_channel(channel_id)
        if not channel:
            await interaction.response.send_message("Channel not found.", ephemeral=True)
            return
        try:
            msg = await channel.fetch_message(msg_id)
        except discord.NotFound:
            await interaction.response.send_message("Message not found.", ephemeral=True)
            return
        users = set()
        for reaction in msg.reactions:
            if str(reaction.emoji) == "🎉":
                async for u in reaction.users():
                    if not u.bot:
                        users.add(u)
        if not users:
            await interaction.response.send_message("No valid entries to re-roll.", ephemeral=True)
            return
        picked = random.sample(sorted(users, key=lambda u: u.id), min(winner_count, len(users)))
        await interaction.response.send_message(
            f"🎉 New winner(s) for **{prize}**: " + ", ".join(u.mention for u in picked))


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
    await bot.add_cog(Giveaway(bot))
