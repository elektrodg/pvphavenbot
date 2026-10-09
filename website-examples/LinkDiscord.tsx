"use client";
import { useState } from "react";

// Drop-in React component for pvphaven.cc profile page ("Link Discord").
// POSTs to /api/discord/verify (see nextjs-verify-route.ts).

export default function LinkDiscord({ siteUserId }: { siteUserId: string }) {
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setStatus(null);
    try {
      const r = await fetch("/api/discord/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, siteUserId }),
      });
      const data = await r.json();
      setStatus(data.ok ? `✅ Linked to ${data.username} (${data.discordId})` : `❌ ${data.error}`);
    } catch {
      setStatus("❌ Network error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ border: "1px solid #333", borderRadius: 12, padding: 16, maxWidth: 420 }}>
      <h3>🔗 Link Discord</h3>
      <p style={{ opacity: 0.7, fontSize: 14 }}>
        In Discord run <code>/link</code>, then enter the 6-character code here.
      </p>
      <input
        value={code}
        onChange={(e) => setCode(e.target.value.toUpperCase())}
        placeholder="ABC123"
        maxLength={6}
        style={{ padding: 8, fontSize: 18, letterSpacing: 4, width: "100%" }}
      />
      <button onClick={submit} disabled={busy || code.length < 6} style={{ marginTop: 8, padding: "8px 16px" }}>
        {busy ? "Verifying…" : "Verify & Link"}
      </button>
      {status && <p>{status}</p>}
    </div>
  );
}
