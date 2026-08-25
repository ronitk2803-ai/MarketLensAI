import { cookies } from "next/headers";

import { ApiError, addHolding } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";
import type { AddHoldingPayload } from "@/lib/api";

/**
 * BFF proxy for the add-holding form (a Client Component — it can't reach
 * API_BASE_URL or read the session cookie itself). Reads (GET /portfolio)
 * go straight from the Server Component instead — see app/portfolio/page.tsx.
 */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) {
    return Response.json({ error: "not signed in" }, { status: 401 });
  }

  const payload = (await request.json()) as AddHoldingPayload;
  try {
    const holding = await addHolding(accessToken, payload);
    return Response.json(holding, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    const message =
      error instanceof ApiError && error.detail ? error.detail : "couldn't add the holding";
    return Response.json(
      { error: message },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
