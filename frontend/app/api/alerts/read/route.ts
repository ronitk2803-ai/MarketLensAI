import { cookies } from "next/headers";

import { ApiError, markAlertsRead } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";

/**
 * BFF proxy for the mark-all-read button (a Client Component — it can't
 * reach API_BASE_URL or read the session cookie itself). Reading alerts
 * goes straight from the Server Component page, per this app's rule that
 * Route Handlers exist only to bridge Client Components.
 */
export const dynamic = "force-dynamic";

export async function POST() {
  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) {
    return Response.json({ error: "not signed in" }, { status: 401 });
  }

  try {
    const result = await markAlertsRead(accessToken);
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return Response.json(
      { error: "couldn't mark alerts read" },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
