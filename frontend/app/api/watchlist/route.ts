import { cookies } from "next/headers";

import { ApiError, getWatchlist } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";

/**
 * BFF proxy for the watchlist panel (a Client Component — it needs
 * interactivity, so it can't reach API_BASE_URL or read the session
 * cookie itself). Account-backed as of P1: no more `symbols` query param,
 * the access-token cookie is what selects whose list this is.
 */
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) {
    return Response.json({ error: "not signed in" }, { status: 401 });
  }

  const deltas = (new URL(request.url).searchParams.get("deltas") ?? "7,14,30")
    .split(",")
    .map((d) => Number.parseInt(d, 10))
    .filter((d) => Number.isFinite(d) && d > 0);

  try {
    const { data, meta } = await getWatchlist(accessToken, deltas);
    return Response.json({ ...data, meta }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return Response.json(
      { quotes: [], unknown_symbols: [] },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
