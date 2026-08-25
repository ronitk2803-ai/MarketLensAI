"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Panel } from "@/components/terminal/Panel";

/**
 * Shared shape for /login and /register — same fields, same submit/error/
 * redirect flow, just a different endpoint and button copy. Posts to the
 * matching app/api/auth/* Route Handler (never the backend directly —
 * that's what sets the httpOnly session cookies) and does a full
 * navigation to `/` on success so the server re-renders AppHeader signed
 * in, rather than trying to patch client state to match.
 */
export function AuthForm({
  mode,
}: {
  mode: "login" | "register";
}) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isRegister = mode === "register";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const body = (await res.json()) as { status?: string; error?: string };
      if (!res.ok) {
        setError(body.error ?? (isRegister ? "Registration failed." : "Sign in failed."));
        return;
      }
      router.push("/");
      router.refresh();
    } catch {
      setError("Something went wrong — try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center px-4 py-12">
      <Panel title={isRegister ? "Create an account" : "Sign in"}>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-3 py-4">
          <label className="flex flex-col gap-1">
            <span className="label-caps">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-8 rounded-sm border border-input bg-surface px-2.5 text-sm outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label-caps">Password</span>
            <input
              type="password"
              required
              minLength={isRegister ? 8 : undefined}
              autoComplete={isRegister ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-8 rounded-sm border border-input bg-surface px-2.5 text-sm outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring"
            />
            {isRegister && (
              <span className="text-[11px] text-muted-foreground">At least 8 characters.</span>
            )}
          </label>

          {error && <p className="text-xs text-down">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="mt-1 h-8 rounded-sm bg-primary text-sm font-medium text-primary-foreground hover:bg-primary/80 disabled:opacity-50"
          >
            {loading ? "Please wait…" : isRegister ? "Create account" : "Sign in"}
          </button>

          <p className="text-center text-[11px] text-muted-foreground">
            {isRegister ? (
              <>
                Already have an account?{" "}
                <Link href="/login" className="text-primary hover:underline">
                  Sign in
                </Link>
              </>
            ) : (
              <>
                Need an account?{" "}
                <Link href="/register" className="text-primary hover:underline">
                  Create one
                </Link>
              </>
            )}
          </p>
        </form>
      </Panel>
    </main>
  );
}
