"use client";

import Link from "next/link";
import { useId, useRef, useState, type ButtonHTMLAttributes, type KeyboardEvent, type ReactNode } from "react";
import { HEALTH, type Tone } from "@/lib/format";
import type { Health } from "@/lib/types";
import {
  AlertOctagon,
  AlertTriangle,
  Ban,
  ChartIcon,
  CheckCircle,
  Clock,
  HelpCircle,
  Info,
  TableIcon,
} from "./icons";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

// ------------------------------------------------------------------ status
const TONE_COLOUR: Record<Tone, string> = {
  good: "var(--good)",
  warning: "var(--warning)",
  serious: "var(--serious)",
  critical: "var(--critical)",
  down: "var(--down)",
  unknown: "var(--muted)",
  info: "var(--accent)",
};

const TONE_ICON: Record<Tone, (p: { size?: number }) => ReactNode> = {
  good: CheckCircle,
  warning: AlertTriangle,
  serious: Clock,
  critical: AlertOctagon,
  down: Ban,
  unknown: HelpCircle,
  info: Info,
};

export const toneColour = (tone: Tone) => TONE_COLOUR[tone];

/** A status is always colour + icon + words, never colour alone. `title`: the full wording, as a tooltip. */
export function StatusBadge({ tone, label, size = "sm", title }: { tone: Tone; label: string; size?: "sm" | "md"; title?: string }) {
  const IconComponent = TONE_ICON[tone];
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-surface font-medium text-ink",
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm",
      )}
    >
      <span style={{ color: TONE_COLOUR[tone] }} className="inline-flex">
        <IconComponent size={size === "sm" ? 14 : 16} />
      </span>
      {label}
    </span>
  );
}

export function HealthBadge({ health, size }: { health: Health; size?: "sm" | "md" }) {
  const meta = HEALTH[health];
  return <StatusBadge tone={meta.tone} label={meta.label} size={size} />;
}

export function ToneIcon({ tone, size = 16 }: { tone: Tone; size?: number }) {
  const IconComponent = TONE_ICON[tone];
  return (
    <span style={{ color: TONE_COLOUR[tone] }} className="inline-flex shrink-0">
      <IconComponent size={size} />
    </span>
  );
}

// ------------------------------------------------------------------ layout
export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  padded = true,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={cx("rounded-lg border border-line bg-surface", className)}>
      {title || actions ? (
        <header className="flex flex-wrap items-start justify-between gap-2 px-4 pt-3.5">
          <div className="min-w-0">
            {title ? <h2 className="text-sm font-semibold text-ink">{title}</h2> : null}
            {subtitle ? <p className="mt-0.5 text-xs text-ink-2">{subtitle}</p> : null}
          </div>
          {/* ml-auto: when a long title pushes the actions onto their own row, they stay on the right */}
          {actions ? <div className="ml-auto flex flex-wrap items-center justify-end gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={padded ? "p-4" : undefined}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions, back }: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {back ? (
          <Link href={back.href} className="mb-1 inline-block text-xs text-accent-ink hover:underline">
            ← {back.label}
          </Link>
        ) : null}
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {description ? <p className="mt-1 max-w-3xl text-sm text-ink-2">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

// ------------------------------------------------------------------ figures
export function StatTile({ label, value, detail, tone, href }: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: Tone;
  href?: string;
}) {
  const body = (
    <div className="h-full rounded-lg border border-line bg-surface px-4 py-3">
      <div className="flex items-center gap-1.5 text-xs text-ink-2">
        {tone ? <ToneIcon tone={tone} size={14} /> : null}
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
      {/* up to two lines, so narrow (phone) tiles keep the key words, such as which link is busiest */}
      {detail ? <div className="mt-0.5 line-clamp-2 text-xs wrap-break-word text-ink-2">{detail}</div> : null}
    </div>
  );
  return href ? (
    <Link href={href} className="block rounded-lg hover:ring-2 hover:ring-accent-wash">
      {body}
    </Link>
  ) : (
    body
  );
}

/** Horizontal meter: the fill carries the severity; the track is a light tint of the same colour. */
export function Meter({ value, tone, label }: { value: number | null; tone: Tone; label: string }) {
  const colour = TONE_COLOUR[tone];
  const width = value == null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value ?? undefined}
      className="h-2 w-full overflow-hidden rounded-full"
      style={{ background: `color-mix(in srgb, ${colour} 18%, transparent)` }}
    >
      <div className="h-full rounded-full" style={{ width: `${width}%`, background: colour }} />
    </div>
  );
}

// ------------------------------------------------------------------ controls
export function Button({
  variant = "secondary",
  size = "md",
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md" }) {
  return (
    <button
      type="button"
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm",
        variant === "primary" && "bg-accent text-white hover:brightness-110",
        variant === "secondary" && "border border-line bg-surface text-ink hover:bg-surface-2",
        variant === "ghost" && "text-ink-2 hover:bg-surface-2 hover:text-ink",
        variant === "danger" && "border border-line bg-surface text-danger-ink hover:bg-surface-2",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

/**
 * One choice out of a few (an ARIA radio group): a single tab stop on the chosen option,
 * and the arrow keys (plus Home and End) move the choice, as screen readers announce.
 */
export function Segmented<T extends string | number>({ value, options, onChange, label }: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (value: T) => void;
  label: string;
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const checked = options.findIndex((option) => option.value === value);
  const tabStop = checked >= 0 ? checked : 0;

  function move(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.altKey || event.ctrlKey || event.metaKey) return; // leave browser shortcuts alone
    const last = options.length - 1;
    let next: number;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = index === last ? 0 : index + 1;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = index === 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else return;
    event.preventDefault();
    buttons.current[next]?.focus();
    onChange(options[next].value);
  }

  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-line bg-surface p-0.5">
      {options.map((option, index) => (
        <button
          key={String(option.value)}
          ref={(element) => {
            buttons.current[index] = element;
          }}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          tabIndex={index === tabStop ? 0 : -1}
          onClick={() => onChange(option.value)}
          onKeyDown={(event) => move(event, index)}
          className={cx(
            "rounded px-2.5 py-1 text-xs font-medium",
            option.value === value ? "bg-surface-2 text-ink" : "text-ink-2 hover:text-ink",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** Every chart has a table twin with the same numbers (accessibility, exact values). */
export function useViewToggle(initial: "chart" | "table" = "chart") {
  const [view, setView] = useState<"chart" | "table">(initial);
  const toggle = (
    <Segmented
      label="Show as"
      value={view}
      onChange={setView}
      options={[
        { value: "chart", label: <span className="inline-flex items-center gap-1"><ChartIcon size={13} />Chart</span> },
        { value: "table", label: <span className="inline-flex items-center gap-1"><TableIcon size={13} />Table</span> },
      ]}
    />
  );
  return { view, toggle };
}

export function Field({ label, hint, error, children }: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-ink">
        {label}
      </label>
      {children(id)}
      {hint ? <p className="mt-1 text-xs text-ink-2">{hint}</p> : null}
      {error ? <p className="mt-1 text-xs text-danger-ink">{error}</p> : null}
    </div>
  );
}

// ------------------------------------------------------------------ states
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-ink-2" role="status">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-axis border-t-accent" />
      {label}
    </div>
  );
}

export function ErrorNote({ error, title = "Could not load this" }: { error: unknown; title?: string }) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return (
    <div className="flex items-start gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-ink" role="alert">
      <ToneIcon tone="critical" />
      <div>
        <div className="font-medium">{title}</div>
        {message ? <div className="text-ink-2">{message}</div> : null}
      </div>
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-ink">
      <ToneIcon tone={tone} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-6 text-center text-sm text-ink-2">{children}</div>;
}

export function KeyValues({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([key, value], index) => (
        <div key={index} className="contents">
          <dt className="text-ink-2">{key}</dt>
          <dd className="min-w-0 text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
