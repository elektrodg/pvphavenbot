"""Anti-alt / VPN verification: /screen, /alts, /vpncheck + join screening.

Signals (SQLite link_history + Discord account heuristics):
  - Discord account age, default avatar
  - One Discord linked to multiple site accounts (or vice versa)
  - Multiple accounts sharing one IP, VPN/proxy flag on link

Flag-only by default: nothing auto-bans. Tune via
MIN_ACCOUNT_AGE_DAYS / SCREEN_ON_JOIN / VPN_CHECK_PROVIDER / BLOCK_VPN_LINKS.
"""
from __future__ import annotations

import datetime

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

import config
from api.ipintel import check_ip
from config import DB_PATH


def _risk(score: int) -> tuple[str, int]:
    if score >= 60:
        return ("🔴 HIGH", 0xE74C3C)
    if score >= 30:
        return ("🟡 MEDIUM", 0xF1C40F)
    return ("🟢 LOW", 0x2ECC71)


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- data helpers ----------
    async def _links_for_discord(self, guild_id: int, user_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT website_user, linked_at FROM linked_accounts WHERE guild_id=? AND user_id=?",
                (guild_id, user_id))
            current = await cur.fetchone()
            cur = await db.execute(
                "SELECT DISTINCT website_user FROM link_history WHERE guild_id=? AND user_id=? AND website_user<>''",
                (guild_id, user_id))
            site_users = [r[0] for r in await cur.fetchall()]
            cur = await db.execute(
                "SELECT website_user, ip, vpn, created_at FROM link_history "
                "WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 5",
                (guild_id, user_id))
            history = await cur.fetchall()
        return current, site_users, history

    async def _others_on_same_site(self, guild_id: int, user_id: int, site_user: str):
        if not site_user:
            return []
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id FROM linked_accounts WHERE website_user=? AND NOT (guild_id=? AND user_id=?)",
                (site_user, guild_id, user_id))
            return [r[0] for r in await cur.fetchall()]

    async def _shared_ip(self, guild_id: int, user_id: int, ips: list[str]):
        out: set[str] = set()
        async with aiosqlite.connect(DB_PATH) as db:
            for ip in ips:
                if not ip:
                    continue
                cur = await db.execute(
                    "SELECT DISTINCT website_user, user_id FROM link_history "
                    "WHERE ip=? AND NOT (guild_id=? AND user_id=?) LIMIT 10",
                    (ip, guild_id, user_id))
                for site_u, disc_id in await cur.fetchall():
                    out.add(f"{site_u or '?'} (discord {disc_id})")
        return sorted(out)

    # ---------- commands ----------
    @app_commands.command(name="screen", description="Staff: alt/VPN risk screening for a member")
    async def screen(self, interaction: discord.Interaction, member: discord.Member):
        if not isinstance(interaction.user, discord.Member) or not (
                interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        score = 0
        notes: list[str] = []

        age_days = (discord.utils.utcnow() - member.created_at).days
        if age_days < config.MIN_ACCOUNT_AGE_DAYS:
            score += 40
            notes.append(f"⚠️ Account only **{age_days}d** old (< {config.MIN_ACCOUNT_AGE_DAYS}d)")
        elif age_days < 30:
            score += 15
            notes.append(f"Account {age_days}d old")
        else:
            notes.append(f"Account {age_days}d old ✅")

        if member.avatar is None:
            score += 20
            notes.append("⚠️ Default avatar (no custom pfp)")
        else:
            notes.append("Custom avatar ✅")

        current, site_users, history = await self._links_for_discord(interaction.guild.id, member.id)
        if current and current[0]:
            notes.append(f"🔗 Linked site account: **{current[0]}** (since <t:{current[1]}:D>)")
        else:
            notes.append("Not linked to website.")
        if len(site_users) > 1:
            score += 25 * (len(site_users) - 1)
            notes.append(f"⚠️ This Discord linked to **{len(site_users)}** site accounts: {', '.join(site_users)}")
        vpn_hits = [h for h in history if h[2] == 1]
        if vpn_hits:
            score += 25
            notes.append(f"⚠️ VPN/proxy used on {len(vpn_hits)} link(s)")
        ips = [h[1] for h in history if h[1]]
        shared = await self._shared_ip(interaction.guild.id, member.id, ips)
        if shared:
            score += 15
            notes.append("⚠️ Shared IP with: " + ", ".join(shared[:5]))
        if current and current[0]:
            others = await self._others_on_same_site(interaction.guild.id, member.id, current[0])
            if others:
                score += 25
                notes.append("⚠️ Site account also linked to discord(s): " + ", ".join(f"<@{o}>" for o in others))

        label, color = _risk(score)
        em = discord.Embed(title=f"🔍 Screening — {member} {label}", color=color,
                           description=f"Score **{score}/100**")
        em.set_thumbnail(url=member.display_avatar.url)
        em.add_field(name="Signals", value="\n".join(f"• {n}" for n in notes) or "none", inline=False)
        em.add_field(name="IDs", value=f"discord `{member.id}` • site `{current[0] if current and current[0] else '—'}`")
        await interaction.followup.send(embed=em, ephemeral=True)

    @app_commands.command(name="alts", description="Staff: find accounts sharing a site user, discord, or IP")
    async def alts(self, interaction: discord.Interaction, query: str):
        """query = @member mention / discord ID / site username / IP."""
        if not isinstance(interaction.user, discord.Member) or not (
                interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        q = query.strip().strip("<@!>")
        lines: list[str] = []
        async with aiosqlite.connect(DB_PATH) as db:
            # by discord id
            if q.isdigit():
                cur = await db.execute(
                    "SELECT website_user, ip, vpn, created_at FROM link_history WHERE user_id=? ORDER BY id DESC LIMIT 10",
                    (int(q),))
                for site_u, ip, vpn, ts in await cur.fetchall():
                    lines.append(f"• site **{site_u or '?'}** • ip `{ip or '?'}` • vpn={vpn} • <t:{ts}:D>")
            # by IP
            if "." in q or ":" in q:
                cur = await db.execute(
                    "SELECT DISTINCT website_user, user_id FROM link_history WHERE ip=? LIMIT 20", (q,))
                for site_u, disc_id in await cur.fetchall():
                    lines.append(f"• site **{site_u or '?'}** ↔ discord `{disc_id}`")
            # by site username
            cur = await db.execute(
                "SELECT guild_id, user_id, linked_at FROM linked_accounts WHERE website_user=? LIMIT 20", (q,))
            for gid, disc_id, ts in await cur.fetchall():
                lines.append(f"• discord <@{disc_id}> `{disc_id}` • linked <t:{ts}:D>")
        em = discord.Embed(title=f"🔍 Alt search: `{query[:50]}`", color=0x9B59B6,
                           description="\n".join(lines) or "No matches in link history.")
        await interaction.followup.send(embed=em, ephemeral=True)

    @app_commands.command(name="vpncheck", description="Staff: live VPN/proxy check for an IP")
    async def vpncheck(self, interaction: discord.Interaction, ip: str):
        if not isinstance(interaction.user, discord.Member) or not (
                interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        if config.VPN_CHECK_PROVIDER == "off":
            await interaction.response.send_message(
                "VPN checks are disabled. Set `VPN_CHECK_PROVIDER=proxycheck` (+ optional `PROXYCHECK_KEY`) in `.env` and restart.",
                ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await check_ip(ip.strip(), config.VPN_CHECK_PROVIDER,
                                config.PROXYCHECK_KEY, config.IPQUALITYSCORE_KEY)
        if result is None:
            await interaction.followup.send(f"❓ `{ip}` — unknown (private IP or provider error).", ephemeral=True)
        elif result:
            await interaction.followup.send(f"🚨 `{ip}` — **VPN/proxy detected**.", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ `{ip}` — clean.", ephemeral=True)

    # ---------- join screening ----------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not config.SCREEN_ON_JOIN or member.bot:
            return
        age_days = (discord.utils.utcnow() - member.created_at).days
        flags = []
        if age_days < config.MIN_ACCOUNT_AGE_DAYS:
            flags.append(f"account {age_days}d old")
        if member.avatar is None:
            flags.append("default avatar")
        if not flags:
            return
        log_id = config.LOG_CHANNEL_ID
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT log_channel FROM guild_settings WHERE guild_id=?", (member.guild.id,))
            row = await cur.fetchone()
            if row and row[0]:
                log_id = row[0]
        if not log_id:
            return
        ch = member.guild.get_channel(log_id)
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.send(
                    f"🔍 **Watchlist join:** {member.mention} `{member.id}` — {', '.join(flags)}. "
                    f"Run `/screen {member.mention}` after they link.")
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
