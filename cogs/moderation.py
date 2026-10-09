"""Moderation: ban/kick/timeout/clear/warns/lock/slowmode/role."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite

from config import DB_PATH
from database.db import now


def _mod_check():
    async def pred(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        p = interaction.user.guild_permissions
        return bool(p.manage_messages or p.kick_members or p.ban_members or p.moderate_members)
    return app_commands.check(pred)


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ----- helpers -----
    async def _log(self, guild: discord.Guild, text: str):
        from config import LOG_CHANNEL_ID
        if LOG_CHANNEL_ID:
            ch = guild.get_channel(LOG_CHANNEL_ID)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(f"🛡 {text}")
                except discord.HTTPException:
                    pass

    # ----- ban / kick / timeout -----
    @app_commands.command(name="ban", description="Ban a member")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member,
                  reason: str = "No reason", delete_days: int = 0):
        await interaction.guild.ban(member, reason=f"{interaction.user}: {reason}",
                                    delete_message_days=max(0, min(7, delete_days)))
        await self._log(interaction.guild, f"**Ban** {member.mention} by {interaction.user.mention} — {reason}")
        await interaction.response.send_message(f"🔨 Banned **{member}** — {reason}", ephemeral=True)

    @app_commands.command(name="unban", description="Unban a user by ID or name#discrim")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str):
        try:
            uid = int(user_id)
            user = await self.bot.fetch_user(uid)
        except ValueError:
            await interaction.response.send_message("Give a numeric user ID.", ephemeral=True)
            return
        try:
            await interaction.guild.unban(user)
            await interaction.response.send_message(f"✅ Unbanned **{user}**", ephemeral=True)
        except discord.NotFound:
            await interaction.response.send_message("User is not banned.", ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        await member.kick(reason=f"{interaction.user}: {reason}")
        await self._log(interaction.guild, f"**Kick** {member.mention} by {interaction.user.mention} — {reason}")
        await interaction.response.send_message(f"👢 Kicked **{member}** — {reason}", ephemeral=True)

    @app_commands.command(name="timeout", description="Timeout a member (minutes, max 40320)")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member,
                      minutes: int = 10, reason: str = "No reason"):
        import datetime
        minutes = max(1, min(40320, minutes))
        await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
        await interaction.response.send_message(
            f"⏳ Timed out **{member}** for {minutes}m — {reason}", ephemeral=True)

    @app_commands.command(name="untimeout", description="Remove timeout from a member")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None)
        await interaction.response.send_message(f"✅ Removed timeout from **{member}**", ephemeral=True)

    # ----- purge / lock / slowmode -----
    @app_commands.command(name="clear", description="Delete recent messages (1-100)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int = 10, user: discord.Member | None = None):
        amount = max(1, min(100, amount))

        def check(m: discord.Message):
            return True if user is None else m.author.id == user.id

        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount, check=check)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)

    @app_commands.command(name="lock", description="Lock this channel (no @everyone send)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        ch = interaction.channel
        await ch.set_permissions(interaction.guild.default_role, send_messages=False)
        await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)

    @app_commands.command(name="unlock", description="Unlock this channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        ch = interaction.channel
        await ch.set_permissions(interaction.guild.default_role, send_messages=None)
        await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)

    @app_commands.command(name="slowmode", description="Set slowmode seconds (0 to disable)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: int = 0):
        seconds = max(0, min(21600, seconds))
        await interaction.channel.edit(slowmode_delay=seconds)
        await interaction.response.send_message(
            f"🐢 Slowmode set to {seconds}s." if seconds else "🐢 Slowmode disabled.", ephemeral=True)

    @app_commands.command(name="nick", description="Change a member's nickname")
    @app_commands.checks.has_permissions(manage_nicknames=True)
    async def nick(self, interaction: discord.Interaction, member: discord.Member, nickname: str = ""):
        await member.edit(nick=nickname or None)
        await interaction.response.send_message(f"✏️ Nickname updated for **{member}**.", ephemeral=True)

    # ----- warnings -----
    @app_commands.command(name="warn", description="Warn a member")
    @_mod_check()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO warnings (guild_id, user_id, mod_id, reason, created_at) VALUES (?,?,?,?,?)",
                (interaction.guild.id, member.id, interaction.user.id, reason, now()),
            )
            await db.commit()
            cur = await db.execute(
                "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, member.id))
            count = (await cur.fetchone())[0]
        await self._log(interaction.guild, f"**Warn #{count}** {member.mention} by {interaction.user.mention} — {reason}")
        await interaction.response.send_message(
            f"⚠️ Warned **{member}** (#{count}) — {reason}", ephemeral=True)

    @app_commands.command(name="warnings", description="List warnings for a member")
    @_mod_check()
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT id, reason, mod_id, created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 20",
                (interaction.guild.id, member.id))
            rows = await cur.fetchall()
        if not rows:
            await interaction.response.send_message(f"✅ **{member}** has no warnings.", ephemeral=True)
            return
        em = discord.Embed(title=f"Warnings — {member}", color=0xF1C40F)
        for wid, reason, mod_id, ts in rows:
            em.add_field(name=f"#{wid} • <t:{ts}:R>",
                         value=f"{reason} (by <@{mod_id}>)", inline=False)
        await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="clearwarns", description="Clear all warnings for a member")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?",
                             (interaction.guild.id, member.id))
            await db.commit()
        await interaction.response.send_message(f"🧽 Cleared warnings for **{member}**.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
