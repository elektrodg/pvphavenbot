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

import config
from api.ipintel import check_ip
from api.roles import grant_verified_role
from config import DB_PATH, LINK_CODE_TTL_MINUTES, WEBSITE_URL
from database.db import now

# Links older than this must be refreshed (Link Account again) before Verify,
# otherwise the stored IP data is too stale to trust.
VERIFY_LINK_MAX_AGE_DAYS = 30


def make_code() -> str:
    # 6-char human-friendly code, no ambiguous chars
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


async def create_link_code(guild_id: int, user: discord.abc.User) -> tuple[str, int]:
    """Stores a fresh one-time code, returns (code, expires_at)."""
    code = make_code()
    created = now()
    expires = created + LINK_CODE_TTL_MINUTES * 60
    async with aiosqlite.connect(DB_PATH) as db:
        # one active code per user
        await db.execute("DELETE FROM link_codes WHERE guild_id=? AND user_id=?",
                         (guild_id, user.id))
        await db.execute(
            "INSERT INTO link_codes (code, guild_id, user_id, username, created_at, expires_at) VALUES (?,?,?,?,?,?)",
            (code, guild_id, user.id, str(user), created, expires))
        await db.commit()
    return code, expires


def link_embed(code: str, expires: int) -> discord.Embed:
    return discord.Embed(
        title="🔗 Link your Discord to PvPHaven", color=0x2ECC71,
        description=f"Your code: **`{code}`**\nExpires <t:{expires}:R>\n\n"
                    f"**Steps:**\n1. Go to {WEBSITE_URL}\n"
                    f"2. Open your profile → **Link Discord**\n3. Enter the code above\n\n"
                    f"Never share this code — it proves you own this Discord account.")


class VerifyPanelView(discord.ui.View):
    """Persistent panel for a #verify channel: Link Account + Verify + Check Status."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Link Account", emoji="🔗", style=discord.ButtonStyle.success,
                       custom_id="pvp_verify:link")
    async def link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        code, expires = await create_link_code(interaction.guild.id, interaction.user)  # type: ignore
        await interaction.followup.send(embed=link_embed(code, expires), ephemeral=True)

    @discord.ui.button(label="Verify", emoji="🛡️", style=discord.ButtonStyle.primary,
                       custom_id="pvp_verify:verify")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """VPN + multi-account checks; grants Verified role when clear."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        gid = interaction.guild.id  # type: ignore
        uid = interaction.user.id
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT website_user, linked_at FROM linked_accounts WHERE guild_id=? AND user_id=?",
                (gid, uid))
            row = await cur.fetchone()
            if not row or not row[0]:
                await interaction.followup.send(
                    f"❌ **Link your account first:** press **Link Account**, enter the code at {WEBSITE_URL}, then press **Verify**.",
                    ephemeral=True)
                return
            site_user, linked_at = row
            cur = await db.execute(
                "SELECT DISTINCT website_user FROM link_history WHERE guild_id=? AND user_id=? AND website_user<>''",
                (gid, uid))
            site_users = [r[0] for r in await cur.fetchall()]
            cur = await db.execute(
                "SELECT DISTINCT ip FROM link_history WHERE guild_id=? AND user_id=? AND ip<>''",
                (gid, uid))
            ips = [r[0] for r in await cur.fetchall()]
            cur = await db.execute(
                "SELECT user_id FROM linked_accounts WHERE website_user=? AND NOT (guild_id=? AND user_id=?)",
                (site_user, gid, uid))
            other_discords = [r[0] for r in await cur.fetchall()]
            shared: list[str] = []
            for ip in ips:
                cur = await db.execute(
                    "SELECT DISTINCT website_user FROM link_history "
                    "WHERE ip=? AND website_user<>'' AND website_user<>? LIMIT 5",
                    (ip, site_user))
                shared.extend(r[0] for r in await cur.fetchall())

        problems: list[str] = []
        # 1. Freshness — stale IPs can't be trusted.
        if linked_at < now() - VERIFY_LINK_MAX_AGE_DAYS * 86400:
            problems.append(f"Your link is older than {VERIFY_LINK_MAX_AGE_DAYS} days. "
                            f"Press **Link Account**, enter the fresh code at {WEBSITE_URL}, then **Verify** again.")
        # 2. Multi-accounts.
        if len(site_users) > 1:
            problems.append("This Discord is linked to multiple website accounts. Staff must review — open a ticket.")
        if other_discords:
            problems.append("Your website account is linked to other Discord accounts. Staff must review — open a ticket.")
        if shared:
            problems.append("Your network is already used by another account. If this is a mistake (shared Wi-Fi etc.), open a ticket.")
        # 3. VPN/proxy on the stored link IPs (always evaluated, reported with the rest).
        if config.VPN_CHECK_PROVIDER == "off":
            problems.append("VPN verification is not enabled on the bot yet — contact staff.")
        elif not ips:
            problems.append("No network data stored — press **Link Account**, enter the code on the site, then **Verify**.")
        else:
            vpn_hit, unknown = False, False
            for ip in ips:
                res = await check_ip(ip, config.VPN_CHECK_PROVIDER,
                                     config.PROXYCHECK_KEY, config.IPQUALITYSCORE_KEY)
                if res is True:
                    vpn_hit = True
                elif res is None:
                    unknown = True
            if vpn_hit:
                problems.append("VPN/proxy detected on your network. Disable it, press **Link Account** to refresh, then **Verify** again.")
            elif unknown:
                problems.append("VPN status could not be confirmed — try again in a few minutes or contact staff.")

        if problems:
            em = discord.Embed(title="🔴 Verification failed", color=0xE74C3C,
                               description="\n".join(f"• {p}" for p in problems))
            await interaction.followup.send(embed=em, ephemeral=True)
            return
        ok = await grant_verified_role(interaction.client, gid, uid)
        if ok:
            await interaction.followup.send(
                "✅ **Verified!** VPN and multi-account checks are clear — welcome to PvPHaven. 🏝️",
                ephemeral=True)
        else:
            await interaction.followup.send(
                "✅ Checks passed, but the Verified role could not be granted. "
                "Staff: check `VERIFIED_ROLE_ID` and that the bot role sits above it.",
                ephemeral=True)

    @discord.ui.button(label="Check Status", emoji="✅", style=discord.ButtonStyle.secondary,
                       custom_id="pvp_verify:status")
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT website_user, linked_at FROM linked_accounts WHERE guild_id=? AND user_id=?",
                (interaction.guild.id, interaction.user.id))  # type: ignore
            row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(
                f"❌ Not linked yet. Press **Link Account** then enter the code at {WEBSITE_URL}.",
                ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ Linked to **{row[0] or 'website account'}** since <t:{row[1]}:D>.", ephemeral=True)


class Linking(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="link", description="Get a code to link your Discord to pvphaven.cc")
    async def link(self, interaction: discord.Interaction):
        code, expires = await create_link_code(interaction.guild.id, interaction.user)
        em = link_embed(code, expires)
        try:
            await interaction.user.send(embed=em)
            await interaction.response.send_message(
                "📩 I DM'd you your link code! (If DMs are closed, re-run with DMs open.)", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=em, ephemeral=True)

    @app_commands.command(name="verifysync", description="Admin: grant Verified role to all linked members")
    @app_commands.checks.has_permissions(administrator=True)
    async def verifysync(self, interaction: discord.Interaction):
        from api.roles import grant_verified_role
        from config import VERIFIED_ROLE_ID
        if not VERIFIED_ROLE_ID:
            await interaction.response.send_message(
                "❌ `VERIFIED_ROLE_ID` is not set in `.env`.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT user_id FROM linked_accounts WHERE guild_id=?", (interaction.guild.id,))
            user_ids = [r[0] for r in await cur.fetchall()]
        granted, skipped = 0, 0
        for uid in user_ids:
            if await grant_verified_role(interaction.client, interaction.guild.id, uid):
                granted += 1
            else:
                skipped += 1
        await interaction.followup.send(
            f"✅ Verified role granted to **{granted}** member(s)"
            + (f" ({skipped} skipped — left the server or role missing)." if skipped else "."),
            ephemeral=True)

    @app_commands.command(name="verify-setup", description="Post the verification panel in this channel (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def verify_setup(self, interaction: discord.Interaction, message: str = ""):
        em = discord.Embed(
            title="✅ PvPHaven Verification",
            description=message or (
                f"Verify yourself to unlock the server. We check for VPN/proxy use and multi-accounts.\n\n"
                f"**Steps:**\n1. Press **Link Account** → you get a private code\n"
                f"2. Enter it at {WEBSITE_URL} → profile → **Link Discord**\n"
                f"3. Press **Verify** → clear checks = Verified role instantly\n\n"
                f"Already linked? Press **Verify** (or **Check Status** to see your link)."),
            color=0x2ECC71)
        await interaction.response.send_message("Verify panel posted below 👇")
        await interaction.channel.send(embed=em, view=VerifyPanelView())

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
    bot.add_view(VerifyPanelView())
