"use client";
/** The member states as cards, wettest first, each with a bar in its rainfall class. */
import Link from "next/link";
import { RAIN_CLASSES } from "@/components/forecast-map";
import { countrySlug } from "@/features/routes";
import { primaryOf } from "@/features/operational/shared";
import { num } from "@/lib/format";
import type { ForecastDetail } from "@/types/operational";

const CLASS_EDGES = [1, 10, 30, 50, 100, 200];

/** The bulletin colour class of an amount (mm). */
export function rainColour(mm: number): string {
  const index = CLASS_EDGES.filter((edge) => mm >= edge).length;
  return RAIN_CLASSES[index][0];
}

export default function CountryCards({ detail }: { detail: ForecastDetail }) {
  const layer = primaryOf(detail);
  const rows = detail.countries
    .filter((r) => r[layer])
    .sort((a, b) => (b[layer]?.mean_mm ?? 0) - (a[layer]?.mean_mm ?? 0));
  const top = Math.max(...rows.map((r) => r[layer]?.mean_mm ?? 0), 1);
  return (
    <div className="country-grid">
      {rows.map((row) => {
        const stats = row[layer]!;
        return (
          <Link
            key={row.country}
            href={`/countries/${countrySlug(row.country)}`}
            className="country-card"
          >
            <span className="country-name">{row.country}</span>
            <span className="country-value">
              {num(stats.mean_mm)}
              <small>mm</small>
            </span>
            <span className="country-bar" aria-hidden>
              <span
                style={{
                  width: `${Math.max(4, (100 * stats.mean_mm) / top)}%`,
                  background: rainColour(stats.mean_mm),
                }}
              />
            </span>
            <span className="country-hint">
              Up to {num(stats.max_mm, 0)} mm locally
            </span>
          </Link>
        );
      })}
    </div>
  );
}
