import { cookies } from "next/headers";

import { getGoogleAuthorizeUrl } from "@/lib/api";
import { setOAuthStateCookie } from "@/lib/auth-cookies";

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
 */
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const state = crypto.randomUUID().replace(/-/g, "");

  try {
    const { url } = await getGoogleAuthorizeUrl(state);
    setOAuthStateCookie(await cookies(), state);
    return Response.redirect(url, 302);
  } catch {
    // Nothing useful to show at this URL — send them back to the form,
    // which renders the message.
    return Response.redirect(new URL("/login?error=google", request.url), 302);
  }
}
