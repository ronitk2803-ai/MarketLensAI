import { KpiLabel } from "@/components/domain/KpiLabel";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { cn } from "@/lib/utils";
import { scoreBarTone, scoreTone } from "@/lib/format";
import type { Meta, Score, ScoreInputs } from "@/lib/api";

const COMPONENT_LABELS: Record<string, string> = {
  valuation: "Valuation",
  fundamental_quality: "Fundamental quality",
  earnings_valuation: "Earnings valuation",
  growth: "Growth",
  technical_setup: "Decline setup",
  participation: "Participation",
};

/** Profiles are seeded only where a component is structurally invalid for
 * a sector, so this stays deliberately short — anything unmapped is on the
 * default profile and needs no explanation. */
const PROFILE_LABELS: Record<string, string> = {
  financials: "Financials",
};

/**
 * The raw numbers each component is actually built from, so the bar isn't
 * the only explanation on offer — this is what makes "why is this 62"
 * answerable by reading the panel instead of trusting it. Mirrors the same
 * blends app/engines/scoring/components.py computes from, via the
 * `score.inputs` field (app/services/scoring.py:gather_score_inputs), so
 * this can never show a different number than what the score was actually
 * computed from.
 */
function componentDetail(component: string, inputs: ScoreInputs): string | null {
  const parts: string[] = [];
  const pct1 = (v: number) => `${(v * 100).toFixed(1)}%`;

  switch (component) {
    case "valuation":
      if (inputs.price_to_book != null) parts.push(`P/B ${inputs.price_to_book.toFixed(2)}`);
      break;
    case "fundamental_quality":
      if (inputs.debt_to_equity != null) parts.push(`D/E ${inputs.debt_to_equity.toFixed(1)}%`);
      if (inputs.gross_margins != null) parts.push(`Gross margin ${pct1(inputs.gross_margins)}`);
      break;
    case "earnings_valuation":
      if (inputs.trailing_pe != null) parts.push(`P/E ${inputs.trailing_pe.toFixed(1)}`);
      break;
    case "growth":
      if (inputs.revenue_growth != null) parts.push(`Revenue ${pct1(inputs.revenue_growth)}`);
      if (inputs.earnings_growth != null) parts.push(`Earnings ${pct1(inputs.earnings_growth)}`);
      break;
    case "technical_setup":
      if (inputs.rsi14 != null) parts.push(`RSI ${inputs.rsi14.toFixed(1)}`);
      if (inputs.drawdown_pct != null) parts.push(`Drawdown ${inputs.drawdown_pct.toFixed(1)}%`);
      break;
    case "participation":
      if (inputs.relative_volume != null) parts.push(`Rel. volume ${inputs.relative_volume.toFixed(1)}x`);
      if (inputs.delivery_pct != null) parts.push(`Delivery ${inputs.delivery_pct.toFixed(1)}%`);
      break;
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function ScorePanel({ score, meta }: { score: Score; meta: Meta }) {
  const hasScore = typeof score.value === "number";
  const profileLabel = PROFILE_LABELS[score.profile.industry_code];

  // Deliberately specific rather than a generic "scores are approximate"
  // hedge: technical_setup + participation are the same functions at the
  // same combined weight in every profile, so that half is always
  // comparable across industries. The fundamental half ranks against
  // same-industry peers when enough of them have data (backend/app/
  // engines/scoring/percentile.py) and falls back to a fixed scale
  // otherwise — so its comparability depends on how much peer coverage
  // exists, not on the profile alone.
  const footnote = profileLabel
    ? `Scored with the ${profileLabel} profile: components that don't mean the same thing for this industry are excluded rather than reweighted. The decline-setup and participation components are identical across industries. The fundamental components rank against same-industry peers where enough peer data exists, and fall back to a fixed scale otherwise. Research attractiveness — not a predicted return, and not a buy/sell/hold recommendation. Components renormalize over whatever data exists, so coverage below 100% means some inputs were unavailable, not that they scored zero.`
    : "Research attractiveness — not a predicted return, and not a buy/sell/hold recommendation. Fundamental components rank against same-industry peers where enough peer data exists, and fall back to a fixed scale otherwise. Components renormalize over whatever data exists, so coverage below 100% means some inputs were unavailable, not that they scored zero.";

  return (
    <Panel
      title="Opportunity Score"
      actions={<ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />}
      footnote={footnote}
      fullscreenable
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
            <div className="flex items-end gap-4">
              {profileLabel && (
                <div className="text-right">
                  <div className="label-caps">Profile</div>
                  <div className="text-sm">{profileLabel}</div>
                </div>
              )}
              <div className="text-right">
                <div className="label-caps">Coverage</div>
                <div className="num text-sm">{(score.coverage * 100).toFixed(0)}%</div>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-2.5">
            {score.components.map((c) => {
              const detail = componentDetail(c.component, score.inputs);
              return (
                <div key={c.component} className="flex flex-col gap-1">
                  <div className="flex items-baseline justify-between gap-2 text-[11px]">
                    <KpiLabel
                      metric={c.component}
                      label={COMPONENT_LABELS[c.component] ?? c.component}
                      className="text-[11px] font-normal tracking-normal text-foreground normal-case"
                    />
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
                  {detail && <p className="text-[10.5px] text-muted-foreground">{detail}</p>}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </Panel>
  );
}
