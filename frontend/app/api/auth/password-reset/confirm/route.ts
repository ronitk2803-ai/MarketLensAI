import { cookies } from "next/headers";

import { ApiError, confirmPasswordReset } from "@/lib/api";
import { setAuthCookies } from "@/lib/auth-cookies";

/**
 * On success the backend returns a fresh token pair (it revoked every
 * other session first), so this signs the user straight in rather than
 * bouncing them to a login form they just proved they can't use.
 */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const { email, code, newPassword } = await request.json();
  if (
    typeof email !== "string" ||
    typeof code !== "string" ||
    typeof newPassword !== "string"
  ) {
    return Response.json({ error: "email, code and password are required" }, { status: 400 });
  }

  try {
    const tokens = await confirmPasswordReset(email, code, newPassword);
    setAuthCookies(await cookies(), tokens);
    return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    const message =
      error instanceof ApiError && error.detail ? error.detail : "couldn't reset the password";
    return Response.json(
      { error: message },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
