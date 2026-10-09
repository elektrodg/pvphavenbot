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
| 🔗 Linking | `/link /mylink /unlink /linkcheck /verify-setup` + verify panel + bot API (`/verify`, `/user/{id}`, `/health`) |
| 🔍 Verification | `/screen /alts /vpncheck` + join screening + VPN/multi-account flags on `/verify` |
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
- `TICKET_STAFF_ROLE_IDS` — **all** staff ranks that can see/handle tickets, comma-separated role IDs (e.g. `111,222,333`). Every listed role gets view+send in each ticket and is pinged on creation. Anyone with Manage Messages / Admin also counts as staff.
- `TICKET_LOG_CHANNEL_ID` — transcripts posted here on close.
- `GUILD_ID` — set for instant slash sync while testing; remove later for global commands.

## 3. Ticket setup

1. In the support channel run `/ticket-setup` (admin). A panel with buttons (Support / Report / Appeal / Other) is posted.
2. Users click → private channel `ticket-<name>-<category>` with Claim/Transcript/Close buttons.
3. `/ticket-close` → HTML transcript sent to log channel → channel deleted.
4. Buttons are **persistent** (survive restarts).

## 4. Website linking (pvphaven.cc ↔ Discord)

Flow: Discord `/link` → 6-char code (10 min TTL) → user enters code on site → site calls bot API → linked.

**Verify panel (recommended):** in your `#verify` channel run `/verify-setup` (admin).
It posts a persistent panel with two buttons — **Link Account** (sends the user their
private code as an ephemeral reply, no DM needed) and **Check Status** (shows their
current link). Same flow as `/link`, just one click. Buttons survive restarts.

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

## 5. Anti-alt & VPN verification

The bot screens for multi-accounts and VPN/proxy use in two places:

**A. At link time (automatic).** The Next.js route forwards the user's IP to `GET /verify?...&ip=...`. The bot then:
1. Checks the IP for VPN/proxy (if `VPN_CHECK_PROVIDER` is enabled — `proxycheck` has a free tier, key optional; `ipqualityscore` needs a key). Results cached 7 days.
2. Flags duplicates: Discord previously linked to another site account, site account linked to other Discord(s), IP already used by other accounts.
3. Returns `warnings: [...]` + `vpn: true/false/null` to the website — store these and e.g. require staff review on `vpn_detected` / `shared_ip_*`.
4. If `BLOCK_VPN_LINKS=true`, VPN users are rejected outright (code stays valid for retry without VPN). Default `false` = flag-only.

Every link is logged to `link_history` (site user + IP + vpn flag), which powers the Discord commands below. Note: IPs are personal data — the SQLite DB lives on your VPS; don't export it.

**B. In Discord (staff commands).**
- `/screen @member` — risk score (LOW/MEDIUM/HIGH) from account age, default avatar, multi-linked site accounts, VPN links, shared IPs.
- `/alts <member | site name | IP>` — find all accounts tied to the same Discord, site user, or IP.
- `/vpncheck <ip>` — live VPN/proxy lookup.
- Join screening (`SCREEN_ON_JOIN=true`, threshold `MIN_ACCOUNT_AGE_DAYS=7`): fresh or avatar-less joins get flagged to the log channel with a `/screen` hint.

Enable on VPS: set `VPN_CHECK_PROVIDER=proxycheck` in `.env`, restart. `/screen` and `/alts` work immediately from link history even with checks off.

## 6. Deploy (VPS example)

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
