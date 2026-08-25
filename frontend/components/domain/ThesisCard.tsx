import Link from "next/link";

import type { Thesis, ThesisStance, ThesisStatus, ThesisTrigger } from "@/lib/api";
import { cn } from "@/lib/utils";

const STANCE_LABEL: Record<ThesisStance, string> = {
  bull: "Bull",
  bear: "Bear",
  neutral: "Neutral",
};

const STANCE_TONE: Record<ThesisStance, string> = {
  bull: "text-up",
  bear: "text-down",
  neutral: "text-muted-foreground",
};

const STATUS_LABEL: Record<ThesisStatus, string> = {
  active: "Active",
  challenged: "Challenged",
  invalidated: "Invalidated",
  closed: "Closed",
};

// Deliberately not a verdict color: "challenged" just means at least one
// invalidation condition has fired at some point, not that the thesis is
// wrong — that's for the reader to judge from the trigger, same reasoning
// AiSummaryPanel avoids color-coding supporting/risk factors.
const STATUS_TONE: Record<ThesisStatus, string> = {
  active: "text-muted-foreground",
  challenged: "text-[color:var(--chart-2)]",
  invalidated: "text-down",
  closed: "text-muted-foreground",
};

const OPERATOR_SYMBOL: Record<string, string> = {
  gt: ">",
  lt: "<",
  gte: "≥",
  lte: "≤",
  eq: "=",
};

function ConvictionDots({ value }: { value: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" title={`Conviction ${value}/5`}>
      {Array.from({ length: 5 }, (_, i) => (
        <span
          key={i}
          className={cn(
            "size-1.5 rounded-full",
            i < value ? "bg-foreground" : "bg-muted",
          )}
        />
      ))}
    </span>
  );
}

function TriggerRow({ trigger }: { trigger: ThesisTrigger }) {
  return (
    <li className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5 text-sm last:border-0">
      <span className="min-w-0">
        <span className="num">
          {trigger.metric} {OPERATOR_SYMBOL[trigger.operator] ?? trigger.operator}{" "}
          {trigger.threshold}
        </span>
        {trigger.description && (
          <span className="block text-[11px] text-muted-foreground">{trigger.description}</span>
        )}
      </span>
      {trigger.currently_breached && (
        <span className="shrink-0 text-[11px] font-medium text-down">breached</span>
      )}
    </li>
  );
}

/** The named UI component from Build_plan.md §X.1's spec: stance,
 * conviction, triggers, status — everything needed to judge a thesis at a
 * glance, without needing to also see the event timeline (that's rendered
 * separately by the caller, app/theses/[id]/page.tsx). */
export function ThesisCard({ thesis }: { thesis: Thesis }) {
  return (
    <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-base font-semibold tracking-tight">{thesis.title}</h1>
          <Link
            href={`/company/${thesis.symbol}`}
            className="num text-sm text-muted-foreground hover:text-primary hover:underline"
          >
            {thesis.symbol}
          </Link>
          <span className="text-sm text-muted-foreground"> · {thesis.asset_name}</span>
        </div>
        <span className={cn("text-xs font-medium", STATUS_TONE[thesis.status])}>
          {STATUS_LABEL[thesis.status]}
        </span>
      </div>

      <div className="flex items-center gap-4 text-xs">
        <span className={cn("font-medium", STANCE_TONE[thesis.stance])}>
          {STANCE_LABEL[thesis.stance]}
        </span>
        <ConvictionDots value={thesis.conviction} />
      </div>

      <p className="text-sm leading-relaxed whitespace-pre-wrap">{thesis.body}</p>

      <div>
        <p className="label-caps mb-1">What would invalidate this</p>
        <ul className="flex flex-col">
          {thesis.triggers.map((t) => (
            <TriggerRow key={t.id} trigger={t} />
          ))}
        </ul>
      </div>
    </div>
  );
}
