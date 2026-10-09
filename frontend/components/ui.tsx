"use client";
/** Building blocks of the ICPAC design system (styles: app/globals.css). */
import Link from "next/link";
import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Info,
  RotateCw,
  XCircle,
} from "lucide-react";
export { PageBanner } from "@/components/banner";

export function cx(...names: (string | false | null | undefined)[]) {
  return names.filter(Boolean).join(" ");
}

export type Tone = "ok" | "progress" | "planned" | "bad" | "info";

export function Status({
  tone,
  children,
}: {
  tone: Tone;
  children: React.ReactNode;
}) {
  return (
    <span className={cx("status", tone)}>
      <span className="dot" aria-hidden />
      {children}
    </span>
  );
}

/** Model registry status as a pill. */
export function ModelStatus({ status }: { status?: string }) {
  const tone: Tone =
    status === "production"
      ? "ok"
      : status === "candidate"
        ? "info"
        : status === "retired"
          ? "planned"
          : "progress";
  return <Status tone={tone}>{status ?? "unknown"}</Status>;
}

type ButtonVariant = "amber" | "green" | "outline" | "white" | "ghost-light";

export function Button({
  variant = "green",
  size,
  className,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: "sm";
}) {
  return (
    <button
      type="button"
      className={cx("btn", `btn-${variant}`, size && "btn-sm", className)}
      {...props}
    >
      {children}
    </button>
  );
}

export function LinkButton({
  href,
  variant = "green",
  size,
  external,
  children,
  className,
}: {
  href: string;
  variant?: ButtonVariant;
  size?: "sm";
  external?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const classes = cx("btn", `btn-${variant}`, size && "btn-sm", className);
  if (external || href.startsWith("/api/") || href.startsWith("http"))
    return (
      <a
        className={classes}
        href={href}
        {...(href.startsWith("http")
          ? { target: "_blank", rel: "noreferrer" }
          : {})}
      >
        {children}
      </a>
    );
  return (
    <Link className={classes} href={href}>
      {children}
    </Link>
  );
}

export function Card({
  title,
  subtitle,
  eyebrow,
  action,
  children,
  className,
  flush,
  id,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  eyebrow?: string;
  action?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  flush?: boolean;
  id?: string;
}) {
  return (
    <section id={id} className={cx("card", flush && "flush", className)}>
      {(title || action) && (
        <div className="card-head">
          <div>
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  unit,
  hint,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  hint?: React.ReactNode;
  tone?: "amber";
}) {
  return (
    <div className={cx("stat", tone)}>
      <div className="label">{label}</div>
      <div className="value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function KeyValues({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([label, value]) => (
        <div key={label} style={{ display: "contents" }}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Notice({
  tone = "amber",
  title,
  children,
}: {
  tone?: "amber" | "green" | "red";
  title?: string;
  children?: React.ReactNode;
}) {
  const Icon =
    tone === "green" ? CheckCircle2 : tone === "red" ? XCircle : Info;
  return (
    <div className={cx("notice", tone !== "amber" && tone)} role="note">
      <Icon size={20} aria-hidden />
      <div>
        {title && <strong>{title} </strong>}
        {children}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="card" style={{ textAlign: "center", padding: "56px 28px" }}>
      <Clock3
        size={40}
        style={{ color: "var(--amber)", margin: "0 auto 14px" }}
        aria-hidden
      />
      <h2 style={{ fontSize: 26 }}>{title}</h2>
      {children && (
        <div style={{ maxWidth: 640, margin: "12px auto 0" }}>{children}</div>
      )}
      {action && <div style={{ marginTop: 22 }}>{action}</div>}
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
    <div className="notice red" role="alert">
      <AlertTriangle size={20} aria-hidden />
      <div style={{ flex: 1 }}>
        <strong>The service could not load this information.</strong> {message}
      </div>
      {retry && (
        <Button variant="outline" size="sm" onClick={retry}>
          <RotateCw size={15} aria-hidden /> Retry
        </Button>
      )}
    </div>
  );
}

export function Skeleton({
  height = 320,
  className,
}: {
  height?: number;
  className?: string;
}) {
  return <div className={cx("skeleton", className)} style={{ height }} />;
}

export type TabOption<T extends string> = {
  value: T;
  label: React.ReactNode;
  disabled?: boolean;
  title?: string;
};

export function Tabs<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: TabOption<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="tabs" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          disabled={option.disabled}
          title={option.title}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** A server-rendered map image with a placeholder while it renders. */
export function MapFigure({
  src,
  alt,
  caption,
}: {
  src: string;
  alt: string;
  caption?: React.ReactNode;
}) {
  // The outcome is kept per source, so a new map starts loading without an effect that
  // could overwrite the load event of an image already in the browser cache.
  const [outcome, setOutcome] = useState<{ src: string; ok: boolean } | null>(
    null,
  );
  const state =
    outcome?.src !== src ? "loading" : outcome.ok ? "ready" : "failed";
  const settle = (ok: boolean) => setOutcome({ src, ok });
  return (
    <figure className="figure">
      {state === "loading" && <Skeleton height={420} />}
      {state === "failed" ? (
        <Notice tone="red">This map could not be rendered.</Notice>
      ) : (
        <img
          src={src}
          alt={alt}
          ref={(img) => {
            if (img?.complete && img.naturalWidth > 0 && state === "loading")
              settle(true);
          }}
          onLoad={() => settle(true)}
          onError={() => settle(false)}
          style={state === "ready" ? undefined : { display: "none" }}
        />
      )}
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

/** A product that is not available yet, with what it needs. */
export function InProgress({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="pending-card">
      <Status tone="progress">In progress</Status>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
