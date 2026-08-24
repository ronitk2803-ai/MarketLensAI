"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { kpiDescription } from "@/lib/kpi-glossary";
import { cn } from "@/lib/utils";

/**
 * A metric's label, with a hover explanation of what it means, how to read
 * it, and why it matters — for any of the ratio/technical jargon (P/E,
 * ROE, beta, DMA, RSI...) a first-time visitor has no reason to already
 * know. Falls back to a plain label with no dotted underline when there's
 * no glossary entry for that metric, rather than a tooltip that just
 * repeats the label back.
 */
export function KpiLabel({ metric, label, className }: { metric: string; label: string; className?: string }) {
  const description = kpiDescription(metric);
  if (!description) {
    return <span className={cn("label-caps truncate", className)}>{label}</span>;
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className={cn(
            "label-caps w-fit truncate underline decoration-dotted decoration-muted-foreground/60 underline-offset-2 outline-none",
            className,
          )}
        >
          {label}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[280px] text-left text-[11px] leading-snug normal-case">
        {description}
      </TooltipContent>
    </Tooltip>
  );
}
