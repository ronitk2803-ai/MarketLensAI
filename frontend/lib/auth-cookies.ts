import { cookies } from "next/headers";

/** Derived from the real return type rather than importing Next's
 * internal cookie-store type directly — that lives under a `dist/compiled`
 * path that isn't public API and can move between versions. */
type CookieStore = Awaited<ReturnType<typeof cookies>>;

/**
 * The two httpOnly cookies that ARE the session — no server-side session
 * store, matching this app's "zero extra infra beyond Postgres" approach.
 * Only ever set/cleared from the app/api/auth/* Route Handlers; read via
 * `cookies()` everywhere else (Server Components call the backend
 * directly with the value, they don't decode it — see
 * lib/api.ts's getCurrentUser).
 */
export const ACCESS_TOKEN_COOKIE = "mlai_access";
export const REFRESH_TOKEN_COOKIE = "mlai_refresh";

// Mirrors the backend's own TTLs (backend/app/core/config.py) so a cookie
// never outlives the token it holds.
const ACCESS_TOKEN_MAX_AGE_SECONDS = 60 * 60;
const REFRESH_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

function baseOptions() {
  return {
    httpOnly: true,
    // Deliberately NOT tied to NODE_ENV — the containerized deploy sets
    // NODE_ENV=production while still being served over plain HTTP (no
    // TLS anywhere in docker-compose.prod.yml), and a Secure cookie is
    // silently dropped by the browser on a non-HTTPS origin. Verified
    // live 2026-08-25: login returned a real Set-Cookie header with
    // `Secure`, the redirect to `/` "succeeded," and the header still
    // read signed-out on the next request — Chromium grants `localhost`
    // itself an exception that let earlier testing through this browser
    // pane hide the bug, but it doesn't extend to every hostname/browser
    // a real visitor might use. Set COOKIE_SECURE=true only once this app
    // is actually behind HTTPS.
    secure: process.env.COOKIE_SECURE === "true",
    sameSite: "lax" as const,
    path: "/",
  };
}

export function setAuthCookies(
  cookieStore: CookieStore,
  tokens: { access_token: string; refresh_token: string },
) {
  cookieStore.set(ACCESS_TOKEN_COOKIE, tokens.access_token, {
    ...baseOptions(),
    maxAge: ACCESS_TOKEN_MAX_AGE_SECONDS,
  });
  cookieStore.set(REFRESH_TOKEN_COOKIE, tokens.refresh_token, {
    ...baseOptions(),
    maxAge: REFRESH_TOKEN_MAX_AGE_SECONDS,
  });
}

export function clearAuthCookies(cookieStore: CookieStore) {
  cookieStore.delete(ACCESS_TOKEN_COOKIE);
  cookieStore.delete(REFRESH_TOKEN_COOKIE);
}

/** CSRF guard for the Google flow: minted before the redirect, compared on
 *  the way back. Short-lived and scoped to the callback path — it is
 *  useless anywhere else and useless a few minutes later. */
export const OAUTH_STATE_COOKIE = "mlai_oauth_state";
const OAUTH_STATE_MAX_AGE_SECONDS = 600;

export function setOAuthStateCookie(cookieStore: CookieStore, state: string) {
  cookieStore.set(OAUTH_STATE_COOKIE, state, {
    // Deliberately reuses baseOptions() rather than hand-rolling flags.
    // sameSite "lax" is load-bearing here: Google returns via a top-level
    // GET navigation, which lax permits and "strict" would drop, breaking
    // the flow with no obvious cause. And a hardcoded `secure: true` is
    // exactly what silently broke login on the container deploy (31cd617).
    ...baseOptions(),
    maxAge: OAUTH_STATE_MAX_AGE_SECONDS,
  });
}

export function clearOAuthStateCookie(cookieStore: CookieStore) {
  cookieStore.delete(OAUTH_STATE_COOKIE);
}
