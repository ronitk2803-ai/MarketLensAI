import { cookies } from "next/headers";

import { ApiError, generateAiSummary } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";

/**
 * BFF proxy for the AI-summary button — same boundary as /api/quotes and
 * /api/search: API_BASE_URL stays server-side, the client only ever talks
 * to this route.
 *
 * This is the ONE call site that can trigger a (free-tier, rate-limited)
 * LLM generation, and only because a user clicked the button — nothing
 * here runs on a schedule or a plain page load. The backend itself is
 * still what decides whether that click actually needs a fresh
 * generation or can reuse the cached one (app/services/company_summary.py).
 */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const symbol = new URL(request.url).searchParams.get("symbol");
  if (!symbol) {
    return Response.json({ error: "missing symbol" }, { status: 400 });
  }

  // Generating is auth-gated on the backend, so the session cookie has to
  // be forwarded — this route is the only thing that can read it.
  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) {
    return Response.json({ error: "sign in to generate a summary" }, { status: 401 });
  }

  try {
    const summary = await generateAiSummary(accessToken, symbol);
    return Response.json(summary, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    // Forward the provider's own message rather than flattening every
    // failure to one sentence. A permanently misconfigured API key and a
    // momentary blip are very different problems, and collapsing them is
    // why a completely dead LLM read as "try again in a moment" for days.
    const message =
      error instanceof ApiError && error.detail
        ? error.detail
        : "AI summary generation failed";
    return Response.json(
      { error: message },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
