"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import type { AssetSearchResult } from "@/lib/api";

export function SearchBox({ className }: { className?: string }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AssetSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    const trimmed = query.trim();
    const timeout = setTimeout(() => {
      if (trimmed.length < 1) {
        setResults([]);
        return;
      }
      fetch(`/api/search?q=${encodeURIComponent(trimmed)}`)
        .then((res) => res.json())
        .then((data: AssetSearchResult[]) => {
          setResults(data);
          setOpen(true);
        })
        .catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(timeout);
  }, [query]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function goToCompany(symbol: string) {
    setOpen(false);
    setQuery("");
    router.push(`/company/${symbol}`);
  }

  return (
    <div ref={containerRef} className={`relative w-full max-w-sm ${className ?? ""}`}>
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && results.length > 0) {
              goToCompany(results[0].symbol);
            }
          }}
          placeholder="Search Nifty 500 companies…"
          className="pl-8"
        />
      </div>
      {open && results.length > 0 && (
        <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-md border bg-popover shadow-md">
          {results.map((result) => (
            <li key={`${result.exchange}:${result.symbol}`}>
              <button
                type="button"
                onClick={() => goToCompany(result.symbol)}
                className="flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-accent"
              >
                <span className="font-medium">{result.symbol}</span>
                <span className="text-xs text-muted-foreground">{result.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
