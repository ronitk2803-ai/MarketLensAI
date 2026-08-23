import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import type { Meta, Score } from "@/lib/api";

const COMPONENT_LABELS: Record<string, string> = {
  valuation: "Valuation",
  fundamental_quality: "Fundamental Quality",
  growth: "Growth",
  technical_setup: "Decline Setup",
  participation: "Market Participation",
};

function scoreColor(value: number): string {
  if (value >= 66) return "bg-emerald-500";
  if (value >= 33) return "bg-amber-500";
  return "bg-red-500";
}

export function ScorePanel({ score, meta }: { score: Score; meta: Meta }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-sm font-medium">Opportunity Score</CardTitle>
        <ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <p className="text-xs text-muted-foreground">
          Research attractiveness / opportunity characteristics — not a predicted return, and not
          a buy/sell/hold recommendation. The final decision is yours.
        </p>

        {score.value === null ? (
          <p className="text-sm text-muted-foreground">
            Not enough data available yet to compute a score for this company.
          </p>
        ) : (
          <>
            <div className="flex items-baseline gap-3">
              <span className="text-3xl font-semibold tabular-nums">{score.value.toFixed(0)}</span>
              <span className="text-sm text-muted-foreground">/ 100</span>
              <span className="text-xs text-muted-foreground">
                {(score.coverage * 100).toFixed(0)}% data coverage
              </span>
            </div>

            <div className="flex flex-col gap-3">
              {score.components.map((c) => (
                <div key={c.component} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between text-xs">
                    <span>{COMPONENT_LABELS[c.component] ?? c.component}</span>
                    <span className="text-muted-foreground">
                      {c.normalized_value === null
                        ? "unavailable"
                        : `${c.normalized_value.toFixed(0)} × ${(c.weight * 100).toFixed(0)}% weight`}
                    </span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    {c.normalized_value !== null && (
                      <div
                        className={`h-full rounded-full ${scoreColor(c.normalized_value)}`}
                        style={{ width: `${c.normalized_value}%` }}
                      />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
