"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { cn } from "@/lib/utils";
import { encodeTree } from "@/lib/screener-tree";
import { isScreenerGroup } from "@/lib/api";
import type {
  OpportunityIndustry,
  ScreenerGroup,
  ScreenerMetric,
  ScreenerNode,
  ScreenerOperator,
} from "@/lib/api";

const OPERATOR_LABELS: { value: ScreenerOperator; label: string }[] = [
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
];

// `eq` is deliberately absent, matching the backend: exact float equality
// against a computed indicator can never match, so offering it would only
// produce empty results a user couldn't explain.

const UNIT_HINTS: Record<string, string> = {
  percent: "%",
  fraction: "fraction (0.15 = 15%)",
  ratio: "x",
  multiple: "x",
  price: "₹",
  index: "0-100",
};

const GROUP_LABELS: Record<string, string> = {
  price: "Price",
  technical: "Technical",
  valuation: "Valuation",
  fundamental: "Fundamental",
};

/** Immutable update at a path — the tree is nested, so editing in place
 * would mutate React state. Paths are arrays of child indices. */
function updateAt(node: ScreenerNode, path: number[], next: ScreenerNode | null): ScreenerNode | null {
  if (path.length === 0) return next;
  if (!isScreenerGroup(node)) return node;
  const [head, ...rest] = path;
  const children = node.children
    .map((child, i) => (i === head ? updateAt(child, rest, next) : child))
    .filter((child): child is ScreenerNode => child !== null);
  return { ...node, children };
}

function nodeAt(node: ScreenerNode, path: number[]): ScreenerNode | null {
  if (path.length === 0) return node;
  if (!isScreenerGroup(node)) return null;
  const [head, ...rest] = path;
  const child = node.children[head];
  return child ? nodeAt(child, rest) : null;
}

function countConditions(node: ScreenerNode): number {
  return isScreenerGroup(node)
    ? node.children.reduce((sum, child) => sum + countConditions(child), 0)
    : 1;
}

const MAX_CONDITIONS = 12;
const MAX_DEPTH = 4;

// Module scope, not nested inside the parent — a component defined inside
// another's body is a new type on every render and would remount its
// subtree (losing focus mid-edit).
function GroupNode({
  group,
  path,
  depth,
  metrics,
  onChange,
  onRemove,
}: {
  group: ScreenerGroup;
  path: number[];
  depth: number;
  metrics: ScreenerMetric[];
  onChange: (path: number[], next: ScreenerNode | null) => void;
  onRemove: (() => void) | null;
}) {
  const grouped = metrics.reduce<Record<string, ScreenerMetric[]>>((acc, metric) => {
    (acc[metric.group] ??= []).push(metric);
    return acc;
  }, {});

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-sm border border-border p-2",
        depth > 1 && "bg-surface-raised/30",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          {(["and", "or"] as const).map((op) => (
            <button
              key={op}
              type="button"
              onClick={() => onChange(path, { ...group, op })}
              className={cn(
                "rounded-sm border px-2 py-0.5 text-[11px] uppercase transition-colors",
                group.op === op
                  ? "border-primary bg-primary/15 font-medium text-foreground"
                  : "border-border text-muted-foreground hover:bg-accent/60",
              )}
            >
              {op === "and" ? "Match all" : "Match any"}
            </button>
          ))}
        </div>
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="text-[11px] text-muted-foreground hover:text-down"
          >
            Remove group
          </button>
        )}
      </div>

      {group.children.map((child, index) => {
        const childPath = [...path, index];
        if (isScreenerGroup(child)) {
          return (
            <GroupNode
              key={index}
              group={child}
              path={childPath}
              depth={depth + 1}
              metrics={metrics}
              onChange={onChange}
              onRemove={() => onChange(childPath, null)}
            />
          );
        }
        const spec = metrics.find((m) => m.key === child.metric);
        return (
          <div key={index} className="flex flex-wrap items-center gap-2">
            <select
              value={child.metric}
              onChange={(e) => onChange(childPath, { ...child, metric: e.target.value })}
              className="h-8 rounded-sm border border-input bg-surface px-2 text-xs"
            >
              {Object.entries(grouped).map(([groupKey, items]) => (
                <optgroup key={groupKey} label={GROUP_LABELS[groupKey] ?? groupKey}>
                  {items.map((m) => (
                    <option key={m.key} value={m.key}>
                      {m.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <select
              value={child.operator}
              onChange={(e) =>
                onChange(childPath, { ...child, operator: e.target.value as ScreenerOperator })
              }
              className="h-8 rounded-sm border border-input bg-surface px-2 text-xs"
            >
              {OPERATOR_LABELS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <input
              value={String(child.threshold)}
              onChange={(e) => {
                const parsed = Number.parseFloat(e.target.value);
                onChange(childPath, {
                  ...child,
                  threshold: Number.isFinite(parsed) ? parsed : 0,
                });
              }}
              inputMode="decimal"
              className="h-8 w-24 rounded-sm border border-input bg-surface px-2 text-xs"
            />
            {/* The units trap this defuses: debt_to_equity is stored as a
                percentage (23.8 means 0.24x) while growth and margins are
                fractions, so an unlabelled box would silently mismatch. */}
            <span className="text-[11px] text-muted-foreground">
              {spec ? (UNIT_HINTS[spec.unit] ?? spec.unit) : ""}
            </span>
            <button
              type="button"
              onClick={() => onChange(childPath, null)}
              className="text-[11px] text-muted-foreground hover:text-down"
            >
              Remove
            </button>
          </div>
        );
      })}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={() =>
            onChange(path, {
              ...group,
              children: [
                ...group.children,
                { metric: metrics[0]?.key ?? "close", operator: "lt", threshold: 0 },
              ],
            })
          }
          className="text-[11px] text-primary hover:underline"
        >
          + Condition
        </button>
        {depth < MAX_DEPTH && (
          <button
            type="button"
            onClick={() =>
              onChange(path, {
                ...group,
                children: [
                  ...group.children,
                  {
                    op: "or",
                    children: [
                      { metric: metrics[0]?.key ?? "close", operator: "lt", threshold: 0 },
                    ],
                  },
                ],
              })
            }
            className="text-[11px] text-primary hover:underline"
          >
            + Group
          </button>
        )}
      </div>
    </div>
  );
}

export function ConditionBuilder({
  initialTree,
  metrics,
  industries,
  initialIndustry,
}: {
  initialTree: ScreenerGroup;
  metrics: ScreenerMetric[];
  industries: OpportunityIndustry[];
  initialIndustry?: string;
}) {
  const router = useRouter();
  const [tree, setTree] = useState<ScreenerGroup>(initialTree);
  const [industry, setIndustry] = useState(initialIndustry ?? "");

  function handleChange(path: number[], next: ScreenerNode | null) {
    // The root can be edited but never removed — there'd be nothing to
    // render and nothing to submit.
    if (path.length === 0 && next === null) return;
    const updated = updateAt(tree, path, next);
    if (updated && isScreenerGroup(updated)) setTree(updated);
  }

  const conditionCount = countConditions(tree);
  const tooMany = conditionCount > MAX_CONDITIONS;

  function run() {
    const params = new URLSearchParams({ q: encodeTree(tree) });
    if (industry) params.set("industry", industry);
    router.push(`/opportunities/advanced?${params.toString()}`);
  }

  return (
    <div className="flex flex-col gap-3">
      <GroupNode
        group={tree}
        path={[]}
        depth={1}
        metrics={metrics}
        onChange={handleChange}
        onRemove={null}
      />

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs">
          <span className="label-caps">Industry</span>
          <select
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="h-8 rounded-sm border border-input bg-surface px-2 text-xs"
          >
            <option value="">All</option>
            {industries.map((i) => (
              <option key={i.code} value={i.code}>
                {i.name}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={run}
          disabled={tooMany}
          className="h-8 rounded-sm bg-primary px-4 text-xs font-medium text-primary-foreground hover:bg-primary/80 disabled:opacity-50"
        >
          Run screen
        </button>
        <span className="text-[11px] text-muted-foreground">
          {conditionCount} condition{conditionCount === 1 ? "" : "s"}
          {tooMany && ` — at most ${MAX_CONDITIONS}`}
        </span>
      </div>
    </div>
  );
}

export { nodeAt };
