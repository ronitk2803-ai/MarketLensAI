import Link from "next/link";

/**
 * Shown under the header for any signed-in account whose address hasn't
 * been confirmed. Not dismissible: it explains why saving anything is
 * currently refused, so hiding it would leave the refusal unexplained.
 *
 * Rendered from AppHeader rather than the root layout because AppHeader
 * already awaits getSignedInUser() — the same argument the /auth/me
 * payload makes for carrying unread_alert_count. From layout.tsx this
 * would cost a second round trip on every page render.
 */
export function VerifyEmailBanner({ email }: { email: string }) {
  return (
    <div className="border-b border-border bg-[color:var(--chart-2)]/10 px-4 py-1.5 text-[12px]">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-foreground">
          Confirm <span className="font-medium">{email}</span> to save watchlists, theses and
          holdings.
        </span>
        <Link href="/verify-email" className="font-medium text-primary underline-offset-2 hover:underline">
          Verify now
        </Link>
      </div>
    </div>
  );
}
