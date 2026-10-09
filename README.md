# PvPHaven Bot 🏝️

Discord bot for **pvphaven.cc** (Growlocks): moderation, utility, fun, giveaways,
**ticket panel system**, welcome/autorole, and **Discord ↔ website account linking**.

## Features (40+ slash commands)

| Group | Commands |
|---|---|
| 🛡 Moderation | `/ban /unban /kick /timeout /untimeout /clear /warn /warnings /clearwarns /lock /unlock /slowmode /nick` |
| 🧰 Utility | `/help /ping /botinfo /serverinfo /userinfo /avatar /poll /remind /reminders` |
| 🎉 Fun | `/8ball /coinflip /dice /rps /joke` |
| 🎁 Giveaway | `/gstart /gend /greroll` (auto-ends, 🎉 reactions) |
| 🎫 Tickets | `/ticket-setup /ticket-panel /ticket-close /ticket-claim /ticket-add /ticket-remove /ticket-transcript` + button panel + HTML transcripts |
| 🔗 Linking | `/link /mylink /unlink /linkcheck` + bot API (`/verify`, `/user/{id}`, `/health`) |
| 👋 Welcome | `/setwelcome /setautorole /welcometest` + join messages |

## 1. Create the bot (Discord Developer Portal)

1. Go to https://discord.com/developers/applications → **New Application** → name `PvPHaven Bot`.
2. **Bot** tab → Reset Token → copy token. Enable intents: **Server Members**, **Message Content**.
3. **OAuth2 → URL Generator**: scopes `bot` + `applications.commands`, permissions: Manage Channels/Roles/Messages, Ban/Kick/Timeout, Read History, Add Reactions, Embed Links, Attach Files. Open the URL to invite.
4. Copy the **Application ID** (not strictly needed) and Guild ID for fast testing.

## 2. Run locally

```powershell
cd pvp_haven_bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# edit .env: DISCORD_TOKEN, GUILD_ID, TICKET_* IDs, LINK_API_KEY, WEBSITE_URL=https://pvphaven.cc
python bot.py
```

Get IDs: Discord Settings → Advanced → Developer Mode → right-click channel/role/category → Copy ID.

- `TICKET_CATEGORY_ID` — category where ticket channels are created.
- `TICKET_STAFF_ROLE_ID` — role pinged on new tickets, can claim/close.
- `TICKET_LOG_CHANNEL_ID` — transcripts posted here on close.
- `GUILD_ID` — set for instant slash sync while testing; remove later for global commands.

## 3. Ticket setup

1. In the support channel run `/ticket-setup` (admin). A panel with buttons (Support / Report / Appeal / Other) is posted.
2. Users click → private channel `ticket-<name>-<category>` with Claim/Transcript/Close buttons.
3. `/ticket-close` → HTML transcript sent to log channel → channel deleted.
4. Buttons are **persistent** (survive restarts).

## 4. Website linking (pvphaven.cc ↔ Discord)

Flow: Discord `/link` → 6-char code (10 min TTL) → user enters code on site → site calls bot API → linked.

**Bot side** (already built): `bot.py` hosts `GET /verify?code=..&site_user=..` with `X-API-Key` header.
Test: `curl -H "X-API-Key: <LINK_API_KEY>" "http://localhost:8090/verify?code=ABC123&site_user=testuser"`

**Website side (Next.js, pvphaven.cc)** — see `website-examples/`:

1. Add to website `.env`: `BOT_LINK_API_URL=http://<bot-host>:8090`, `BOT_LINK_API_KEY=<same as bot>`.
2. Copy `website-examples/nextjs-verify-route.ts` → `app/api/discord/verify/route.ts`.
3. Copy `website-examples/LinkDiscord.tsx` into profile page.
4. On success, store `discordId` on your user row (Prisma/etc). Optionally grant site perks / show Discord name.
5. To look up from site later: `GET {BOT_LINK_API_URL}/user/{discordId}?guild_id=..` with API key.

> VPS note: bot and site must reach each other. If the site is on Vercel and the bot on a VPS, expose port 8090 with a firewall rule restricted to Vercel/your server, or put it behind a reverse proxy with HTTPS. Never expose without the API key.

Optional reverse direction (site → Discord role): after linking, use the bot token server-side with discord.py/discord API to add a "Linked" role — ask if you want this snippet.

## 5. Deploy (VPS example)

```bash
# on VPS
git clone https://github.com/elektrodg/pvphavenbot && cd pvphavenbot
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env
# ALWAYS use the venv python with its full path (never bare `python`):
./.venv/bin/python bot.py
```

Keep it running with systemd (recommended over nohup):

```ini
# /etc/systemd/system/pvphavenbot.service
[Unit]
Description=PvPHaven Discord Bot
After=network.target

[Service]
User=tibo
WorkingDirectory=/home/tibo/pvphavenbot
ExecStart=/home/tibo/pvphavenbot/.venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now pvphavenbot
journalctl -u pvphavenbot -f   # live logs (replaces nohup.out)
```

## Project layout

```
pvp_haven_bot/
  bot.py                 entrypoint (+ starts link API)
  config.py              env config
  database/db.py         SQLite schema
  cogs/                  moderation, utility, fun_giveaway, tickets, linking, welcome
  api/link_server.py     GET /verify /user/{id} /health
  website-examples/      Next.js route + React component
```

## Troubleshooting

- **`PrivilegedIntentsRequired`**: Developer Portal → your app → **Bot** → enable **Server Members Intent** + **Message Content Intent** → Save → restart. (This is the #1 startup error.)
- **`No module named 'discord'` / `python: No such file`**: venv not active — use `./.venv/bin/python bot.py`, not bare `python`.
- **Commands don't appear**: wait ~1h for global sync, or set `GUILD_ID` for instant guild sync; re-invite with `applications.commands` scope.
- **Missing permissions**: bot role must be ABOVE moderated/ticket roles; needs Manage Channels for tickets.
- **DMs closed for /link**: bot falls back to ephemeral reply — still works.
- **404 growlocks repo**: the GitHub URL you gave 404s (private/renamed?). The bot's linking is stack-agnostic — the Next.js examples drop straight into pvphaven.cc.
