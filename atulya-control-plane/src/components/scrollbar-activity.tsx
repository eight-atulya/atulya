"use client";

import { useEffect } from "react";

const ACTIVE_CLASS = "scrollbars-active";
const IDLE_DELAY_MS = 900;
const SCROLL_KEYS = new Set([
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "ArrowUp",
  "End",
  "Home",
  "PageDown",
  "PageUp",
  " ",
]);

export function ScrollbarActivity() {
  useEffect(() => {
    let idleTimer: number | undefined;
    const root = document.documentElement;

    const markActive = () => {
      root.classList.add(ACTIVE_CLASS);
      if (idleTimer) window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => {
        root.classList.remove(ACTIVE_CLASS);
      }, IDLE_DELAY_MS);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (SCROLL_KEYS.has(event.key)) markActive();
    };

    const passiveCapture = { passive: true, capture: true } as const;
    window.addEventListener("wheel", markActive, passiveCapture);
    window.addEventListener("touchmove", markActive, passiveCapture);
    window.addEventListener("scroll", markActive, passiveCapture);
    window.addEventListener("keydown", handleKeyDown, true);

    return () => {
      if (idleTimer) window.clearTimeout(idleTimer);
      root.classList.remove(ACTIVE_CLASS);
      window.removeEventListener("wheel", markActive, passiveCapture);
      window.removeEventListener("touchmove", markActive, passiveCapture);
      window.removeEventListener("scroll", markActive, passiveCapture);
      window.removeEventListener("keydown", handleKeyDown, true);
    };
  }, []);

  return null;
}
