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
    secure: process.env.NODE_ENV === "production",
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
