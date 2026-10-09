"""Ticket system: panel with buttons, private channels, claim/add/remove/close/transcript."""
from __future__ import annotations

import asyncio
import datetime
import html
import io

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from config import (
    DB_PATH,
    TICKET_CATEGORY_ID,
    TICKET_LOG_CHANNEL_ID,
    TICKET_PANEL_OPTIONS,
    TICKET_PANEL_TITLE,
    TICKET_STAFF_ROLE_ID,
)
from database.db import now


def parse_panel_options() -> list[tuple[str, str, str]]:
    """Returns [(key, label, emoji)]."""
    out = []
    for part in TICKET_PANEL_OPTIONS.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        if len(bits) == 3:
            out.append((bits[0].strip(), bits[1].strip(), bits[2].strip()))
        elif len(bits) == 2:
            out.append((bits[0].strip(), bits[1].strip(), "🎫"))
    return out or [("support", "Support", "🎫")]


def is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.manage_messages or member.guild_permissions.administrator:
        return True
    if TICKET_STAFF_ROLE_ID and any(r.id == TICKET_STAFF_ROLE_ID for r in member.roles):
        return True
    return False


class TicketOpenButton(discord.ui.Button):
    def __init__(self, key: str, label: str, emoji: str):
        super().__init__(label=label[:80], emoji=emoji, style=discord.ButtonStyle.primary,
                         custom_id=f"pvp_ticket_open:{key}")
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        cog: Tickets = interaction.client.get_cog("Tickets")  # type: ignore
        await cog.open_ticket(interaction, self.key)


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for key, label, emoji in parse_panel_options():
            self.add_item(TicketOpenButton(key, label, emoji))


class TicketControlView(discord.ui.View):
    """Buttons shown inside every ticket channel."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", emoji="🙋", style=discord.ButtonStyle.secondary, custom_id="pvp_ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: Tickets = interaction.client.get_cog("Tickets")  # type: ignore
        await cog.claim_ticket(interaction)

    @discord.ui.button(label="Transcript", emoji="📝", style=discord.ButtonStyle.secondary, custom_id="pvp_ticket:transcript")
    async def transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: Tickets = interaction.client.get_cog("Tickets")  # type: ignore
        await cog.send_transcript(interaction, interaction.channel)

    @discord.ui.button(label="Close", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="pvp_ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: Tickets = interaction.client.get_cog("Tickets")  # type: ignore
        await cog.close_ticket(interaction)


async def build_transcript_html(channel: discord.TextChannel) -> str:
    lines = []
    async for msg in channel.history(limit=1000, oldest_first=True):
        ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
        author = html.escape(f"{msg.author} ({msg.author.id})")
        content = html.escape(msg.content or "")
        if msg.attachments:
            content += " " + " ".join(html.escape(a.url) for a in msg.attachments)
        avatar = html.escape(str(msg.author.display_avatar.url))
        lines.append(
            f"<div class='msg'><img src='{avatar}'/><div><div class='meta'><b>{author}</b>"
            f"<span>{ts}</span></div><div class='body'>{content or '<i>(no text)</i>'}</div></div></div>"
        )
    body = "\n".join(lines) or "<p>No messages.</p>"
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>Transcript #{html.escape(channel.name)}</title>
<style>body{{font-family:sans-serif;background:#1e1f22;color:#eee;margin:0;padding:24px}}
.msg{{display:flex;gap:12px;margin-bottom:14px}}img{{width:40px;height:40px;border-radius:50%}}
.meta span{{color:#999;margin-left:8px;font-size:12px}}.body{{margin-top:4px;white-space:pre-wrap}}</style>
</head><body><h2>Transcript — #{html.escape(channel.name)}</h2>{body}</body></html>"""


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- core actions ----------
    async def open_ticket(self, interaction: discord.Interaction, category: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        # one open ticket per user?
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id FROM tickets WHERE guild_id=? AND owner_id=? AND status='open'",
                (guild.id, interaction.user.id))
            existing = await cur.fetchone()
        if existing:
            ch = guild.get_channel(existing[0])
            await interaction.followup.send(
                f"❌ You already have an open ticket: {ch.mention if ch else 'unknown channel'}",
                ephemeral=True)
            return

        category_ch = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                         read_message_history=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if TICKET_STAFF_ROLE_ID:
            role = guild.get_role(TICKET_STAFF_ROLE_ID)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                              read_message_history=True, manage_messages=True)

        name = f"ticket-{interaction.user.name[:20].lower().replace(' ', '-')}-{category[:10]}"
        channel = await guild.create_text_channel(
            name=name,
            category=category_ch if isinstance(category_ch, discord.CategoryChannel) else None,
            overwrites=overwrites,
            reason=f"Ticket ({category}) by {interaction.user}",
        )
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO tickets (guild_id, channel_id, owner_id, category, status, created_at) VALUES (?,?,?,?,?,?)",
                (guild.id, channel.id, interaction.user.id, category, "open", now()))
            await db.commit()

        em = discord.Embed(title=f"🎫 {category.title()} ticket",
                           description=f"Hello {interaction.user.mention}! Staff will be with you shortly.\n"
                                       f"Use the buttons below to claim, save a transcript, or close.",
                           color=0x2ECC71)
        await channel.send(embed=em, view=TicketControlView())
        if TICKET_STAFF_ROLE_ID:
            role = guild.get_role(TICKET_STAFF_ROLE_ID)
            if role:
                await channel.send(f"{role.mention} new ticket!")
        await interaction.followup.send(f"✅ Ticket created: {channel.mention}", ephemeral=True)

    async def claim_ticket(self, interaction: discord.Interaction):
        if not is_staff(interaction.user):  # type: ignore
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE tickets SET claimed_by=? WHERE channel_id=?",
                             (interaction.user.id, interaction.channel.id))
            await db.commit()
        await interaction.response.send_message(f"🙋 Ticket claimed by {interaction.user.mention}")

    async def close_ticket(self, interaction: discord.Interaction):
        channel = interaction.channel
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT owner_id, status FROM tickets WHERE channel_id=?", (channel.id,))
            row = await cur.fetchone()
        if not row:
            await interaction.response.send_message("This is not a ticket channel.", ephemeral=True)
            return
        owner_id, status = row
        if status == "closed":
            await interaction.response.send_message("Ticket already closed.", ephemeral=True)
            return
        if interaction.user.id != owner_id and not is_staff(interaction.user):  # type: ignore
            await interaction.response.send_message("❌ Only the ticket owner or staff can close.", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Closing in 5s — transcript will be saved...")
        await asyncio.sleep(5)
        try:
            html_doc = await build_transcript_html(channel)  # type: ignore
        except Exception:
            html_doc = "<html><body>Transcript failed.</body></html>"
        if TICKET_LOG_CHANNEL_ID:
            log = interaction.guild.get_channel(TICKET_LOG_CHANNEL_ID)
            if isinstance(log, discord.TextChannel):
                try:
                    f = discord.File(io.BytesIO(html_doc.encode()), filename=f"transcript-{channel.name}.html")
                    await log.send(f"📝 Transcript for #{channel.name} (owner <@{owner_id}>, closed by {interaction.user.mention})", file=f)
                except discord.HTTPException:
                    pass
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE tickets SET status='closed', closed_at=? WHERE channel_id=?", (now(), channel.id))
            await db.commit()
        await channel.delete(reason=f"Ticket closed by {interaction.user}")

    async def send_transcript(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True, thinking=True)
        html_doc = await build_transcript_html(channel)
        f = discord.File(io.BytesIO(html_doc.encode()), filename=f"transcript-{channel.name}.html")
        await interaction.followup.send("📝 Transcript:", file=f, ephemeral=True)

    # ---------- slash commands ----------
    @app_commands.command(name="ticket-setup", description="Post the ticket panel in this channel (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_setup(self, interaction: discord.Interaction, message: str = ""):
        em = discord.Embed(title=f"🎫 {TICKET_PANEL_TITLE}",
                           description=message or "Need help? Click a button below to open a private ticket.",
                           color=0x3498DB)
        await interaction.response.send_message("Panel posted below 👇")
        await interaction.channel.send(embed=em, view=TicketPanelView())

    @app_commands.command(name="ticket-panel", description="Alias for ticket-setup (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        await self.ticket_setup.callback(self, interaction)  # type: ignore

    @app_commands.command(name="ticket-close", description="Close this ticket")
    async def ticket_close(self, interaction: discord.Interaction):
        await self.close_ticket(interaction)

    @app_commands.command(name="ticket-claim", description="Claim this ticket (staff)")
    async def ticket_claim(self, interaction: discord.Interaction):
        await self.claim_ticket(interaction)

    @app_commands.command(name="ticket-transcript", description="Get an HTML transcript of this ticket")
    async def ticket_transcript(self, interaction: discord.Interaction):
        await self.send_transcript(interaction, interaction.channel)  # type: ignore

    @app_commands.command(name="ticket-add", description="Add a user to this ticket (staff)")
    async def ticket_add(self, interaction: discord.Interaction, member: discord.Member):
        if not is_staff(interaction.user):  # type: ignore
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        await interaction.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)  # type: ignore
        await interaction.response.send_message(f"✅ Added {member.mention}")

    @app_commands.command(name="ticket-remove", description="Remove a user from this ticket (staff)")
    async def ticket_remove(self, interaction: discord.Interaction, member: discord.Member):
        if not is_staff(interaction.user):  # type: ignore
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        await interaction.channel.set_permissions(member, overwrite=None)  # type: ignore
        await interaction.response.send_message(f"✅ Removed {member.mention}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
    # persistent views survive restarts
    bot.add_view(TicketPanelView())
    bot.add_view(TicketControlView())
