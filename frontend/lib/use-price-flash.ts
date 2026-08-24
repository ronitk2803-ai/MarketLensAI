"use client";

import { useEffect, useRef, useState } from "react";

const FLASH_MS = 700;

/**
 * Briefly flags a numeric value as "just moved" and which way, for a CSS
 * flash on the number that changed.
 *
 * This is the one piece of the whole "make the user want to stay" ask that
 * a static screenshot can't show: numbers that visibly tick are what make
 * a market screen feel alive rather than merely correct, and is standard
 * language on every real trading terminal. It rides entirely on data the
 * live-quote polling already fetches — no extra request, just a transient
 * render state.
 */
export function usePriceFlash(value: number | undefined): "up" | "down" | null {
  const previous = useRef(value);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);

  useEffect(() => {
    if (value !== undefined && previous.current !== undefined && value !== previous.current) {
      setFlash(value > previous.current ? "up" : "down");
      const timer = setTimeout(() => setFlash(null), FLASH_MS);
      previous.current = value;
      return () => clearTimeout(timer);
    }
    previous.current = value;
  }, [value]);

  return flash;
}
