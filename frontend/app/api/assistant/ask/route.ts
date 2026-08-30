import { cookies } from "next/headers";

import { ApiError, askResearchAssistant } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";

/**
 * BFF proxy for the NL research assistant — same boundary as
 * /api/ai-summary: API_BASE_URL stays server-side, the client only ever
 * talks to this route. Auth-gated and rate-limited on the backend (app/
 * api/v1/assistant.py) since one question can be several Gemini calls.
 */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  let question: unknown;
  try {
    ({ question } = await request.json());
  } catch {
    return Response.json({ error: "invalid request body" }, { status: 400 });
  }
  if (typeof question !== "string" || question.trim().length === 0) {
    return Response.json({ error: "missing question" }, { status: 400 });
  }

  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) {
    return Response.json({ error: "sign in to ask the research assistant" }, { status: 401 });
  }

  try {
    const answer = await askResearchAssistant(accessToken, question);
    return Response.json(answer, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    // Forward the backend's own message (rate-limited vs. a dead provider
    // vs. "narrower question please" are very different problems) rather
    // than flattening every failure to one sentence.
    const message =
      error instanceof ApiError && error.detail
        ? error.detail
        : "the research assistant couldn't answer right now";
    return Response.json(
      { error: message },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
