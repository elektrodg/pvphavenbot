"""Utility + info commands: help, ping, server/user info, poll, reminders."""
from __future__ import annotations

import asyncio
import time

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from config import DB_PATH
from database.db import now

START = time.time()


class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._reminder_task: asyncio.Task | None = None

    async def cog_load(self):
        self._reminder_task = asyncio.create_task(self._reminder_loop())

    async def cog_unload(self):
        if self._reminder_task:
            self._reminder_task.cancel()

    async def _reminder_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT id, guild_id, user_id, channel_id, message, due_at FROM reminders WHERE due_at <= ?",
                        (now(),))
                    rows = await cur.fetchall()
                    for rid, gid, uid, cid, msg, _due in rows:
                        ch = self.bot.get_channel(cid)
                        if ch:
                            try:
                                await ch.send(f"⏰ <@{uid}> reminder: {msg}")
                            except discord.HTTPException:
                                pass
                        await db.execute("DELETE FROM reminders WHERE id=?", (rid,))
                    await db.commit()
            except Exception:
                pass
            await asyncio.sleep(20)

    @app_commands.command(name="help", description="Show all PvPHaven Bot commands")
    async def help(self, interaction: discord.Interaction):
        em = discord.Embed(title="🏝️ PvPHaven Bot — Commands", color=0x2ECC71,
                           description="Slash commands grouped by category.")
        em.add_field(name="🛡 Moderation",
                     value="`/ban /unban /kick /timeout /untimeout /clear /warn /warnings /clearwarns /lock /unlock /slowmode /nick`", inline=False)
        em.add_field(name="🧰 Utility",
                     value="`/help /ping /botinfo /serverinfo /userinfo /avatar /poll /remind /reminders`", inline=False)
        em.add_field(name="🎉 Fun & Social",
                     value="`/8ball /coinflip /dice /rps /joke` + `/gstart /gend /greroll`", inline=False)
        em.add_field(name="🎫 Tickets",
                     value="`/ticket-setup /ticket-panel /ticket-close /ticket-claim /ticket-add /ticket-remove /ticket-transcript`", inline=False)
        em.add_field(name="🔗 Website linking",
                     value="`/link /unlink /mylink` — link Discord to your PvPHaven website account", inline=False)
        em.add_field(name="👋 Welcome",
                     value="`/setwelcome /setautorole /welcometest`", inline=False)
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! `{ms}ms`", ephemeral=True)

    @app_commands.command(name="botinfo", description="Info about the bot")
    async def botinfo(self, interaction: discord.Interaction):
        up = int(time.time() - START)
        h, rem = divmod(up, 3600)
        m, s = divmod(rem, 60)
        em = discord.Embed(title="PvPHaven Bot", color=0x3498DB,
                           description=f"Uptime `{h}h {m}m {s}s` • {len(self.bot.guilds)} guild(s)")
        em.add_field(name="Latency", value=f"{round(self.bot.latency*1000)}ms")
        em.add_field(name="discord.py", value=discord.__version__)
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="serverinfo", description="Info about this server")
    async def serverinfo(self, interaction: discord.Interaction):
        g = interaction.guild
        em = discord.Embed(title=g.name, color=0x9B59B6)
        if g.icon:
            em.set_thumbnail(url=g.icon.url)
        em.add_field(name="Members", value=str(g.member_count))
        em.add_field(name="Channels", value=str(len(g.channels)))
        em.add_field(name="Roles", value=str(len(g.roles)))
        em.add_field(name="Created", value=f"<t:{int(g.created_at.timestamp())}:D>")
        em.add_field(name="Owner", value=f"<@{g.owner_id}>")
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="userinfo", description="Info about a user")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        em = discord.Embed(title=str(member), color=member.color if member.color.value else 0x95A5A7)
        em.set_thumbnail(url=member.display_avatar.url)
        em.add_field(name="ID", value=str(member.id))
        em.add_field(name="Joined server", value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "?")
        em.add_field(name="Account created", value=f"<t:{int(member.created_at.timestamp())}:R>")
        em.add_field(name="Roles", value=", ".join(r.mention for r in member.roles[1:][:10]) or "none")
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="avatar", description="Show a user's avatar")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        em = discord.Embed(title=f"{member}'s avatar", color=0x1ABC9C)
        em.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=em)

    @app_commands.command(name="poll", description="Create a quick yes/no or custom poll")
    async def poll(self, interaction: discord.Interaction, question: str,
                   option1: str = "✅ Yes", option2: str = "❌ No"):
        em = discord.Embed(title=f"📊 {question}", color=0xE67E22,
                           description=f"1️⃣ {option1}\n2️⃣ {option2}\n\nVote with reactions!")
        await interaction.response.send_message(embed=em)
        msg = await interaction.original_response()
        await msg.add_reaction("1️⃣")
        await msg.add_reaction("2️⃣")

    @app_commands.command(name="remind", description="Remind you after N minutes")
    async def remind(self, interaction: discord.Interaction, minutes: int, message: str):
        minutes = max(1, min(60 * 24 * 7, minutes))
        due = now() + minutes * 60
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO reminders (guild_id, user_id, channel_id, message, due_at) VALUES (?,?,?,?,?)",
                (interaction.guild.id, interaction.user.id, interaction.channel.id, message, due))
            await db.commit()
        await interaction.response.send_message(
            f"⏰ I'll remind you in {minutes}m: _{message}_", ephemeral=True)

    @app_commands.command(name="reminders", description="List your pending reminders")
    async def reminders(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT message, due_at FROM reminders WHERE guild_id=? AND user_id=? ORDER BY due_at LIMIT 10",
                (interaction.guild.id, interaction.user.id))
            rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message("You have no pending reminders.", ephemeral=True)
            return
        em = discord.Embed(title="⏰ Your reminders", color=0xF39C12)
        for msg, due in rows:
            em.add_field(name=f"<t:{due}:R>", value=msg[:200], inline=False)
        await interaction.response.send_message(embed=em, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
