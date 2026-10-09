"use client";
/**
 * The page banner sits inside the site header, over the satellite image. Pages render
 * <PageBanner> into the header's slot (a portal), so the header never re-renders with them.
 */
import Link from "next/link";
import { createContext, useContext } from "react";
import { createPortal } from "react-dom";

export const BannerSlot = createContext<HTMLElement | null>(null);

export type Crumb = { label: string; href?: string };

export type Banner = {
  title: string;
  subtitle?: React.ReactNode;
  crumbs?: Crumb[];
  actions?: React.ReactNode;
  /** Short facts shown as pills (e.g. the forecast window). */
  facts?: React.ReactNode[];
};

export function Crumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <Link href="/">Home</Link>
      {crumbs.map((crumb) => (
        <span key={crumb.label}>
          {" / "}
          {crumb.href ? (
            <Link href={crumb.href}>{crumb.label}</Link>
          ) : (
            crumb.label
          )}
        </span>
      ))}
    </nav>
  );
}

export function PageBanner({
  title,
  subtitle,
  crumbs,
  actions,
  facts,
}: Banner) {
  const slot = useContext(BannerSlot);
  if (!slot) return null;
  return createPortal(
    <>
      {crumbs && <Crumbs crumbs={crumbs} />}
      <h1>{title}</h1>
      {subtitle && <p>{subtitle}</p>}
      {facts && facts.length > 0 && (
        <div className="hero-facts">
          {facts.map((fact, index) => (
            <span key={index}>{fact}</span>
          ))}
        </div>
      )}
      {actions && <div className="actions">{actions}</div>}
    </>,
    slot,
  );
}

/** The home page's large hero, in the same slot. */
export function HeroBanner({ children }: { children: React.ReactNode }) {
  const slot = useContext(BannerSlot);
  if (!slot) return null;
  return createPortal(children, slot);
}
