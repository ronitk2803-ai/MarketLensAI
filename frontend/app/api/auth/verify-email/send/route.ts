import { cookies } from "next/headers";

import { ApiError, sendVerificationCode } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";

/**
 * BFF proxy for "send me the code". Same boundary as every other
 * app/api/auth/* route: the form is a Client Component, so it can reach
 * neither API_BASE_URL nor the httpOnly session cookie.
 *
 * The backend's 429 is forwarded as-is rather than softened. It is safe
 * here because this endpoint is authenticated — the caller already knows
 * the account exists, so the status reveals nothing. The password-reset
 * equivalent deliberately cannot do this.
 */
export const dynamic = "force-dynamic";

export async function POST() {
  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) {
    return Response.json({ error: "sign in first" }, { status: 401 });
  }

  try {
    const result = await sendVerificationCode(accessToken);
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    const message =
      error instanceof ApiError && error.detail ? error.detail : "couldn't send the code";
    return Response.json(
      { error: message },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
