import { Info } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/**
 * "source + as_of" hover affordance (architecture.md §E): every metric
 * should be able to reveal where it came from and how fresh it is, so
 * facts stay visibly distinct from interpretation.
 */
export function ProvenanceBadge({
  source,
  asOf,
  confidence,
}: {
  source: string;
  asOf: string | null;
  confidence: "high" | "low";
}) {
  const asOfLabel = asOf ? new Date(asOf).toLocaleString() : "unavailable";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-default items-center gap-1 text-xs text-muted-foreground">
          <Info className="size-3" aria-hidden />
          {confidence === "low" ? "Limited data" : "Source"}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p>Source: {source}</p>
        <p>As of: {asOfLabel}</p>
        {confidence === "low" && <p>Coverage is limited for this view.</p>}
      </TooltipContent>
    </Tooltip>
  );
}
