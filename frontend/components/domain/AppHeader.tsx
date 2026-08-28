import { Bell } from "lucide-react";
import Link from "next/link";

import { AccountControl } from "@/components/domain/AccountControl";
import { SearchBox } from "@/components/domain/SearchBox";
import { NavLink } from "@/components/domain/NavLink";
import { ThemeToggle } from "@/components/domain/ThemeToggle";
import { VerifyEmailBanner } from "@/components/domain/VerifyEmailBanner";
import { getSignedInUser } from "@/lib/session";

export async function AppHeader() {
  const user = await getSignedInUser();
  const unread = user?.unread_alert_count ?? 0;

  return (
    <>
    <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur">
      {/* Below `sm` the search drops to its own row rather than competing
          with the nav for width — hiding the nav instead would leave no way
          to reach the screener on a phone. */}
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 sm:h-12 sm:flex-nowrap sm:py-0">
        <Link href="/" className="flex shrink-0 items-center gap-2">
          <span className="grid size-6 place-items-center rounded-sm bg-primary text-[10px] font-bold text-primary-foreground">
            ML
          </span>
          <span className="text-sm font-semibold tracking-tight">MarketLens AI</span>
        </Link>

        <nav className="flex items-center gap-1">
          <NavLink href="/">Markets</NavLink>
          <NavLink href="/opportunities">Screener</NavLink>
          <NavLink href="/portfolio">Portfolio</NavLink>
          <NavLink href="/theses">Theses</NavLink>
        </nav>

        <ThemeToggle />
        {/* Rendered from the session payload already in hand, so the count
            is correct on first paint rather than popping in after a client
            fetch. Signed-out visitors have no alerts, so no bell. */}
        {user && (
          <Link
            href="/alerts"
            aria-label={unread > 0 ? `Alerts (${unread} unread)` : "Alerts"}
            title={unread > 0 ? `${unread} unread` : "Alerts"}
            className="relative grid size-8 shrink-0 place-items-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Bell className="size-4" aria-hidden />
            {unread > 0 && (
              <span className="absolute -top-0.5 -right-0.5 grid min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] leading-4 font-medium text-primary-foreground">
                {unread > 9 ? "9+" : unread}
              </span>
            )}
          </Link>
        )}
        <AccountControl user={user} />

        <div className="order-last w-full sm:order-none sm:ml-auto sm:max-w-md">
          <SearchBox />
        </div>
      </div>
    </header>
    {user && !user.email_verified && <VerifyEmailBanner email={user.email} />}
    </>
  );
}
