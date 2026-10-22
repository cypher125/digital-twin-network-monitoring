"use client";

import { useSyncExternalStore } from "react";

// Theme: follow the operating system unless the user picks light or dark. The choice
// is a per-browser convenience kept in localStorage (it may be unavailable).

export type ThemeChoice = "system" | "light" | "dark";
const KEY = "dt-theme";
const EVENT = "dt-theme-change";

function readChoice(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function setTheme(choice: ThemeChoice) {
  try {
    if (choice === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    // storage blocked: the choice lasts for this page only
  }
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(callback: () => void) {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  window.addEventListener(EVENT, callback);
  media.addEventListener("change", callback);
  return () => {
    window.removeEventListener(EVENT, callback);
    media.removeEventListener("change", callback);
  };
}

function resolved(): "light" | "dark" {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useThemeChoice(): ThemeChoice {
  return useSyncExternalStore(subscribe, readChoice, () => "system");
}

export function useResolvedTheme(): "light" | "dark" {
  return useSyncExternalStore(subscribe, resolved, () => "light");
}

const TOKEN_NAMES = [
  "surface",
  "surface-2",
  "ink",
  "ink-2",
  "muted",
  "grid",
  "axis",
  "series-1",
  "series-2",
  "series-3",
  "good",
  "warning",
  "serious",
  "critical",
  "down",
  "seq-0",
  "seq-1",
  "seq-2",
  "seq-3",
  "seq-4",
  "seq-5",
  "seq-6",
] as const;

export type TokenName = (typeof TOKEN_NAMES)[number];
export type Tokens = Record<TokenName, string>;

const LIGHT: Tokens = {
  surface: "#fcfcfb",
  "surface-2": "#f0efec",
  ink: "#0b0b0b",
  "ink-2": "#52514e",
  muted: "#898781",
  grid: "#e1e0d9",
  axis: "#c3c2b7",
  "series-1": "#2a78d6",
  "series-2": "#eb6834",
  "series-3": "#1baf7a",
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  down: "#898781",
  "seq-0": "#cde2fb",
  "seq-1": "#9ec5f4",
  "seq-2": "#6da7ec",
  "seq-3": "#3987e5",
  "seq-4": "#256abf",
  "seq-5": "#184f95",
  "seq-6": "#0d366b",
};

const cache = new Map<string, Tokens>();

/**
 * Resolved colour values of the CSS tokens, for canvas and SVG libraries
 * (Cytoscape, Recharts) that need concrete colours. globals.css stays the single
 * source of truth; this reads it back for the theme in use.
 */
export function useTokens(): Tokens {
  useResolvedTheme(); // re-render when the theme changes
  if (typeof window === "undefined") return LIGHT;
  const theme = resolved(); // what the page shows now (also correct during hydration)
  const cached = cache.get(theme);
  if (cached) return cached;
  const style = getComputedStyle(document.documentElement);
  const tokens = { ...LIGHT };
  for (const name of TOKEN_NAMES) {
    const value = style.getPropertyValue(`--${name}`).trim();
    if (value) tokens[name] = value;
  }
  cache.set(theme, tokens);
  return tokens;
}
