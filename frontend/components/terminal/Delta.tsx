import { ArrowDown, ArrowUp } from "lucide-react";

import { cn } from "@/lib/utils";
import { pct, tone } from "@/lib/format";

/**
 * Signed percentage change with a directional arrow. The arrow carries the
 * direction redundantly with colour so red/green isn't the only channel —
 * roughly 1 in 12 men has a red-green colour deficiency, and this is the
 * single most-scanned number on the screen.
 */
export function Delta({
  value,
  className,
  showIcon = true,
  digits = 2,
}: {
  value: number | null | undefined;
  className?: string;
  showIcon?: boolean;
  digits?: number;
}) {
  const Icon = value == null || value === 0 ? null : value > 0 ? ArrowUp : ArrowDown;
  return (
    <span className={cn("num inline-flex items-center gap-0.5", tone(value), className)}>
      {showIcon && Icon && <Icon className="size-3 shrink-0" aria-hidden />}
      {pct(value, digits)}
    </span>
  );
}
