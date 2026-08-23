import { ExternalLink } from "lucide-react";

import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Panel } from "@/components/terminal/Panel";
import { relativeTime } from "@/lib/format";
import type { Meta, NewsItem } from "@/lib/api";

export function NewsPanel({ articles, meta }: { articles: NewsItem[]; meta: Meta }) {
  return (
    <Panel
      title="News"
      actions={<ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />}
      bodyClassName="p-0"
    >
      {articles.length === 0 ? (
        <p className="px-3 py-8 text-center text-xs text-muted-foreground">
          No recent news found for this company.
        </p>
      ) : (
        <ul className="flex flex-col">
          {articles.map((article) => (
            <li key={article.url} className="border-b border-border/50 last:border-0">
              <a
                href={article.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex flex-col gap-0.5 px-3 py-2 hover:bg-accent/40"
              >
                <span className="text-[13px] leading-snug group-hover:text-primary">
                  {article.title}
                  <ExternalLink
                    className="ml-1 inline size-3 align-baseline text-muted-foreground"
                    aria-hidden
                  />
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {article.source} · {relativeTime(article.published_at)}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
