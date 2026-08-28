"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

/** Mirrors the backend's RESEND_COOLDOWN so the button doesn't invite a
 *  request that is already guaranteed to be refused. The server remains the
 *  authority — this only avoids provoking a pointless 429. */
const RESEND_COOLDOWN_SECONDS = 60;

export function VerifyEmailForm({ email }: { email: string }) {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((seconds) => seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  async function send() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch("/api/auth/verify-email/send", { method: "POST" });
      const body = (await res.json()) as { error?: string };
      if (!res.ok) {
        setError(body.error ?? "Couldn't send the code.");
        return;
      }
      setNotice(`Code sent to ${email}.`);
      setCooldown(RESEND_COOLDOWN_SECONDS);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/verify-email/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      const body = (await res.json()) as { error?: string };
      if (!res.ok) {
        setError(body.error ?? "Couldn't verify that code.");
        return;
      }
      // push + refresh, so the server re-renders the header without the
      // banner rather than leaving a stale one behind.
      router.push("/");
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-sm">
      <h1 className="text-lg font-semibold tracking-tight">Verify your email</h1>
      <p className="mt-1 text-[13px] text-muted-foreground">
        We&rsquo;ll send a 6-digit code to <span className="text-foreground">{email}</span>.
        Until it&rsquo;s confirmed you can browse everything, but not save anything.
      </p>

      <button
        type="button"
        onClick={send}
        disabled={busy || cooldown > 0}
        className="mt-4 w-full rounded-sm border border-border px-3 py-2 text-[13px] hover:bg-accent disabled:opacity-50"
      >
        {cooldown > 0 ? `Resend in ${cooldown}s` : "Send code"}
      </button>

      <form onSubmit={confirm} className="mt-4 flex flex-col gap-2">
        <label className="flex flex-col gap-1">
          <span className="label-caps">Code</span>
          <input
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="123456"
            className="num rounded-sm border border-border bg-surface px-3 py-2 tracking-[0.3em]"
            required
          />
        </label>
        <button
          type="submit"
          disabled={busy || code.length !== 6}
          className="rounded-sm bg-primary px-3 py-2 text-[13px] font-medium text-primary-foreground disabled:opacity-50"
        >
          Verify
        </button>
      </form>

      {notice && <p className="mt-3 text-[12px] text-muted-foreground">{notice}</p>}
      {error && <p className="mt-3 text-[12px] text-down">{error}</p>}
    </div>
  );
}
