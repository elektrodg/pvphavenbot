"""Role grants after successful verification."""
from __future__ import annotations

import discord

import config


async def grant_verified_role(bot: discord.Client, guild_id: int, user_id: int) -> bool:
    """Adds VERIFIED_ROLE_ID to the member. Returns True on success.

    False = not configured, guild/member/role not found, or no permission.
    Never raises.
    """
    role_id = config.VERIFIED_ROLE_ID
    if not role_id:
        return False
    try:
        guild = bot.get_guild(guild_id)
        if guild is None:
            try:
                guild = await bot.fetch_guild(guild_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return False
        role = guild.get_role(role_id)
        if role is None:
            return False
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return False
        if role in member.roles:
            return True
        await member.add_roles(role, reason="PvPHaven verification (website link)")
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False
