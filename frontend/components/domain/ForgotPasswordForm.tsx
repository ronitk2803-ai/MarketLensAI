"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Both steps live on one page rather than two routes. The code arrives out
 * of band — the user switches to an email client and comes back — so a
 * navigation between steps would lose the address they typed and the fact
 * that a code is already in flight.
 */
export function ForgotPasswordForm() {
  const router = useRouter();
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function requestCode(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/password-reset/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        const body = (await res.json()) as { error?: string };
        setError(body.error ?? "Couldn't send the code.");
        return;
      }
      // Advances whether or not the address has an account. The backend
      // answers identically either way on purpose, and branching here
      // would hand back the account-enumeration it exists to prevent.
      setStep("code");
    } finally {
      setBusy(false);
    }
  }

  async function submitNewPassword(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/password-reset/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code, newPassword: password }),
      });
      if (!res.ok) {
        const body = (await res.json()) as { error?: string };
        setError(body.error ?? "Couldn't reset the password.");
        return;
      }
      router.push("/");
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  const inputClass = "rounded-sm border border-border bg-surface px-3 py-2 text-[13px]";
  const buttonClass =
    "rounded-sm bg-primary px-3 py-2 text-[13px] font-medium text-primary-foreground disabled:opacity-50";

  return (
    <div className="mx-auto w-full max-w-sm">
      <h1 className="text-lg font-semibold tracking-tight">Reset your password</h1>

      {step === "email" ? (
        <>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Enter your email and we&rsquo;ll send you a 6-digit code.
          </p>
          <form onSubmit={requestCode} className="mt-4 flex flex-col gap-2">
            <label className="flex flex-col gap-1">
              <span className="label-caps">Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                className={inputClass}
                required
              />
            </label>
            <button type="submit" disabled={busy} className={buttonClass}>
              Send code
            </button>
          </form>
        </>
      ) : (
        <>
          <p className="mt-1 text-[13px] text-muted-foreground">
            If <span className="text-foreground">{email}</span> has an account, a code is on
            its way. Enter it below with your new password.
          </p>
          <form onSubmit={submitNewPassword} className="mt-4 flex flex-col gap-2">
            <label className="flex flex-col gap-1">
              <span className="label-caps">Code</span>
              <input
                value={code}
                onChange={(event) =>
                  setCode(event.target.value.replace(/\D/g, "").slice(0, 6))
                }
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
                className={`${inputClass} num tracking-[0.3em]`}
                required
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="label-caps">New password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="new-password"
                minLength={8}
                className={inputClass}
                required
              />
            </label>
            <button
              type="submit"
              disabled={busy || code.length !== 6}
              className={buttonClass}
            >
              Set new password
            </button>
          </form>
        </>
      )}

      {error && <p className="mt-3 text-[12px] text-down">{error}</p>}
      <p className="mt-4 text-[12px] text-muted-foreground">
        <Link href="/login" className="text-primary underline-offset-2 hover:underline">
          Back to sign in
        </Link>
      </p>
    </div>
  );
}
