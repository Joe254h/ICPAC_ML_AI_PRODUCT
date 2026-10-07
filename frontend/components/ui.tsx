"use client";
/**
 * Small shadcn/ui-style primitives (Card, Badge, Button, Stat, ...) on the design
 * tokens in app/globals.css. Status colour always comes with an icon and a label.
 */
import Link from "next/link";
import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  FlaskConical,
  ImageOff,
  LoaderCircle,
  RefreshCw,
  XCircle,
} from "lucide-react";
import type { SeriesKey } from "@/lib/format";
import { SERIES } from "@/lib/format";

export function cx(...names: (string | false | null | undefined)[]) {
  return names.filter(Boolean).join(" ");
}

export function Card({
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={cx(
        "rounded-xl border border-border bg-card text-card-foreground",
        className,
      )}
      {...rest}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  title,
  description,
  action,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "flex flex-wrap items-start justify-between gap-3 px-5 pt-5",
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="text-[1.07rem] font-semibold tracking-tight">{title}</h2>
        {description && (
          <p className="mt-1 text-muted-foreground">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}

export function CardContent({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={cx("p-5", className)}>{children}</div>;
}

export type Tone =
  | "neutral"
  | "good"
  | "warning"
  | "serious"
  | "critical"
  | "info";

const TONES: Record<Tone, string> = {
  neutral: "border-border bg-muted text-muted-foreground",
  good: "border-status-good/40 bg-status-good/10 text-status-good-ink",
  warning:
    "border-status-warning/50 bg-status-warning/12 text-status-warning-ink",
  serious:
    "border-status-serious/50 bg-status-serious/12 text-status-serious-ink",
  critical:
    "border-status-critical/50 bg-status-critical/10 text-status-critical-ink",
  info: "border-primary/30 bg-accent text-accent-foreground",
};

export function Badge({
  tone = "neutral",
  icon,
  children,
  className,
}: {
  tone?: Tone;
  icon?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[0.78rem] font-medium",
        TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/** Model registry status, with icon and label (never colour alone). */
export function ModelStatus({ status }: { status?: string }) {
  if (status === "production")
    return (
      <Badge tone="good" icon={<CheckCircle2 size={13} />}>
        Production
      </Badge>
    );
  if (status === "candidate")
    return (
      <Badge tone="warning" icon={<FlaskConical size={13} />}>
        Candidate · not production
      </Badge>
    );
  if (status === "experimental")
    return (
      <Badge tone="neutral" icon={<CircleDashed size={13} />}>
        Experimental
      </Badge>
    );
  return (
    <Badge tone="neutral" icon={<CircleDashed size={13} />}>
      {status ?? "Unknown"}
    </Badge>
  );
}

export function TestStatus({ status }: { status?: string }) {
  if (status === "passed")
    return (
      <Badge tone="good" icon={<CheckCircle2 size={13} />}>
        Independent test passed
      </Badge>
    );
  if (status === "failed")
    return (
      <Badge tone="critical" icon={<XCircle size={13} />}>
        Independent test failed
      </Badge>
    );
  return (
    <Badge tone="neutral" icon={<CircleDashed size={13} />}>
      Independent test pending
    </Badge>
  );
}

export function SyntheticBadge() {
  return (
    <Badge tone="serious" icon={<AlertTriangle size={13} />}>
      Synthetic input · not a real forecast
    </Badge>
  );
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
  busy?: boolean;
};

const VARIANTS = {
  primary: "bg-primary text-primary-foreground hover:brightness-110",
  secondary: "border border-border bg-card hover:bg-muted",
  ghost: "hover:bg-muted",
};

export function Button({
  variant = "secondary",
  busy,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={cx(
        "inline-flex h-9 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3.5 font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        className,
      )}
      disabled={disabled || busy}
      {...rest}
    >
      {busy && <LoaderCircle size={15} className="spin" />}
      {children}
    </button>
  );
}

export function LinkButton({
  href,
  variant = "secondary",
  className,
  children,
  download,
}: {
  href: string;
  variant?: "primary" | "secondary" | "ghost";
  className?: string;
  children: React.ReactNode;
  download?: boolean;
}) {
  const classes = cx(
    "inline-flex h-9 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3.5 font-medium transition",
    VARIANTS[variant],
    className,
  );
  return href.startsWith("/api/") || download ? (
    <a className={classes} href={href} download={download || undefined}>
      {children}
    </a>
  ) : (
    <Link className={classes} href={href}>
      {children}
    </Link>
  );
}

export function SeriesSwatch({ series }: { series: SeriesKey }) {
  return (
    <span
      aria-hidden
      className="inline-block size-2.5 shrink-0 rounded-full"
      style={{ background: `var(${SERIES[series].token})` }}
    />
  );
}

/** KPI tile: label, value and unit; an optional series swatch carries identity. */
export function Stat({
  label,
  value,
  unit,
  hint,
  series,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: React.ReactNode;
  series?: SeriesKey;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-muted-foreground">
        {series && <SeriesSwatch series={series} />}
        <span>{label}</span>
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-[1.9rem] font-semibold leading-none tracking-tight">
          {value}
        </span>
        {unit && value !== "Unavailable" && (
          <span className="text-muted-foreground">{unit}</span>
        )}
      </div>
      {hint && <div className="mt-2 text-[0.86rem] text-subtle">{hint}</div>}
    </div>
  );
}

export function KeyValues({
  items,
  className,
}: {
  items: [string, React.ReactNode][];
  className?: string;
}) {
  return (
    <dl
      className={cx(
        "grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4",
        className,
      )}
    >
      {items.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="border-b border-border py-2 text-muted-foreground">
            {label}
          </dt>
          <dd className="m-0 min-w-0 border-b border-border py-2 [overflow-wrap:anywhere]">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="grid justify-items-center gap-2 px-6 py-12 text-center">
      {icon && <div className="text-subtle">{icon}</div>}
      <h3 className="text-base font-semibold">{title}</h3>
      {children && (
        <div className="max-w-xl text-muted-foreground">{children}</div>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-status-critical/40 bg-status-critical/8 px-4 py-3 text-status-critical-ink"
    >
      <span className="flex items-center gap-2">
        <XCircle size={16} />
        {message}
      </span>
      {retry && (
        <Button onClick={retry}>
          <RefreshCw size={14} />
          Retry
        </Button>
      )}
    </div>
  );
}

export function Notice({
  tone = "info",
  children,
}: {
  tone?: Tone;
  children: React.ReactNode;
}) {
  return (
    <div
      role="status"
      className={cx("rounded-lg border px-4 py-3 text-[0.93rem]", TONES[tone])}
    >
      {children}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-lg bg-muted", className)} />;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string; disabled?: boolean }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="inline-flex flex-wrap gap-1 rounded-lg bg-muted p-1"
    >
      {options.map((option) => (
        <button
          key={option.value}
          role="tab"
          aria-selected={value === option.value}
          disabled={option.disabled}
          onClick={() => onChange(option.value)}
          className={cx(
            "rounded-md px-3 py-1.5 text-[0.9rem] font-medium transition disabled:opacity-40",
            value === option.value
              ? "bg-card text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  badges,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  badges?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[1.75rem] font-semibold leading-tight tracking-tight">
          {title}
        </h1>
        {description && (
          <p className="mt-1.5 max-w-3xl text-[1.02rem] text-muted-foreground">
            {description}
          </p>
        )}
        {badges && <div className="mt-3 flex flex-wrap gap-2">{badges}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

/** A backend-rendered ICPAC map (PNG) with loading and failure states. */
export function MapImage({
  src,
  alt,
  className,
}: {
  src: string;
  alt: string;
  className?: string;
}) {
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const [shown, setShown] = useState(src);
  if (shown !== src) {
    setShown(src);
    setState("loading");
  }
  return (
    <div
      className={cx("relative overflow-hidden rounded-lg bg-white", className)}
    >
      {state === "loading" && (
        <Skeleton className="absolute inset-0 rounded-none" />
      )}
      {state === "failed" ? (
        <div className="grid aspect-[5/4] place-items-center gap-2 text-muted-foreground">
          <ImageOff size={28} />
          <span>Map unavailable from the API</span>
        </div>
      ) : (
        // A backend-rendered product image, served as is (no optimisation pass).
        <img
          src={src}
          alt={alt}
          className="relative block h-auto w-full"
          onLoad={() => setState("ready")}
          onError={() => setState("failed")}
        />
      )}
    </div>
  );
}

export function Table({
  head,
  children,
  className,
}: {
  head: React.ReactNode[];
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-[0.93rem]">
        <thead>
          <tr>
            {head.map((cell, index) => (
              <th
                key={index}
                className="whitespace-nowrap border-b border-border px-3 py-2 text-left text-[0.8rem] font-medium text-muted-foreground first:pl-0"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&_td]:border-b [&_td]:border-border [&_td]:px-3 [&_td]:py-2.5 [&_td:first-child]:pl-0 [&_tr:last-child_td]:border-b-0">
          {children}
        </tbody>
      </table>
    </div>
  );
}
