import { cookies } from "next/headers";

import { addToWatchlist, ApiError, removeFromWatchlist } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";

export const dynamic = "force-dynamic";

async function requireAccessToken(): Promise<string | null> {
  return (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value ?? null;
}

export async function POST(_request: Request, { params }: { params: Promise<{ symbol: string }> }) {
  const accessToken = await requireAccessToken();
  if (!accessToken) return Response.json({ error: "not signed in" }, { status: 401 });

  const { symbol } = await params;
  try {
    await addToWatchlist(accessToken, symbol);
    return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return Response.json(
      { error: error instanceof ApiError && error.detail ? error.detail : "add failed" },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ symbol: string }> },
) {
  const accessToken = await requireAccessToken();
  if (!accessToken) return Response.json({ error: "not signed in" }, { status: 401 });

  const { symbol } = await params;
  try {
    await removeFromWatchlist(accessToken, symbol);
    return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return Response.json(
      { error: "remove failed" },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
