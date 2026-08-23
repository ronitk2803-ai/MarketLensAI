import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The terminal's single container primitive. Deliberately flatter and
 * tighter than shadcn's Card — a market screen is a grid of instrument
 * panels, so the chrome should read as a bezel, not a content card.
 */
export function Panel({
  title,
  actions,
  footnote,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  footnote?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={cn(
        "flex min-w-0 flex-col overflow-hidden rounded-md border border-border bg-surface",
        className,
      )}
    >
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-border bg-surface-raised/60 px-3 py-2">
          {typeof title === "string" ? <h2 className="label-caps">{title}</h2> : title}
          {actions}
        </header>
      )}
      <div className={cn("flex-1", bodyClassName ?? "p-3")}>{children}</div>
      {footnote && (
        <footer className="border-t border-border px-3 py-2 text-[11px] leading-snug text-muted-foreground">
          {footnote}
        </footer>
      )}
    </section>
  );
}
