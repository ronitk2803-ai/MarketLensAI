import { cookies } from "next/headers";
import Link from "next/link";

import { AccountControl } from "@/components/domain/AccountControl";
import { SearchBox } from "@/components/domain/SearchBox";
import { NavLink } from "@/components/domain/NavLink";
import { ThemeToggle } from "@/components/domain/ThemeToggle";
import { getCurrentUser } from "@/lib/api";
import { ACCESS_TOKEN_COOKIE } from "@/lib/auth-cookies";

/** Reads the session cookie and asks the backend who it belongs to —
 * straight to lib/api.ts, not through a Route Handler, since this is a
 * Server Component and can reach API_BASE_URL directly (same as
 * getCompany/getPrices elsewhere). A missing/expired/invalid token all
 * just mean "signed out" here; get_current_user does the same on the
 * backend and there's nothing more specific worth telling this header. */
async function getSignedInUser() {
  const accessToken = (await cookies()).get(ACCESS_TOKEN_COOKIE)?.value;
  if (!accessToken) return null;
  return getCurrentUser(accessToken);
}

export async function AppHeader() {
  const user = await getSignedInUser();

  return (
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
        </nav>

        <ThemeToggle />
        <AccountControl user={user} />

        <div className="order-last w-full sm:order-none sm:ml-auto sm:max-w-md">
          <SearchBox />
        </div>
      </div>
    </header>
  );
}
