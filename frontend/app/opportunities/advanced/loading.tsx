import { Loader2 } from "lucide-react";

// A condition tree scans the whole universe and can pull ~300 sessions per
// asset, so this wait is longer than the preset screener's — the segment
// needs its own boundary rather than inheriting a blank page.
export default function Loading() {
  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col items-center justify-center gap-2 px-4 py-24">
      <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
      <p className="text-xs text-muted-foreground">Running screen…</p>
    </main>
  );
}
