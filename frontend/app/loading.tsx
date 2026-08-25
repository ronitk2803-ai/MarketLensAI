import { Loader2 } from "lucide-react";

/**
 * Next's file-based loading boundary for this route segment — shown
 * automatically in place of page.tsx's output while a navigation is
 * waiting on the server (including a searchParams-only change, like
 * picking an industry filter: force-dynamic means every filter click is a
 * full server round trip re-running every screen, which was taking long
 * enough with zero feedback that it read as broken rather than slow —
 * reported live 2026-08-25). Disappears the instant the new page is ready.
 */
export default function Loading() {
  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col items-center justify-center gap-2 px-4 py-24">
      <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
      <p className="text-xs text-muted-foreground">Loading…</p>
    </main>
  );
}
