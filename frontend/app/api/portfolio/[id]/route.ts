import { cookies } from "next/headers";

import { ApiError, deleteHolding, updateHolding } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";
import type { UpdateHoldingPayload } from "@/lib/api";

export const dynamic = "force-dynamic";

async function requireAccessToken(): Promise<string | null> {
  return (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value ?? null;
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const accessToken = await requireAccessToken();
  if (!accessToken) return Response.json({ error: "not signed in" }, { status: 401 });

  const { id } = await params;
  const payload = (await request.json()) as UpdateHoldingPayload;
  try {
    const holding = await updateHolding(accessToken, Number(id), payload);
    return Response.json(holding, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return Response.json(
      { error: "couldn't update the holding" },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const accessToken = await requireAccessToken();
  if (!accessToken) return Response.json({ error: "not signed in" }, { status: 401 });

  const { id } = await params;
  try {
    await deleteHolding(accessToken, Number(id));
    return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return Response.json(
      { error: "couldn't delete the holding" },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
