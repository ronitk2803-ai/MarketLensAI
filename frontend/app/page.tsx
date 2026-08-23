import { SearchBox } from "@/components/domain/SearchBox";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-20 text-center">
      <h1 className="text-3xl font-semibold tracking-tight">mlai</h1>
      <p className="max-w-md text-muted-foreground">
        Investment research for Indian equities — evidence over opinions, context over noise.
        Search a company to get started.
      </p>
      <SearchBox />
    </main>
  );
}
