import { searchAssets } from "@/lib/api";

/**
 * Thin BFF proxy so the client-side search box never talks to the backend
 * directly — the real API_BASE_URL stays server-side (architecture.md §E:
 * "No external provider calls from the browser — ever").
 */
export async function GET(request: Request) {
  const query = new URL(request.url).searchParams.get("q")?.trim() ?? "";
  if (!query) {
    return Response.json([]);
  }

  const results = await searchAssets(query);
  return Response.json(results);
}
