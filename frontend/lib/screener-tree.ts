import type { ScreenerGroup, ScreenerNode } from "@/lib/api";

/** The condition tree lives in the URL rather than in a POST body from the
 * client, so a built screen is shareable and bookmarkable and the page can
 * stay a server component like every other page here.
 *
 * Plain URI-encoded JSON, not base64: same length class, but it stays
 * readable and hand-editable in the address bar, and it avoids btoa's
 * throw on non-Latin1 input. */
export function encodeTree(tree: ScreenerGroup): string {
  return encodeURIComponent(JSON.stringify(tree));
}

const OPERATORS = new Set(["gt", "lt", "gte", "lte"]);

function isValidNode(node: unknown, depth: number): node is ScreenerNode {
  if (depth > 6 || typeof node !== "object" || node === null) return false;
  const candidate = node as Record<string, unknown>;
  if ("metric" in candidate) {
    return (
      typeof candidate.metric === "string" &&
      typeof candidate.operator === "string" &&
      OPERATORS.has(candidate.operator) &&
      typeof candidate.threshold === "number" &&
      Number.isFinite(candidate.threshold)
    );
  }
  return (
    (candidate.op === "and" || candidate.op === "or") &&
    Array.isArray(candidate.children) &&
    candidate.children.length > 0 &&
    candidate.children.every((child) => isValidNode(child, depth + 1))
  );
}

/** Returns null for anything malformed rather than throwing — a hand-edited
 * or truncated URL should fall back to an empty builder, not a 500. The
 * backend validates independently; this only decides what the page renders. */
export function decodeTree(raw: string | undefined): ScreenerGroup | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(decodeURIComponent(raw));
    if (!isValidNode(parsed, 1)) return null;
    // The root must be a group — a bare condition has no AND/OR to render.
    return "op" in (parsed as object) ? (parsed as ScreenerGroup) : null;
  } catch {
    return null;
  }
}

/** Each registered preset's exact condition-tree equivalent, so "refine in
 * the advanced builder" starts from what the user was already looking at.
 * Mirrors the thresholds frozen in the backend's screen registry — a
 * backend test asserts each of these returns the same symbols as its
 * preset, so a drift here fails CI rather than silently misleading. */
export const PRESET_TREES: Record<string, ScreenerGroup> = {
  down_5d: { op: "and", children: [{ metric: "change_5d_pct", operator: "lte", threshold: -5 }] },
  down_10d: { op: "and", children: [{ metric: "change_10d_pct", operator: "lte", threshold: -7 }] },
  down_15d: { op: "and", children: [{ metric: "change_15d_pct", operator: "lte", threshold: -8 }] },
  down_30d: { op: "and", children: [{ metric: "change_30d_pct", operator: "lte", threshold: -10 }] },
  down_60d: { op: "and", children: [{ metric: "change_60d_pct", operator: "lte", threshold: -15 }] },
  down_90d: { op: "and", children: [{ metric: "change_90d_pct", operator: "lte", threshold: -20 }] },
  below_dma50: { op: "and", children: [{ metric: "dma50_gap_pct", operator: "lt", threshold: 0 }] },
  below_dma100: {
    op: "and",
    children: [{ metric: "dma100_gap_pct", operator: "lt", threshold: 0 }],
  },
  below_dma200: {
    op: "and",
    children: [{ metric: "dma200_gap_pct", operator: "lt", threshold: 0 }],
  },
  unusual_volume: {
    op: "and",
    children: [{ metric: "relative_volume", operator: "gte", threshold: 2 }],
  },
};

export const EMPTY_TREE: ScreenerGroup = {
  op: "and",
  children: [{ metric: "change_30d_pct", operator: "lte", threshold: -10 }],
};
