import { cookies } from "next/headers";

import { ApiError, importPortfolioCsv } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";

/**
 * First multipart BFF route in the app. Node's server-side `fetch`
 * natively supports a `FormData` body and re-serializes it with a fresh
 * boundary, so this just reads the incoming form and forwards it —
 * no manual header handling needed.
 */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) return Response.json({ error: "not signed in" }, { status: 401 });

  const formData = await request.formData();
  try {
    const summary = await importPortfolioCsv(accessToken, formData);
    return Response.json(summary, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    const message =
      error instanceof ApiError && error.detail ? error.detail : "couldn't import the file";
    return Response.json(
      { error: message },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
