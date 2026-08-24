import { ApiError, generateAiSummary } from "@/lib/api";

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

  try {
    const summary = await generateAiSummary(symbol);
    return Response.json(summary, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return Response.json(
      { error: "AI summary generation failed" },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
