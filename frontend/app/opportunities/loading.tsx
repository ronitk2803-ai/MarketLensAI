import { Loader2 } from "lucide-react";

// See app/loading.tsx — same reasoning, this route has the same
// screen/industry filter pills and the same silent multi-second wait.
export default function Loading() {
  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col items-center justify-center gap-2 px-4 py-24">
      <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
      <p className="text-xs text-muted-foreground">Loading…</p>
    </main>
  );
}
