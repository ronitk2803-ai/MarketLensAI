import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import type { Meta, NewsItem } from "@/lib/api";

function formatRelative(iso: string): string {
  const published = new Date(iso).getTime();
  const hours = Math.round((Date.now() - published) / (1000 * 60 * 60));
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function NewsPanel({ articles, meta }: { articles: NewsItem[]; meta: Meta }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-sm font-medium">News</CardTitle>
        <ProvenanceBadge source={meta.source} asOf={meta.as_of} confidence={meta.confidence} />
      </CardHeader>
      <CardContent>
        {articles.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recent news found for this company.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {articles.map((article) => (
              <li key={article.url} className="border-b pb-3 last:border-0 last:pb-0">
                <a
                  href={article.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium hover:underline"
                >
                  {article.title}
                </a>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {article.source} · {formatRelative(article.published_at)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
