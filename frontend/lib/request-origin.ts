/**
 * Builds an absolute URL on the origin the BROWSER actually requested —
 * never on `request.url`'s own origin.
 *
 * In the containerized deploy, this Next server binds `0.0.0.0` inside the
 * container, and Route Handlers' `request.url` reflects that bind address
 * rather than the `Host` header the client sent. Verified live: a request
 * made with `Host: localhost:3000` produced
 * `request.url === "http://0.0.0.0:3000/..."`, while `request.headers.get
 * ("host")` correctly read `"localhost:3000"`.
 *
 * This is invisible for routes that only read `request.url`'s
 * *searchParams* — the bogus origin doesn't affect the query string. It is
 * a real bug for anything that builds a NEW absolute URL from it, which
 * for this app means exactly one thing: the Google OAuth redirect targets.
 * `NextResponse.redirect(new URL("/", request.url))` sent the browser to
 * `http://0.0.0.0:3000/` — a DIFFERENT origin from `http://localhost:3000`
 * as far as the browser's cookie jar and same-origin policy are concerned.
 * The session cookies the callback had just set (correctly, scoped to
 * `localhost`) were simply never sent on the next request, because that
 * request went to `0.0.0.0` instead. Server-side, sign-in looked perfect —
 * a real token exchange, a real linked account — and the browser still
 * showed "Sign in", because the redirect silently hopped origins.
 *
 * `x-forwarded-host`/`x-forwarded-proto` are checked first so this also
 * behaves correctly behind a real reverse proxy (Vercel, Render, or
 * anything else fronting this app later) without any code change.
 */
export function absoluteUrl(path: string, request: Request): URL {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (!host) {
    // No Host header at all would be unusual for a real browser request —
    // fall back to the (possibly wrong) request.url origin rather than
    // throwing, so a redirect still goes somewhere.
    return new URL(path, request.url);
  }
  const protocol =
    request.headers.get("x-forwarded-proto") ?? new URL(request.url).protocol.replace(":", "");
  return new URL(path, `${protocol}://${host}`);
}
