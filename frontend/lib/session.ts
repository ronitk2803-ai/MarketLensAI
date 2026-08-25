import { cookies } from "next/headers";

import { getCurrentUser } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";
import type { AuthUser } from "@/lib/api";

/** Reads the session cookie and asks the backend who it belongs to —
 * straight to lib/api.ts, not through a Route Handler, since this only
 * runs in Server Components and can reach API_BASE_URL directly (same as
 * getCompany/getPrices elsewhere). A missing/expired/invalid token all
 * just mean "signed out" here; get_current_user does the same on the
 * backend and there's nothing more specific worth telling a caller.
 *
 * Shared between AppHeader (does the "who's signed in" line ever show)
 * and the homepage (does WatchlistPanel get real data or a sign-in
 * prompt) rather than each re-reading the cookie itself.
 */
export async function getSignedInUser(): Promise<AuthUser | null> {
  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) return null;
  return getCurrentUser(accessToken);
}
