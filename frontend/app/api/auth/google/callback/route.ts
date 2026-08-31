import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { ApiError, completeGoogleSignIn } from "@/lib/api";
import {
  OAUTH_STATE_COOKIE,
  clearOAuthStateCookie,
  setAuthCookies,
} from "@/lib/auth-cookies";
import { absoluteUrl } from "@/lib/request-origin";

/**
 * Where Google sends the browser back. A Route Handler rather than a page
 * because it has to set httpOnly session cookies, which a Client Component
 * cannot do.
 *
 * Reading the incoming state cookie uses `cookies()` from next/headers —
 * that direction (request -> handler) always works. WRITING cookies goes
 * through `NextResponse.redirect(...).cookies` on every single return
 * path below, never the separate `cookies()` jar: a Response constructed
 * by the plain Fetch API `Response.redirect()` is an independent object,
 * and mutating a different jar doesn't reliably land on it. This is what
 * silently dropped the session after a real, fully-successful Google
 * sign-in (server logs showed a clean token exchange and a linked
 * account, but the browser was never signed in) — see
 * lib/auth-cookies.ts's CookieWriter doc comment for the fuller story.
 *
 * The state cookie is cleared on EVERY branch's response, not just
 * success, so a failed attempt can't leave a replayable state behind.
 *
 * Every redirect target is built with `absoluteUrl(...)` (lib/request-
 * origin.ts), never `new URL(path, request.url)`. In the containerized
 * deploy `request.url`'s origin is the container's own bind address
 * (0.0.0.0), not the browser's actual host — a redirect built from it sent
 * the browser to a different origin than the one that just received the
 * session cookies, so they were never sent back. This was the actual
 * cause of a fully successful Google sign-in (real token exchange, a real
 * linked account) still showing "Sign in" in the browser.
 */
export const dynamic = "force-dynamic";

/**
 * The backend is on a free Render dyno that cold-starts for 20-45s after an
 * idle stretch, and this handler blocks on it for the token exchange. The
 * platform default (10s on Hobby) killed the function mid-exchange, and
 * because the only thing the user saw was this route's own catch-all
 * redirect, a pure infrastructure timeout was indistinguishable from a
 * rejected Google credential. The three data-heavy PAGES were given the
 * same ceiling in c06b7d5; the auth route handlers were missed in that pass.
 */
export const maxDuration = 60;

function back(request: Request, error: string) {
  const response = NextResponse.redirect(absoluteUrl(`/login?error=${error}`, request), 302);
  clearOAuthStateCookie(response.cookies);
  return response;
}

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const expectedState = (await cookies()).get(OAUTH_STATE_COOKIE)?.value;

  // Google sends ?error=access_denied when the user presses Cancel. That's
  // an ordinary outcome, not a failure to report.
  if (params.get("error")) {
    const response = NextResponse.redirect(absoluteUrl("/login", request), 302);
    clearOAuthStateCookie(response.cookies);
    return response;
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
    const response = NextResponse.redirect(absoluteUrl("/", request), 302);
    clearOAuthStateCookie(response.cookies);
    setAuthCookies(response.cookies, tokens);
    return response;
  } catch (error) {
    // The bare `catch {}` this replaces threw the diagnosis away: a
    // rejected Google grant, a 500 from the account-linking path, and the
    // backend simply not answering in time all rendered as one generic
    // message with nothing written down anywhere. Log the real reason —
    // it is the only record, since the user only ever sees the redirect —
    // and split the two cases the user can actually act on differently.
    const reached = error instanceof ApiError;
    console.error(
      "[google-callback] sign-in failed:",
      reached
        ? `backend ${(error as ApiError).status}: ${(error as ApiError).detail ?? error.message}`
        : error,
    );
    return back(request, reached ? "google" : "google_unreachable");
  }
}
