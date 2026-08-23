import { Badge } from "@/components/ui/badge";
import { getHealth } from "@/lib/api";

export default async function Home() {
  const health = await getHealth().catch(() => null);

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-32 text-center">
      <h1 className="text-3xl font-semibold tracking-tight">mlai</h1>
      <p className="max-w-md text-muted-foreground">
        Investment research platform — foundation scaffold. Company pages, the
        Opportunity Finder, and scoring land in upcoming builds.
      </p>
      <Badge variant={health ? "default" : "destructive"}>
        API: {health ? health.status : "unreachable"}
      </Badge>
    </main>
  );
}
