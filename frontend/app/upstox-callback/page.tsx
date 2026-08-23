"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { Panel } from "@/components/terminal/Panel";

// Nothing here talks to the backend — this page only displays the `code`
// Upstox's own redirect appends to the URL, so it can be copied into
// POST /api/v1/admin/upstox/token by hand (architecture/claude/Deployment.md
// §5). No credentials pass through this app at any point.
function CallbackContent() {
  const params = useSearchParams();
  const code = params.get("code");
  const error = params.get("error");
  const [copied, setCopied] = useState(false);

  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col px-4 py-10">
      <Panel
        title="Upstox authorization"
        footnote="This page never sees your password, PIN, or TOTP — those stay on Upstox's own login page. It only reads the one-time code Upstox puts in this URL."
      >
        <div className="flex flex-col gap-3">
          {error && (
            <p className="text-[13px] text-down">
              Upstox returned an error: <span className="num">{error}</span>
            </p>
          )}

          {!error && !code && (
            <p className="text-[13px] text-muted-foreground">
              No authorization code in the URL. This page is only meant to be reached via
              Upstox&apos;s login redirect.
            </p>
          )}

          {code && (
            <>
              <p className="text-[13px] text-muted-foreground">
                Copy this code and redeem it within a couple of minutes — it is single-use and
                short-lived.
              </p>
              <code className="num rounded-sm border border-border bg-surface-raised px-3 py-2 text-xs break-all">
                {code}
              </code>
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard.writeText(code);
                  setCopied(true);
                }}
                className="self-start rounded-sm border border-border px-3 py-1.5 text-[13px] hover:bg-accent"
              >
                {copied ? "Copied" : "Copy code"}
              </button>
            </>
          )}
        </div>
      </Panel>
    </main>
  );
}

export default function UpstoxCallbackPage() {
  return (
    <Suspense fallback={null}>
      <CallbackContent />
    </Suspense>
  );
}
