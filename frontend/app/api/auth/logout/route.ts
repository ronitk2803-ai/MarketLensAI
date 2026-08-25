import { cookies } from "next/headers";

import { logoutUser } from "@/lib/api";
import { clearAuthCookies, REFRESH_TOKEN_COOKIE } from "@/lib/auth-cookies";

export const dynamic = "force-dynamic";

export async function POST() {
  const cookieStore = await cookies();
  const refreshToken = cookieStore.get(REFRESH_TOKEN_COOKIE)?.value;

  // Best-effort revoke — the cookies come off the browser either way, so a
  // backend hiccup here shouldn't leave the user stuck "logged in" client-
  // side with no way to sign out.
  if (refreshToken) {
    await logoutUser(refreshToken).catch(() => {});
  }
  clearAuthCookies(cookieStore);

  return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
}
