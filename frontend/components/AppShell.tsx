"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ApiError, get, post, setUnauthenticatedHandler } from "@/lib/api";
import { engineBadge, fmtDateTime, fmtTime, ROLE_LABEL } from "@/lib/format";
import { useActiveAlerts, useLive, useMe } from "@/lib/queries";
import { setTheme, useThemeChoice, type ThemeChoice } from "@/lib/theme";
import type { User } from "@/lib/types";
import { Bell, Flask, LayoutGrid, LogOut, Monitor, Moon, Server, Sun, TrendingUp } from "./icons";
import { Button, cx, ErrorNote, Loading, StatusBadge } from "./ui";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutGrid, match: ["/", "/link", "/device"] },
  { href: "/alerts", label: "Alerts", icon: Bell, match: ["/alerts"] },
  { href: "/simulation", label: "Simulation", icon: Flask, match: ["/simulation", "/result"] },
  { href: "/trends", label: "Trends", icon: TrendingUp, match: ["/trends"] },
  { href: "/system", label: "System", icon: Server, match: ["/system"] },
];

const ACTIVITY_PING_MS = 60_000;

/** Signed-in area: checks the session, then shows the dashboard frame. */
export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useMe();
  const lastPing = useRef(Number.NEGATIVE_INFINITY);

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      queryClient.clear();
      router.replace(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
    });
    return () => setUnauthenticatedHandler(null);
  }, [queryClient, router]);

  // Real use of the page (clicks, keys) counts as activity for the 30-minute write
  // rule (D8); automatic refreshes do not. At most one ping a minute, the first one
  // straight away (loading the page fetches auth/me as an automatic request).
  useEffect(() => {
    const ping = () => {
      const now = performance.now();
      if (now - lastPing.current < ACTIVITY_PING_MS) return;
      lastPing.current = now;
      get<User>("auth/me")
        .then((user) => queryClient.setQueryData(["me"], user))
        .catch(() => undefined);
    };
    window.addEventListener("pointerdown", ping);
    window.addEventListener("keydown", ping);
    return () => {
      window.removeEventListener("pointerdown", ping);
      window.removeEventListener("keydown", ping);
    };
  }, [queryClient]);

  const authError = me.error instanceof ApiError && (me.error.code === "not_authenticated" || me.error.status === 403);
  useEffect(() => {
    if (authError) router.replace(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  }, [authError, router]);

  if (me.isPending || authError) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loading label="Checking your session…" />
      </div>
    );
  }
  if (me.error || !me.data) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16">
        <ErrorNote error={me.error} title="The dashboard cannot reach the server" />
        <Button className="mt-4" onClick={() => me.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  return <AppShell user={me.data}>{children}</AppShell>;
}

function AppShell({ user, children }: { user: User; children: ReactNode }) {
  const pathname = usePathname();
  const alerts = useActiveAlerts();
  const alertCount = alerts.data?.alerts.length ?? 0;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
          <Link href="/" className="flex items-center gap-2 font-semibold text-ink">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-accent text-white">
              <NetworkMark />
            </span>
            <span className="hidden sm:inline">Network Digital Twin</span>
          </Link>
          {/* on a phone the links wrap onto a second row rather than scrolling out of sight */}
          <nav aria-label="Main" className="order-3 -mx-1 flex w-full flex-wrap gap-1 md:order-none md:w-auto">
            {NAV.map((item) => {
              const active = item.match.some((m) => (m === "/" ? pathname === "/" : pathname.startsWith(m)));
              const IconComponent = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm",
                    active ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                  )}
                >
                  <IconComponent size={15} />
                  {item.label}
                  {item.href === "/alerts" && alertCount > 0 ? (
                    <span className="num rounded-full bg-critical px-1.5 text-xs font-semibold text-white" aria-label={`${alertCount} active`}>
                      {alertCount}
                    </span>
                  ) : null}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <LiveStatus />
            <UserMenu user={user} />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] px-4 py-5">{children}</main>
    </div>
  );
}

function NetworkMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} aria-hidden>
      <circle cx="12" cy="5" r="2.5" />
      <circle cx="5" cy="19" r="2.5" />
      <circle cx="19" cy="19" r="2.5" />
      <path d="M10.8 7.2 6.2 16.8M13.2 7.2l4.6 9.6M7.5 19h9" />
    </svg>
  );
}

/** Engine state and network time, from the 1-second `live` poll. */
export function LiveStatus() {
  const live = useLive();
  if (live.isPending) return <span className="text-xs text-ink-2">Connecting…</span>;
  if (live.error || !live.data) return <StatusBadge tone="critical" label="Server unreachable" />;
  const data = live.data;
  // a short word in the header; the engine's own wording is in the tooltip
  const { tone, label } = engineBadge(data.engine_state, data.stale);
  const title = [
    `Engine: ${data.engine_state}`,
    data.last_cycle ? `Last stored cycle: ${fmtDateTime(data.last_cycle)} (WAT)` : "No cycle stored yet",
    data.mode ? `Source: ${data.mode}${data.mode === "live" && data.speed ? `, ${data.speed}× real time` : ""}` : null,
    data.last_error ? `Last error: ${data.last_error}` : null,
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <div className="flex items-center gap-2" title={title}>
      <StatusBadge tone={tone} label={label} />
      {data.network_time ? (
        <span className="num hidden text-xs text-ink-2 lg:inline">
          Network time {fmtTime(data.network_time)} WAT
          {data.mode === "live" && data.speed && data.speed !== 1 ? ` · ${data.speed}×` : ""}
          {data.mode === "stepped" ? " · stepped" : ""}
        </span>
      ) : null}
    </div>
  );
}

const THEMES: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
  { value: "system", label: "Use system setting", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

/**
 * Account panel. A disclosure (a button that shows and hides a panel), not an ARIA menu:
 * Tab moves through the panel. A click outside, Escape or moving focus elsewhere closes
 * it, and Escape puts focus back on the button.
 */
function UserMenu({ user }: { user: User }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const theme = useThemeChoice();
  const [open, setOpen] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const themeLabelId = useId();

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (container.current && !container.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  async function logout() {
    setSignOutError(null);
    try {
      await post("auth/logout");
    } catch (problem) {
      // a session that has already ended (expired, or signed out in another tab) needs no sign-out;
      // otherwise the session cookie is still valid, so do not pretend the user is signed out
      if (!(problem instanceof ApiError && problem.code === "not_authenticated")) {
        setSignOutError("Sign-out did not complete, so you are still signed in. Please try again.");
        return;
      }
    }
    queryClient.clear();
    router.replace("/login");
  }

  const initials = (user.full_name || user.username)
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div
      className="relative"
      ref={container}
      onBlur={(event) => {
        // focus moved to another part of the page (Tab or Shift+Tab out of the panel)
        const next = event.relatedTarget;
        if (next instanceof Node && !event.currentTarget.contains(next)) setOpen(false);
      }}
    >
      <button
        ref={trigger}
        type="button"
        onClick={() => {
          setOpen((value) => !value);
          setSignOutError(null);
        }}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-surface-2"
      >
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-surface-2 text-xs font-semibold text-ink">
          {initials}
        </span>
        <span className="hidden text-left leading-tight xl:block">
          <span className="block text-xs font-medium text-ink">{user.full_name || user.username}</span>
          <span className="block text-[11px] text-ink-2">{ROLE_LABEL[user.role]}</span>
        </span>
      </button>
      <div id={panelId} hidden={!open} className="absolute right-0 z-40 mt-1 w-64 rounded-lg border border-line bg-surface p-1 shadow-lg">
        <div className="px-3 py-2">
          <div className="text-sm font-medium text-ink">{user.full_name || user.username}</div>
          <div className="text-xs text-ink-2">
            {user.username} · {ROLE_LABEL[user.role]}
          </div>
        </div>
        <div className="my-1 border-t border-line" />
        <div id={themeLabelId} className="px-3 pb-1 pt-1 text-[11px] font-medium uppercase tracking-wide text-muted">
          Theme
        </div>
        <div role="group" aria-labelledby={themeLabelId}>
          {THEMES.map((option) => {
            const IconComponent = option.icon;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={theme === option.value}
                onClick={() => setTheme(option.value)}
                className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm text-ink hover:bg-surface-2"
              >
                <IconComponent size={15} />
                <span className="flex-1">{option.label}</span>
                {theme === option.value ? (
                  <span className="text-sm font-bold" aria-hidden>
                    ✓
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        <div className="my-1 border-t border-line" />
        <Link
          href="/system#password"
          onClick={() => setOpen(false)}
          className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm text-ink hover:bg-surface-2"
        >
          Change password
        </Link>
        <button
          type="button"
          onClick={logout}
          className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm text-ink hover:bg-surface-2"
        >
          <LogOut size={15} />
          Sign out
        </button>
        {signOutError ? (
          <p role="alert" className="px-3 pb-1.5 pt-1 text-xs text-danger-ink">
            {signOutError}
          </p>
        ) : null}
      </div>
    </div>
  );
}
