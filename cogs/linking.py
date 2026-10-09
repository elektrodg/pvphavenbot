"""Discord <-> pvphaven.cc website linking.

Flow (works with the Next.js site at pvphaven.cc):
  1. User runs /link in Discord -> bot DMs/shows a one-time code (TTL from config).
  2. User enters the code on the website (e.g. profile -> "Link Discord").
  3. Website calls the bot's verification API:
         GET http://bot-host:8090/verify?code=XXXXXX
         Header: X-API-Key: <LINK_API_KEY>
     -> { ok, discord_id, username } on success. Website then stores the
        mapping (discord_id <-> site user) and optionally calls back to
        mark the code used (auto-marked on verify).

Admin: /mylink, /unlink, /linkcheck (staff).
"""
from __future__ import annotations

import secrets

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from config import DB_PATH, LINK_CODE_TTL_MINUTES, WEBSITE_URL
from database.db import now


def make_code() -> str:
    # 6-char human-friendly code, no ambiguous chars
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


class Linking(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="link", description="Get a code to link your Discord to pvphaven.cc")
    async def link(self, interaction: discord.Interaction):
        code = make_code()
        created = now()
        expires = created + LINK_CODE_TTL_MINUTES * 60
        async with aiosqlite.connect(DB_PATH) as db:
            # one active code per user
            await db.execute("DELETE FROM link_codes WHERE guild_id=? AND user_id=?",
                             (interaction.guild.id, interaction.user.id))
            await db.execute(
                "INSERT INTO link_codes (code, guild_id, user_id, username, created_at, expires_at) VALUES (?,?,?,?,?,?)",
                (code, interaction.guild.id, interaction.user.id, str(interaction.user), created, expires))
            await db.commit()
        em = discord.Embed(title="🔗 Link your Discord to PvPHaven", color=0x2ECC71,
                           description=f"Your code: **`{code}`**\nExpires <t:{expires}:R>\n\n"
                                       f"**Steps:**\n1. Go to {WEBSITE_URL}\n"
                                       f"2. Open your profile → **Link Discord**\n3. Enter the code above\n\n"
                                       f"Never share this code — it proves you own this Discord account.")
        try:
            await interaction.user.send(embed=em)
            await interaction.response.send_message(
                "📩 I DM'd you your link code! (If DMs are closed, re-run with DMs open.)", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="mylink", description="Check your linked website account")
    async def mylink(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT website_user, linked_at FROM linked_accounts WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id))
            row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(
                f"❌ Not linked yet. Run `/link` then enter the code at {WEBSITE_URL}.", ephemeral=True)
            return
        site_user, ts = row
        await interaction.response.send_message(
            f"✅ Linked to **{site_user or 'website account'}** since <t:{ts}:D>.", ephemeral=True)

    @app_commands.command(name="unlink", description="Unlink your Discord from the website")
    async def unlink(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM linked_accounts WHERE guild_id=? AND user_id=?",
                             (interaction.guild.id, interaction.user.id))
            await db.execute("DELETE FROM link_codes WHERE guild_id=? AND user_id=?",
                             (interaction.guild.id, interaction.user.id))
            await db.commit()
        await interaction.response.send_message("🔓 Unlinked. You can `/link` again anytime.", ephemeral=True)

    @app_commands.command(name="linkcheck", description="Staff: check who a Discord user is linked to")
    async def linkcheck(self, interaction: discord.Interaction, member: discord.Member):
        if not isinstance(interaction.user, discord.Member) or not (
                interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT website_user, linked_at FROM linked_accounts WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, member.id))
            row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(f"❌ {member.mention} is not linked.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ {member.mention} ↔ **{row[0]}** (since <t:{row[1]}:D>)", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Linking(bot))
