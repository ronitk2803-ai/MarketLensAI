import { NextResponse } from "next/server";

import { getGoogleAuthorizeUrl } from "@/lib/api";
import { setOAuthStateCookie } from "@/lib/auth-cookies";
import { absoluteUrl } from "@/lib/request-origin";

/**
 * Kicks off "Sign in with Google".
 *
 * A GET that replies with a redirect, so the button can be a plain <a>.
 * It must not be reached by fetch(): the browser would follow the 302
 * cross-origin to accounts.google.com and fail CORS, producing an error
 * that looks nothing like the actual cause.
 *
 * The `state` is minted here and stored in an httpOnly cookie, then
 * compared on the way back — that round trip is what stops an attacker
 * feeding the user a callback for a code they obtained themselves.
 *
 * Built as a `NextResponse.redirect(...)` with the cookie set directly on
 * `response.cookies`, not `Response.redirect(...)` plus the separate
 * `cookies()` jar — the two are independent objects, and only writing to
 * the exact response being returned is guaranteed to land in the browser.
 * See lib/auth-cookies.ts's CookieWriter doc comment.
 */
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const state = crypto.randomUUID().replace(/-/g, "");

  try {
    const { url } = await getGoogleAuthorizeUrl(state);
    const response = NextResponse.redirect(url, 302);
    setOAuthStateCookie(response.cookies, state);
    return response;
  } catch {
    // Nothing useful to show at this URL — send them back to the form,
    // which renders the message.
    return NextResponse.redirect(absoluteUrl("/login?error=google", request), 302);
  }
}
