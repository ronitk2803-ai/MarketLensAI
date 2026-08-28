import { ApiError, requestPasswordReset } from "@/lib/api";

/**
 * Unauthenticated by necessity — someone who has forgotten their password
 * has no session. Forwards the backend's deliberately uninformative 200
 * unchanged: it answers identically whether or not the address exists, and
 * anything this route added on top would undo that.
 */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const { email } = await request.json();
  if (typeof email !== "string") {
    return Response.json({ error: "email is required" }, { status: 400 });
  }

  try {
    await requestPasswordReset(email);
  } catch (error) {
    // A 502 from a dead email provider is worth surfacing; anything else
    // still returns ok, since the backend's own contract is "always 200".
    if (error instanceof ApiError && error.status >= 500) {
      return Response.json(
        { error: error.detail ?? "couldn't send the code" },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }
  }
  return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
}
