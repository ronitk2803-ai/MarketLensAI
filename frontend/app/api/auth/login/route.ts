import { cookies } from "next/headers";

import { ApiError, loginUser } from "@/lib/api";
import { setAuthCookies } from "@/lib/auth-cookies";

export const dynamic = "force-dynamic";

/** Cold-start ceiling — see app/api/auth/google/callback/route.ts. Every
 * handler here blocks on the free-tier backend. */
export const maxDuration = 60;

export async function POST(request: Request) {
  const { email, password } = await request.json();
  if (typeof email !== "string" || typeof password !== "string") {
    return Response.json({ error: "email and password are required" }, { status: 400 });
  }

  try {
    const tokens = await loginUser(email, password);
    setAuthCookies(await cookies(), tokens);
    return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    const message =
      error instanceof ApiError && error.detail ? error.detail : "sign in failed";
    return Response.json(
      { error: message },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
