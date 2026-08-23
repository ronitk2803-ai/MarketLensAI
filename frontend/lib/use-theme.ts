"use client";

import { useSyncExternalStore } from "react";

export const THEME_STORAGE_KEY = "mlai-theme";

/**
 * The <html> class list is the source of truth for the active theme (an
 * inline script in <head> sets it before first paint). Subscribing to it as
 * an external store keeps React in sync without a setState-in-effect
 * cascade, and lets any component react to a theme change.
 */
function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

export function useIsLightTheme(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => document.documentElement.classList.contains("light"),
    // Dark is the default, and the server can't know the client's stored
    // preference — the inline script corrects it before paint.
    () => false,
  );
}

export function setLightTheme(light: boolean): void {
  document.documentElement.classList.toggle("light", light);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, light ? "light" : "dark");
  } catch {
    // Private-mode storage denial shouldn't break the toggle itself.
  }
}
