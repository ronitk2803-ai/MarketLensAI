import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { cn } from "@/lib/utils";
import { scoreBarTone, scoreTone } from "@/lib/format";
import type { Meta, Score } from "@/lib/api";

const COMPONENT_LABELS: Record<string, string> = {
  valuation: "Valuation",
  fundamental_quality: "Fundamental quality",
  growth: "Growth",
  technical_setup: "Decline setup",
  participation: "Participation",
};

export function ScorePanel({ score, meta }: { score: Score; meta: Meta }) {
  const hasScore = typeof score.value === "number";

  return (
    <Panel
      title="Opportunity Score"
      actions={<ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />}
      footnote="Research attractiveness — not a predicted return, and not a buy/sell/hold recommendation. Components renormalize over whatever data exists, so coverage below 100% means some inputs were unavailable, not that they scored zero."
    >
      {!hasScore ? (
        <p className="py-6 text-center text-xs text-muted-foreground">
          Not enough data to compute a score for this company yet.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex items-end justify-between">
            <div className="flex items-baseline gap-1.5">
              <span className={cn("num text-4xl font-semibold", scoreTone(score.value))}>
                {score.value!.toFixed(0)}
              </span>
              <span className="num text-sm text-muted-foreground">/100</span>
            </div>
            <div className="text-right">
              <div className="label-caps">Coverage</div>
              <div className="num text-sm">{(score.coverage * 100).toFixed(0)}%</div>
            </div>
          </div>

          <div className="flex flex-col gap-2.5">
            {score.components.map((c) => (
              <div key={c.component} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between gap-2 text-[11px]">
                  <span className="truncate">{COMPONENT_LABELS[c.component] ?? c.component}</span>
                  <span className="num shrink-0 text-muted-foreground">
                    {c.normalized_value == null
                      ? "no data"
                      : `${c.normalized_value.toFixed(0)} · ${(c.weight * 100).toFixed(0)}%`}
                  </span>
                </div>
                <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
                  {c.normalized_value != null && (
                    <div
                      className={cn("h-full rounded-full", scoreBarTone(c.normalized_value))}
                      style={{ width: `${c.normalized_value}%` }}
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}
