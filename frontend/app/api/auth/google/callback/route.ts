import { cookies } from "next/headers";

import { completeGoogleSignIn } from "@/lib/api";
import {
  OAUTH_STATE_COOKIE,
  clearOAuthStateCookie,
  setAuthCookies,
} from "@/lib/auth-cookies";

/**
 * Where Google sends the browser back. A Route Handler rather than a page
 * because it has to set httpOnly session cookies, which a Client Component
 * cannot do.
 *
 * The state cookie is read and cleared BEFORE the code is exchanged, so a
 * failure part-way through can't leave a replayable state behind.
 */
export const dynamic = "force-dynamic";

function back(request: Request, error: string) {
  return Response.redirect(new URL(`/login?error=${error}`, request.url), 302);
}

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const cookieStore = await cookies();
  const expectedState = cookieStore.get(OAUTH_STATE_COOKIE)?.value;
  clearOAuthStateCookie(cookieStore);

  // Google sends ?error=access_denied when the user presses Cancel. That's
  // an ordinary outcome, not a failure to report.
  if (params.get("error")) {
    return Response.redirect(new URL("/login", request.url), 302);
  }

  const code = params.get("code");
  const state = params.get("state");

  // A MISSING cookie is a hard failure, not a reason to skip the check —
  // otherwise stripping the cookie would silently disable CSRF protection.
  if (!expectedState || !state || state !== expectedState) {
    return back(request, "google_state");
  }
  if (!code) {
    return back(request, "google");
  }

  try {
    const tokens = await completeGoogleSignIn(code);
    setAuthCookies(cookieStore, tokens);
  } catch {
    return back(request, "google");
  }
  return Response.redirect(new URL("/", request.url), 302);
}
