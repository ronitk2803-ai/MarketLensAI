import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center gap-3 px-4 py-20 text-center">
      <h1 className="num text-2xl font-semibold">404</h1>
      <p className="text-[13px] text-muted-foreground">
        No such page — or no such symbol in the seeded universe. Only NSE equities that have been
        ingested are available.
      </p>
      <Link
        href="/"
        className="mt-1 rounded-sm border border-border px-3 py-1.5 text-[13px] hover:bg-accent"
      >
        Back to market overview
      </Link>
    </main>
  );
}
