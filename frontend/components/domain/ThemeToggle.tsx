"use client";

import { Moon, Sun } from "lucide-react";

import { setLightTheme, THEME_STORAGE_KEY, useIsLightTheme } from "@/lib/use-theme";

/**
 * Dark is the default (this is a market screen). The `light` class goes on
 * <html>, matching the `.light` block in globals.css — inverted from the
 * usual shadcn `.dark` convention because here dark is the base palette,
 * not the override.
 */
export function ThemeToggle() {
  const light = useIsLightTheme();

  return (
    <button
      type="button"
      onClick={() => setLightTheme(!light)}
      aria-label={light ? "Switch to dark theme" : "Switch to light theme"}
      className="grid size-8 shrink-0 place-items-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
    >
      {light ? <Moon className="size-4" /> : <Sun className="size-4" />}
    </button>
  );
}

/**
 * Applies the stored theme before first paint. Inlined as a blocking script
 * in <head> so the page never flashes the wrong palette — a `useEffect`
 * would run after the first frame is already on screen.
 */
export function ThemeScript() {
  const js = `try{if(localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)})==="light"){document.documentElement.classList.add("light")}}catch(e){}`;
  return <script dangerouslySetInnerHTML={{ __html: js }} />;
}
