// Next.js App Router route: app/api/discord/verify/route.ts
// User enters their 6-char Discord code on pvphaven.cc -> this route
// validates it against the bot's link API, then YOU store the mapping
// (discord_id <-> your site user) in your own DB.
//
// Env needed on website (Vercel): BOT_LINK_API_URL, BOT_LINK_API_KEY
//
// Example .env on website:
//   BOT_LINK_API_URL=http://your-vps-ip:8090
//   BOT_LINK_API_KEY=<same value as LINK_API_KEY in bot .env>

export async function POST(req: Request) {
  const { code, siteUserId } = await req.json();
  if (!code || typeof code !== "string") {
    return Response.json({ ok: false, error: "Missing code" }, { status: 400 });
  }
  const base = process.env.BOT_LINK_API_URL!;
  const key = process.env.BOT_LINK_API_KEY!;
  const url = `${base}/verify?code=${encodeURIComponent(code.trim().toUpperCase())}&site_user=${encodeURIComponent(siteUserId ?? "")}`;
  const r = await fetch(url, { headers: { "X-API-Key": key } });
  const data = await r.json();
  if (!r.ok || !data.ok) {
    return Response.json({ ok: false, error: data.error ?? "Invalid code" }, { status: 400 });
  }
  // TODO: save to YOUR database, e.g. Prisma:
  // await prisma.user.update({ where: { id: siteUserId }, data: { discordId: data.discord_id } });
  return Response.json({ ok: true, discordId: data.discord_id, username: data.username });
}
