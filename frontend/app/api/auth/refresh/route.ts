import { cookies } from "next/headers";

import { ApiError, refreshTokens } from "@/lib/api";
import { clearAuthCookies, REFRESH_TOKEN_COOKIE, setAuthCookies } from "@/lib/auth-cookies";

/**
 * Exists so the refresh capability is complete end-to-end, but nothing
 * calls this automatically yet — a Next.js middleware/proxy-based silent
 * refresh was considered and deliberately deferred (see the P1 auth plan:
 * Next 16 explicitly warns proxy.ts isn't meant for this, and rotate-on-
 * every-refresh would race concurrent requests). For now the access
 * token's 60-minute TTL is the whole story; wiring up reactive
 * refresh-on-401 is a follow-up.
 */
export const dynamic = "force-dynamic";

/** Cold-start ceiling — see app/api/auth/google/callback/route.ts. Every
 * handler here blocks on the free-tier backend. */
export const maxDuration = 60;

export async function POST() {
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)?.value;
  if (!refreshToken) {
    return Response.json({ error: "not signed in" }, { status: 401 });
  }

  try {
    const tokens = await refreshTokens(refreshToken);
    setAuthCookies(cookieStore, tokens);
    return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    clearAuthCookies(cookieStore);
    const status = error instanceof ApiError ? error.status : 502;
    return Response.json(
      { error: "session expired" },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
