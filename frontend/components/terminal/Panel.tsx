"use client";

import { Maximize2, Minimize2 } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * The terminal's single container primitive. Deliberately flatter and
 * tighter than shadcn's Card — a market screen is a grid of instrument
 * panels, so the chrome should read as a bezel, not a content card.
 *
 * `fullscreenable` adds a maximize control that expands the panel to fill
 * the viewport in place (a fixed overlay, not the browser Fullscreen API —
 * that needs a permission gesture and hands the whole screen to the page,
 * which is a much bigger ask than "let me read this table without
 * scrolling a 300px box"). `children` may be a render function receiving
 * the current expanded state, for the rare panel that wants to show more
 * (e.g. more rows) once there's room — most panels can ignore this and
 * pass plain content.
 */
export function Panel({
  title,
  actions,
  footnote,
  children,
  className,
  bodyClassName,
  fullscreenable = false,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  footnote?: ReactNode;
  children: ReactNode | ((expanded: boolean) => ReactNode);
  className?: string;
  bodyClassName?: string;
  fullscreenable?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  // Escape is the universal "get me out of this" gesture, and without it
  // the only way back from a full-viewport overlay is finding the small
  // shrink icon — worse on a page you were trying to read comfortably.
  // Locking body scroll while expanded stops the backdrop's own page from
  // scrolling underneath a panel that visually looks stationary on top of
  // it.
  useEffect(() => {
    if (!expanded) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setExpanded(false);
    }
    document.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [expanded]);

  const content = typeof children === "function" ? children(expanded) : children;

  return (
    <>
      {expanded && (
        <div
          className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm"
          onClick={() => setExpanded(false)}
          aria-hidden
        />
      )}
      <section
        className={cn(
          "flex min-w-0 flex-col overflow-hidden rounded-md border border-border bg-surface",
          expanded &&
            "fixed inset-4 z-50 shadow-2xl sm:inset-8 md:inset-12 lg:inset-16",
          className,
        )}
      >
        {(title || actions || fullscreenable) && (
          <header className="flex items-center justify-between gap-3 border-b border-border bg-surface-raised/60 px-3 py-2">
            {typeof title === "string" ? <h2 className="label-caps">{title}</h2> : title}
            <div className="flex items-center gap-2">
              {actions}
              {fullscreenable && (
                <button
                  type="button"
                  onClick={() => setExpanded((e) => !e)}
                  aria-label={expanded ? "Exit full screen" : "Expand to full screen"}
                  title={expanded ? "Exit full screen (Esc)" : "Expand to full screen"}
                  className="grid size-6 shrink-0 place-items-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  {expanded ? (
                    <Minimize2 className="size-3.5" />
                  ) : (
                    <Maximize2 className="size-3.5" />
                  )}
                </button>
              )}
            </div>
          </header>
        )}
        <div className={cn("flex-1 overflow-auto", bodyClassName ?? "p-3")}>{content}</div>
        {footnote && (
          <footer className="border-t border-border px-3 py-2 text-[11px] leading-snug text-muted-foreground">
            {footnote}
          </footer>
        )}
      </section>
    </>
  );
}
