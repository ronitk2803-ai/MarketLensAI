import { ApiError, getWatchlistQuotes } from "@/lib/api";

/**
 * Thin BFF proxy, same reasoning as app/api/search/route.ts: the watchlist
 * widget is a client component (it reads its symbol list from
 * localStorage, which doesn't exist during server render), so it can't
 * import lib/api.ts directly — API_BASE_URL is server-only. This keeps that
 * boundary intact while still letting the client refresh on demand.
 */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const symbols = (url.searchParams.get("symbols") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const deltas = (url.searchParams.get("deltas") ?? "7,14,30")
    .split(",")
    .map((d) => Number.parseInt(d, 10))
    .filter((d) => Number.isFinite(d) && d > 0);

  if (symbols.length === 0) {
    return Response.json({ quotes: [], unknown_symbols: [] });
  }

  try {
    const data = await getWatchlistQuotes(symbols, deltas);
    return Response.json(data);
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return Response.json({ quotes: [], unknown_symbols: symbols }, { status });
  }
}
