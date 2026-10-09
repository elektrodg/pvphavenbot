"""Welcome messages, autorole, basic guild settings."""
from __future__ import annotations

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from config import AUTOROLE_ID, DB_PATH, WELCOME_CHANNEL_ID


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild_id = member.guild.id
        welcome_id, autorole_id = WELCOME_CHANNEL_ID, AUTOROLE_ID
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT welcome_channel, autorole FROM guild_settings WHERE guild_id=?", (guild_id,))
            row = await cur.fetchone()
            if row:
                welcome_id = row[0] or welcome_id
                autorole_id = row[1] or autorole_id
        if autorole_id:
            role = member.guild.get_role(autorole_id)
            if role:
                try:
                    await member.add_roles(role, reason="Autorole")
                except discord.HTTPException:
                    pass
        if welcome_id:
            ch = member.guild.get_channel(welcome_id)
            if isinstance(ch, discord.TextChannel):
                em = discord.Embed(title=f"Welcome to {member.guild.name}! 🏝️",
                                   description=f"{member.mention}, glad to have you!\n"
                                               f"• Run `/help` for commands\n• Need help? Open a ticket\n• Link your account with `/link`",
                                   color=0x2ECC71)
                em.set_thumbnail(url=member.display_avatar.url)
                try:
                    await ch.send(embed=em)
                except discord.HTTPException:
                    pass

    @app_commands.command(name="setwelcome", description="Set the welcome channel (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setwelcome(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO guild_settings (guild_id, welcome_channel) VALUES (?,?) "
                "ON CONFLICT(guild_id) DO UPDATE SET welcome_channel=excluded.welcome_channel",
                (interaction.guild.id, channel.id))
            await db.commit()
        await interaction.response.send_message(f"✅ Welcome channel → {channel.mention}", ephemeral=True)

    @app_commands.command(name="setautorole", description="Set the autorole (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setautorole(self, interaction: discord.Interaction, role: discord.Role):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO guild_settings (guild_id, autorole) VALUES (?,?) "
                "ON CONFLICT(guild_id) DO UPDATE SET autorole=excluded.autorole",
                (interaction.guild.id, role.id))
            await db.commit()
        await interaction.response.send_message(f"✅ Autorole → {role.mention}", ephemeral=True)

    @app_commands.command(name="welcometest", description="Preview the welcome message (admin)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def welcometest(self, interaction: discord.Interaction):
        em = discord.Embed(title=f"Welcome to {interaction.guild.name}! 🏝️",
                           description=f"{interaction.user.mention}, glad to have you!",
                           color=0x2ECC71)
        await interaction.response.send_message(embed=em)


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
