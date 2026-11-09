"use client";
/** Inset workspace navigation adapted from shadcn/ui's free dashboard pattern. */
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { ArrowUpRight, CircleHelp, Workflow } from "lucide-react";
import { translate } from "@/lib/i18n";
import { useLanguage } from "@/lib/language";
import { validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { ForecastDetail } from "@/types/operational";

const STEPS = [
  { title: "Data sources", path: "/data", number: "01" },
  { title: "Forecasts", path: "/forecasts", number: "02", context: true },
  { title: "Verification", path: "/verification", number: "03" },
  {
    title: "Rainfall maps",
    path: "/maps/rainfall",
    number: "04",
    context: true,
  },
  {
    title: "All member states",
    path: "/countries",
    number: "05",
    context: true,
  },
  { title: "Weekly bulletin", path: "/bulletin", number: "06", context: true },
];

export default function WorkflowNav() {
  const pathname = usePathname();
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
  return (
    <aside
      className="workspace-rail"
      lang={language}
      dir={language === "ar" ? "rtl" : "ltr"}
    >
      <div className="workspace-identity">
        <span className="workspace-symbol">
          <Workflow size={20} aria-hidden />
        </span>
        <div>
          <b>ICPAC</b>
          <small>{t("Week-2 Rainfall Outlook")}</small>
        </div>
      </div>
      <nav aria-label="Forecast workflow">
        <p className="workspace-label">{t("Forecasts")}</p>
        <ol>
          {STEPS.map((step) => (
            <li key={step.path}>
              <Link
                href={
                  step.path +
                  (step.context && id ? `?id=${encodeURIComponent(id)}` : "")
                }
                aria-current={pathname === step.path ? "page" : undefined}
              >
                <span className="workspace-number" aria-hidden>
                  {step.number}
                </span>
                {t(step.title)}
              </Link>
            </li>
          ))}
        </ol>
      </nav>
      <nav className="workspace-tools" aria-label="Workspace tools">
        <p className="workspace-label">{t("Operations")}</p>
        {[
          ["Automation", "/automations"],
          ["Run the weekly cycle", "/data/runs"],
          ["Model registry", "/models"],
          ["Forecaster Copilot", "/copilot"],
          ["System status", "/system"],
        ].map(([label, path]) => (
          <Link
            key={path}
            href={path}
            aria-current={pathname === path ? "page" : undefined}
          >
            {t(label)}
            <ArrowUpRight size={14} aria-hidden />
          </Link>
        ))}
      </nav>
      <div className="workspace-context" aria-live="polite">
        <span className="workspace-label">{t("Week-2 Rainfall Outlook")}</span>
        {forecast.data ? (
          <>
            <b>
              {validDays(forecast.data.valid_start, forecast.data.valid_end)}
            </b>
            <span>
              {forecast.data.layers
                ? forecast.data.layers.includes("hybrid")
                  ? "Raw ECMWF · MBC · AI/ML"
                  : "Raw ECMWF · MBC; AI/ML unavailable"
                : "See forecast for product availability"}
            </span>
          </>
        ) : (
          <span>
            {forecast.loading ? "…" : t("Latest forecast") + " · unavailable"}
          </span>
        )}
      </div>
      <Link href="/about" className="workspace-help">
        <CircleHelp size={16} aria-hidden />
        Service guide
      </Link>
    </aside>
  );
}
