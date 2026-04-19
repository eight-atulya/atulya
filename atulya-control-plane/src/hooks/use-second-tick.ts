import { useEffect, useState } from "react";

/**
 * While `active` is true, schedules ~1 Hz re-renders so wall-clock-derived UI
 * (elapsed timers, etc.) stays in sync with `Date.now()` without coupling to
 * network polling.
 *
 * When the document is hidden, the interval is cleared (browsers throttle
 * timers anyway); when the tab becomes visible again, one immediate bump runs
 * so the next paint picks up the true elapsed time.
 */
export function useSecondTick(active: boolean): number {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!active) {
      return;
    }

    const bump = () => {
      setTick((n) => n + 1);
    };

    let intervalId: number | undefined;

    const clear = () => {
      if (intervalId !== undefined) {
        window.clearInterval(intervalId);
        intervalId = undefined;
      }
    };

    const ensureIntervalWhileVisible = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        clear();
        return;
      }
      if (intervalId !== undefined) {
        return;
      }
      intervalId = window.setInterval(bump, 1000);
    };

    const onVisibility = () => {
      if (typeof document === "undefined") {
        return;
      }
      if (document.visibilityState === "visible") {
        bump();
        ensureIntervalWhileVisible();
      } else {
        clear();
      }
    };

    ensureIntervalWhileVisible();
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
    }

    return () => {
      clear();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
    };
  }, [active]);

  return tick;
}
