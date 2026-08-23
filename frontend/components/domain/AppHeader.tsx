import Link from "next/link";

import { SearchBox } from "@/components/domain/SearchBox";

export function AppHeader() {
  return (
    <header className="sticky top-0 z-20 border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          mlai
        </Link>
        <SearchBox className="flex-1" />
      </div>
    </header>
  );
}
