import { cookies } from "next/headers";

import { ApiError, createThesis } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";
import type { CreateThesisPayload } from "@/lib/api";

/**
 * BFF proxy for the create-thesis form (a Client Component — it can't
 * reach API_BASE_URL or read the session cookie itself). Reads
 * (GET /theses, GET /theses/{id}) go straight from Server Components
 * instead — see app/theses/page.tsx.
 */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) {
    return Response.json({ error: "not signed in" }, { status: 401 });
  }

  const payload = (await request.json()) as CreateThesisPayload;
  try {
    const thesis = await createThesis(accessToken, payload);
    return Response.json(thesis, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    const message =
      error instanceof ApiError && error.detail ? error.detail : "couldn't create the thesis";
    return Response.json(
      { error: message },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
