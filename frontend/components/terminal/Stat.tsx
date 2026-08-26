import type { ReactNode } from "react";

import { KpiLabel } from "@/components/domain/KpiLabel";
import { cn } from "@/lib/utils";

/**
 * One labelled figure in a horizontal strip — the terminal's smallest
 * readout. Separated by a left rule rather than boxed, so a row of them
 * reads as one instrument cluster instead of a row of cards.
 *
 * `hint` is the secondary line underneath: the interpretation ("Oversold",
 * "price +4.2%", "still making new lows"), never a second number competing
 * with the first.
 */
export function Stat({
  label,
  glossaryKey,
  value,
  hint,
  hintTone,
}: {
  label: string;
  /** Key into KPI_GLOSSARY — omit for a stat with no jargon to explain. */
  glossaryKey?: string;
  value: ReactNode;
  hint?: ReactNode;
  hintTone?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 border-l border-border px-3 py-1 first:border-l-0 first:pl-0">
      {glossaryKey ? (
        <KpiLabel metric={glossaryKey} label={label} className="w-fit" />
      ) : (
        <span className="label-caps">{label}</span>
      )}
      <span className="num text-sm font-medium">{value}</span>
      {hint && <span className={cn("text-[10px]", hintTone ?? "text-muted-foreground")}>{hint}</span>}
    </div>
  );
}
