import { cookies } from "next/headers";

import { ApiError, confirmVerificationCode } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const { code } = await request.json();
  if (typeof code !== "string") {
    return Response.json({ error: "code is required" }, { status: 400 });
  }

  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) {
    return Response.json({ error: "sign in first" }, { status: 401 });
  }

  try {
    const result = await confirmVerificationCode(accessToken, code);
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    // The backend returns one identical message for every way a code can
    // fail, on purpose — forward it verbatim rather than elaborating.
    const message =
      error instanceof ApiError && error.detail ? error.detail : "couldn't verify that code";
    return Response.json(
      { error: message },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
