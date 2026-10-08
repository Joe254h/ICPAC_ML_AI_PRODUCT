"use client";
/**
 * Workspace shell (Studio Admin layout): grouped, collapsible sidebar; breadcrumb
 * header with the model in use, date and theme; shared configuration context.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Boxes,
  Briefcase,
  ChevronDown,
  CloudRain,
  Database,
  FileText,
  Globe2,
  LayoutDashboard,
  Map as MapIcon,
  Moon,
  PanelLeft,
  ShieldCheck,
  Sun,
  X,
} from "lucide-react";
import { GROUPS, ROUTES, findRoute, href } from "@/features/routes";
import type { Route } from "@/features/routes";
import { useApi } from "@/services/hooks";
import type { Loaded } from "@/services/hooks";
import type { Config, Selection } from "@/types";
import type { CurrentModel } from "@/types/operational";
import { ModelStatus, cx } from "@/components/ui";

const ICONS: Record<string, React.ComponentType<{ size?: number }>> = {
  Overview: LayoutDashboard,
  Forecasts: CloudRain,
  Maps: MapIcon,
  Countries: Globe2,
  Verification: ShieldCheck,
  Models: Boxes,
  Data: Database,
  Bulletin: FileText,
  System: Activity,
  Workspace: Briefcase,
};

export const DEMO_SELECTION: Selection = {
  cycle: "2026-09-28",
  observation: "CHIRPS",
  model: "mock-v1",
  provider: "ECMWF S2S",
  country: "GHA",
  layer: "corrected",
};

type App = {
  config: Loaded<Config>;
  current: Loaded<CurrentModel>;
  selection: Selection;
  setSelection: React.Dispatch<React.SetStateAction<Selection>>;
  dark: boolean;
  refresh: () => void;
};

const AppContext = createContext<App | null>(null);

export function useApp(): App {
  const app = useContext(AppContext);
  if (!app) throw new Error("useApp outside the workspace shell");
  return app;
}

function groups() {
  return GROUPS.map((name) => ({
    name,
    items: ROUTES.filter((r) => r.group === name && r.nav !== false),
  }));
}

function NavLink({
  route,
  active,
  onNavigate,
  nested,
}: {
  route: Route;
  active: boolean;
  onNavigate: () => void;
  nested?: boolean;
}) {
  return (
    <Link
      href={href(route)}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cx(
        "flex h-8 items-center rounded-md px-2.5 transition",
        nested && "ml-4 border-l border-sidebar-border pl-3 rounded-l-none",
        active
          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
          : "text-sidebar-foreground/85 hover:bg-sidebar-accent/60",
      )}
    >
      <span className="truncate">{route.title}</span>
    </Link>
  );
}

function Sidebar({
  active,
  collapsed,
  mobileOpen,
  close,
}: {
  active?: Route;
  collapsed: boolean;
  mobileOpen: boolean;
  close: () => void;
}) {
  const { current } = useApp();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const rail = collapsed && !mobileOpen;
  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 lg:hidden"
          onClick={close}
          aria-hidden
        />
      )}
      <aside
        aria-label="Workspace navigation"
        className={cx(
          "fixed inset-y-0 left-0 z-50 flex flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width,transform] lg:sticky lg:top-0 lg:h-screen lg:translate-x-0",
          rail ? "w-[3.75rem]" : "w-64",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 items-center gap-2.5 border-b border-sidebar-border px-3.5">
          <Link
            href="/"
            onClick={close}
            className="flex min-w-0 items-center gap-2.5"
          >
            {/* The IGAD seal, as on the weekly bulletin maps. */}
            <img
              src="/igad-seal.png"
              alt="IGAD"
              width={32}
              height={32}
              className="size-8 shrink-0 rounded-full bg-white"
            />
            {!rail && (
              <span className="min-w-0 leading-tight">
                <strong className="block truncate text-[0.98rem] tracking-tight">
                  ICPAC Climate AI
                </strong>
                <small className="block truncate text-sidebar-muted">
                  Week-2 rainfall forecasting
                </small>
              </span>
            )}
          </Link>
          <button
            className="ml-auto grid size-8 place-items-center rounded-md hover:bg-sidebar-accent lg:hidden"
            onClick={close}
            aria-label="Close navigation"
          >
            <X size={16} />
          </button>
        </div>
        <nav
          aria-label="Main navigation"
          className="flex-1 overflow-y-auto px-2.5 py-3"
        >
          {groups().map(({ name, items }) => {
            const Icon = ICONS[name];
            const here = active?.group === name;
            if (rail)
              return (
                <Link
                  key={name}
                  href={href(items[0])}
                  title={name}
                  aria-label={name}
                  className={cx(
                    "mb-1 grid h-9 place-items-center rounded-md",
                    here
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "hover:bg-sidebar-accent/60",
                  )}
                >
                  <Icon size={17} />
                </Link>
              );
            if (items.length === 1 && items[0].title === name)
              return (
                <Link
                  key={name}
                  href={href(items[0])}
                  onClick={close}
                  aria-current={here ? "page" : undefined}
                  className={cx(
                    "mb-1 flex h-9 items-center gap-2.5 rounded-md px-2.5 font-medium",
                    here
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "hover:bg-sidebar-accent/60",
                  )}
                >
                  <Icon size={17} />
                  {name}
                </Link>
              );
            const expanded =
              open[name] ?? (here || name === "Forecasts" || name === "Maps");
            return (
              <div key={name} className="mb-1">
                <button
                  onClick={() => setOpen((o) => ({ ...o, [name]: !expanded }))}
                  aria-expanded={expanded}
                  className={cx(
                    "flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 font-medium hover:bg-sidebar-accent/60",
                    here && "text-sidebar-accent-foreground",
                  )}
                >
                  <Icon size={17} />
                  {name}
                  <ChevronDown
                    size={15}
                    className={cx(
                      "ml-auto text-sidebar-muted transition",
                      !expanded && "-rotate-90",
                    )}
                  />
                </button>
                {expanded && (
                  <div className="mt-0.5 mb-1.5 grid gap-0.5">
                    {items.map((route) => (
                      <NavLink
                        key={route.path}
                        route={route}
                        active={active?.path === route.path}
                        onNavigate={close}
                        nested
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
        {!rail && (
          <div className="border-t border-sidebar-border p-3">
            <div className="rounded-lg border border-sidebar-border bg-card px-3 py-2.5">
              <div className="text-[0.78rem] font-medium uppercase tracking-wide text-sidebar-muted">
                Model in use
              </div>
              {current.data ? (
                <>
                  <div
                    className="mt-1 truncate font-medium"
                    title={current.data.model.model_id}
                  >
                    {current.data.model.model_id}
                  </div>
                  <div className="mt-1.5">
                    <ModelStatus status={current.data.model.status} />
                  </div>
                </>
              ) : (
                <div className="mt-1 text-sidebar-muted">
                  {current.loading
                    ? "Loading…"
                    : "No operational model registered"}
                </div>
              )}
            </div>
          </div>
        )}
      </aside>
    </>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const route = findRoute(pathname ?? "/");
  const config = useApi<Config>("/config");
  const current = useApi<CurrentModel>("/models/current");
  const [selection, setSelection] = useState<Selection>(DEMO_SELECTION);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [today, setToday] = useState("");
  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
    setCollapsed(localStorage.getItem("icpac-sidebar") === "collapsed");
    setToday(
      new Date().toLocaleDateString("en-GB", {
        weekday: "short",
        day: "2-digit",
        month: "short",
        year: "numeric",
      }),
    );
  }, []);
  const { reload: reloadConfig } = config;
  const { reload: reloadCurrent } = current;
  const app = useMemo<App>(
    () => ({
      config,
      current,
      selection,
      setSelection,
      dark,
      refresh: () => {
        reloadConfig();
        reloadCurrent();
      },
    }),
    [config, current, selection, dark, reloadConfig, reloadCurrent],
  );
  const toggleTheme = () => {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("icpac-theme", next ? "dark" : "light");
    setDark(next);
  };
  return (
    <AppContext.Provider value={app}>
      <div className="flex min-h-screen">
        <Sidebar
          active={route}
          collapsed={collapsed}
          mobileOpen={mobileOpen}
          close={() => setMobileOpen(false)}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur md:px-6">
            <button
              className="grid size-9 place-items-center rounded-md border border-border bg-card hover:bg-muted"
              aria-label="Toggle navigation"
              onClick={() => {
                if (window.matchMedia("(min-width: 1024px)").matches) {
                  localStorage.setItem(
                    "icpac-sidebar",
                    collapsed ? "expanded" : "collapsed",
                  );
                  setCollapsed(!collapsed);
                } else setMobileOpen(true);
              }}
            >
              <PanelLeft size={16} />
            </button>
            <nav
              aria-label="Breadcrumb"
              className="flex min-w-0 items-center gap-1.5 text-muted-foreground"
            >
              {route && route.group !== route.title && (
                <>
                  <span className="hidden truncate sm:inline">
                    {route.group}
                  </span>
                  <span className="hidden sm:inline" aria-hidden>
                    /
                  </span>
                </>
              )}
              <span className="truncate font-medium text-foreground">
                {route?.title ?? "Not found"}
              </span>
            </nav>
            <div className="ml-auto flex items-center gap-2.5">
              {current.data && (
                <span className="hidden md:inline-flex">
                  <ModelStatus status={current.data.model.status} />
                </span>
              )}
              {config.error && (
                <span className="text-status-critical-ink" role="status">
                  API unavailable
                </span>
              )}
              <span className="hidden text-muted-foreground xl:inline">
                {today}
              </span>
              <button
                className="grid size-9 place-items-center rounded-md border border-border bg-card hover:bg-muted"
                aria-label="Toggle theme"
                onClick={toggleTheme}
              >
                {dark ? <Sun size={16} /> : <Moon size={16} />}
              </button>
            </div>
          </header>
          <main className="mx-auto w-full max-w-[1440px] flex-1 space-y-6 p-4 md:p-6">
            {children}
          </main>
          <footer className="flex flex-wrap justify-between gap-2 border-t border-border px-6 py-4 text-[0.86rem] text-subtle">
            <span>
              IGAD | ICPAC · Week-2 MBC + Atmos37 CatBoost forecasting
            </span>
            <span>Every number on screen comes from the forecast API.</span>
          </footer>
        </div>
      </div>
    </AppContext.Provider>
  );
}
