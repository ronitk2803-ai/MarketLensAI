import { getLiveQuotes } from "@/lib/api";

/**
 * BFF proxy for live quotes — same boundary as /api/search and
 * /api/watchlist: API_BASE_URL stays server-side.
 *
 * This one is polled, so it must never be cached at any layer: a cached
 * response would pin a "live" price at whatever it was when the cache
 * filled, which is worse than showing a stored close, because it looks
 * current and isn't.
 */
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const symbols = (new URL(request.url).searchParams.get("symbols") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  if (symbols.length === 0) {
    return Response.json({ quotes: [], live: false });
  }

  try {
    const result = await getLiveQuotes(symbols);
    return Response.json(
      { quotes: result.data, live: result.meta.confidence === "high" },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    // Live quotes are an enhancement over the stored close the row already
    // shows — a provider outage degrades the display, it doesn't error it.
    return Response.json({ quotes: [], live: false }, { headers: { "Cache-Control": "no-store" } });
  }
}
