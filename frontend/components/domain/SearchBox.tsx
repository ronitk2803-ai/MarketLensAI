"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { AssetSearchResult } from "@/lib/api";

export function SearchBox({ className }: { className?: string }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AssetSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
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
          setCursor(0);
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

  // "/" to focus is the convention in every terminal-style tool; guard it so
  // it doesn't hijack typing inside another field.
  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;
      if (event.key === "/" && !typing) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, []);

  function goToCompany(symbol: string) {
    setOpen(false);
    setQuery("");
    inputRef.current?.blur();
    router.push(`/company/${encodeURIComponent(symbol)}`);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || results.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => (c + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => (c - 1 + results.length) % results.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      goToCompany(results[cursor].symbol);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className={cn("relative w-full", className)}>
      <div className="relative">
        <Search
          className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="Search symbol or company"
          aria-label="Search companies"
          className="h-8 w-full rounded-sm border border-input bg-surface pr-8 pl-8 text-[13px] outline-none placeholder:text-muted-foreground focus:border-ring focus:ring-1 focus:ring-ring"
        />
        <kbd className="pointer-events-none absolute top-1/2 right-2 hidden -translate-y-1/2 rounded-sm border border-border px-1 font-mono text-[10px] text-muted-foreground sm:block">
          /
        </kbd>
      </div>

      {open && results.length > 0 && (
        <ul className="absolute z-40 mt-1 w-full overflow-hidden rounded-sm border border-border bg-popover shadow-xl">
          {results.map((result, i) => (
            <li key={`${result.exchange}:${result.symbol}`}>
              <button
                type="button"
                onClick={() => goToCompany(result.symbol)}
                onMouseEnter={() => setCursor(i)}
                className={cn(
                  "flex w-full items-baseline gap-2 px-2.5 py-1.5 text-left",
                  i === cursor && "bg-accent",
                )}
              >
                <span className="num w-24 shrink-0 text-[13px] font-medium">{result.symbol}</span>
                <span className="truncate text-xs text-muted-foreground">{result.name}</span>
                <span className="label-caps ml-auto shrink-0">{result.exchange}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
