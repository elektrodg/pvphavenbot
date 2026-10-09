// Next.js App Router route: app/api/discord/verify/route.ts
// User enters their 6-char Discord code on pvphaven.cc -> this route
// validates it against the bot's link API, then YOU store the mapping
// (discord_id <-> your site user) in your own DB.
//
// The user's IP is forwarded so the bot can run VPN/proxy + shared-IP
// (multi-account) checks. The bot returns `warnings` — store/show them,
// e.g. require staff review when `vpn_detected` or `shared_ip_*` appears.
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
  // Real client IP behind Vercel/proxy
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    req.headers.get("x-real-ip") ??
    "";
  const base = process.env.BOT_LINK_API_URL!;
  const key = process.env.BOT_LINK_API_KEY!;
  const url =
    `${base}/verify?code=${encodeURIComponent(code.trim().toUpperCase())}` +
    `&site_user=${encodeURIComponent(siteUserId ?? "")}` +
    `&ip=${encodeURIComponent(ip)}`;
  const r = await fetch(url, { headers: { "X-API-Key": key } });
  const data = await r.json();
  if (!r.ok || !data.ok) {
    if (data.error === "vpn_blocked") {
      return Response.json(
        { ok: false, error: "Please disable your VPN to link your Discord account." },
        { status: 403 },
      );
    }
    return Response.json({ ok: false, error: data.error ?? "Invalid code" }, { status: 400 });
  }
  // TODO: save to YOUR database, e.g. Prisma:
  // await prisma.user.update({ where: { id: siteUserId }, data: { discordId: data.discord_id } });
  // TODO: handle data.warnings, e.g.:
  // if (data.warnings?.length) await prisma.verificationFlag.createMany(...)
  // The Verified role is granted when the user presses Verify in the
  // Discord panel (bot re-checks VPN + multi-accounts first), not here.
  return Response.json({
    ok: true,
    discordId: data.discord_id,
    username: data.username,
    vpn: data.vpn ?? null,
    warnings: data.warnings ?? [],
  });
}
