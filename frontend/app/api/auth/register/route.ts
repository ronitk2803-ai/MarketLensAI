import { cookies } from "next/headers";

import { ApiError, registerUser } from "@/lib/api";
import { setAuthCookies } from "@/lib/auth-cookies";

/**
 * BFF proxy + the only place session cookies get set on register — the
 * register form (a Client Component, since it needs interactivity) can't
 * reach API_BASE_URL or set httpOnly cookies itself, same boundary as
 * every other app/api/* route.
 */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const { email, password } = await request.json();
  if (typeof email !== "string" || typeof password !== "string") {
    return Response.json({ error: "email and password are required" }, { status: 400 });
  }

  try {
    const tokens = await registerUser(email, password);
    setAuthCookies(await cookies(), tokens);
    return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    const message = error instanceof ApiError && error.detail ? error.detail : "registration failed";
    return Response.json(
      { error: message },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
