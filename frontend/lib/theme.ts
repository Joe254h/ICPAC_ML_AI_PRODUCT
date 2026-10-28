"use client";
/** Light or dark theme: the reader's choice, kept in this browser, else their system's. */
import { useCallback, useSyncExternalStore } from "react";
import { THEME_KEY } from "@/lib/theme-script";

export type Theme = "light" | "dark";

function current(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function subscribe(changed: () => void) {
  const watcher = new MutationObserver(changed);
  watcher.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => watcher.disconnect();
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const theme = useSyncExternalStore<Theme>(subscribe, current, () => "light");
  const set = useCallback((next: Theme) => {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      // Private browsing: the choice lasts for this page only.
    }
  }, []);
  return [theme, set];
}

/** Chart colours chosen for a light page, and what they become on a dark one. */
const NIGHT: Record<string, string> = {
  "#212529": "#e6ebe7",
  "#474c51": "#c9d1cb",
  "#7d848b": "#98a29b",
  "#e4e8eb": "#2a3530",
  "#e8ecef": "#2a3530",
  "#cfd6db": "#3b4842",
  "#adb5bd": "#6c7570",
};

/** A chart option with its text and grid colours for the dark theme; data colours and
 * functions (formatters) are kept as they are. */
export function forNight<T>(value: T): T {
  if (typeof value === "string")
    return (NIGHT[value.toLowerCase()] ?? value) as T;
  if (Array.isArray(value)) return value.map(forNight) as T;
  if (value && typeof value === "object" && value.constructor === Object)
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, forNight(item)]),
    ) as T;
  return value;
}
