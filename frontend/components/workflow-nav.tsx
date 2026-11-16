"use client";
/**
 * The product bar of the forecast pages: which week is shown (and the ECMWF run it comes
 * from), and tabs to the same week's forecast, countries, maps, bulletin and verification.
 * A week chosen in the archive stays chosen from tab to tab (``?id=``).
 */
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { translate } from "@/lib/i18n";
import { useLanguage } from "@/lib/language";
import { day, weekPeriod } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { ForecastDetail } from "@/types/operational";

const TABS = [
  { title: "Forecast", path: "/forecasts", context: true },
  { title: "Countries", path: "/countries", context: true },
  { title: "Maps", path: "/maps/rainfall", context: true },
  { title: "Bulletin", path: "/bulletin", context: true },
  { title: "Verification", path: "/verification", context: false },
];

/** The pages the bar belongs to: the forecast products, not the tools. */
export function showsProductBar(pathname: string): boolean {
  return (
    pathname.startsWith("/forecasts") ||
    pathname.startsWith("/countries") ||
    pathname === "/maps/rainfall" ||
    pathname === "/bulletin" ||
    pathname === "/verification"
  );
}

function current(pathname: string, path: string): boolean {
  if (path === "/forecasts") return pathname.startsWith("/forecasts");
  if (path === "/countries") return pathname.startsWith("/countries");
  return pathname === path;
}

export default function WorkflowNav() {
  const pathname = usePathname() ?? "/";
  const search = useSearchParams();
  const requested = search.get("id");
  const selected =
    requested && /^w2-[a-zA-Z0-9_-]+$/.test(requested) ? requested : null;
  const forecast = useApi<ForecastDetail>(
    selected ? `/forecasts/${selected}` : "/forecasts/latest",
  );
  const id = selected ?? forecast.data?.forecast_id;
  const [language] = useLanguage();
  const t = (text: string) => translate(text, language);
  if (!showsProductBar(pathname)) return null;
  const detail = forecast.data;
  return (
    <div
      className="product-bar"
      lang={language}
      dir={language === "ar" ? "rtl" : "ltr"}
    >
      <div className="wrap product-bar-inner">
        <p className="product-week" aria-live="polite">
          {/* The forecast page's own title names the week; the bar names it elsewhere. */}
          {pathname === "/forecasts" ? null : detail ? (
            <>
              <b>{weekPeriod(detail.valid_start, detail.valid_end)}</b>
              <span>
                ECMWF run {day(detail.initialization)}
                {selected && (
                  <>
                    {" · "}
                    <Link href={pathname}>{t("Latest forecast")}</Link>
                  </>
                )}
              </span>
            </>
          ) : (
            <span>{forecast.loading ? "…" : t("Latest forecast")}</span>
          )}
        </p>
        <nav aria-label="Forecast workflow">
          {TABS.map((tab) => (
            <Link
              key={tab.path}
              href={
                tab.path +
                (tab.context && selected && id
                  ? `?id=${encodeURIComponent(id)}`
                  : "")
              }
              aria-current={current(pathname, tab.path) ? "page" : undefined}
            >
              {t(tab.title)}
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}
