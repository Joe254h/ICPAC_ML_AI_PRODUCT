"use client";
/**
 * Site shell after www.icpac.net: the IGAD seal and ICPAC name over a satellite image
 * under a green veil, utility links (status, search, run forecast), the uppercase menu
 * with drop-down panels, the page banner and the footer.
 */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ChevronDown, Menu as MenuIcon, Search, X } from "lucide-react";
import { BannerSlot } from "@/components/banner";
import { cx } from "@/components/ui";
import { MENUS, ROUTES, findRoute, href, menuRoutes } from "@/features/routes";
import type { Menu, Route } from "@/features/routes";
import { useApi } from "@/services/hooks";
import type { Loaded } from "@/services/hooks";
import type { Config } from "@/types";
import type { CurrentModel, Health } from "@/types/operational";

type App = {
  config: Loaded<Config>;
  current: Loaded<CurrentModel>;
  health: Loaded<Health>;
  refresh: () => void;
};

const AppContext = createContext<App | null>(null);

export function useApp(): App {
  const app = useContext(AppContext);
  if (!app) throw new Error("useApp outside the site shell");
  return app;
}

const ORGANISATION = [
  ["About ICPAC", "https://www.icpac.net/about-us/"],
  ["WMO Regional Climate Centre", "https://www.icpac.net/rcc/"],
  ["ICPAC weekly forecast", "https://www.icpac.net/weekly-forecast/"],
  ["Contact us", "https://www.icpac.net/contact-us/"],
] as const;

function MenuEntry({
  menu,
  active,
  open,
  setOpen,
}: {
  menu: Menu;
  active?: Route;
  open: boolean;
  setOpen: (menu: Menu | null) => void;
}) {
  const routes = menuRoutes(menu);
  const current = active?.menu === menu;
  if (routes.length === 1)
    return (
      <li>
        <Link
          className="item"
          href={href(routes[0])}
          aria-current={current ? "page" : undefined}
        >
          {menu}
        </Link>
      </li>
    );
  return (
    <li
      className={cx(open && "open")}
      onMouseEnter={() => setOpen(menu)}
      onMouseLeave={() => setOpen(null)}
    >
      <button
        type="button"
        className="item"
        aria-expanded={open}
        aria-current={current ? "page" : undefined}
        onClick={() => setOpen(open ? null : menu)}
      >
        {menu} <ChevronDown size={16} aria-hidden />
      </button>
      <div className={cx("dropdown", menu === "Countries" && "wide")}>
        {routes.map((route) => (
          <Link
            key={route.path}
            href={href(route)}
            aria-current={active?.path === route.path ? "page" : undefined}
            onClick={() => setOpen(null)}
          >
            {route.title}
            {route.soon && <span className="soon">Coming later</span>}
          </Link>
        ))}
      </div>
    </li>
  );
}

function SearchDialog({ close }: { close: () => void }) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const results = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return ROUTES.filter(
      (route) =>
        route.nav !== false &&
        (!needle ||
          route.title.toLowerCase().includes(needle) ||
          route.menu.toLowerCase().includes(needle)),
    ).slice(0, 12);
  }, [text]);
  useEffect(() => input.current?.focus(), []);
  useEffect(() => setIndex(0), [text]);
  const go = (route?: Route) => {
    if (!route) return;
    router.push(href(route));
    close();
  };
  return (
    <div
      className="search-backdrop"
      role="dialog"
      aria-modal
      aria-label="Search the site"
      onClick={close}
    >
      <div className="search-panel" onClick={(e) => e.stopPropagation()}>
        <input
          ref={input}
          value={text}
          placeholder="Search pages: forecast, Kenya, CHIRPS, bulletin…"
          aria-label="Search pages"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") close();
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setIndex((i) => Math.min(i + 1, results.length - 1));
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              setIndex((i) => Math.max(i - 1, 0));
            }
            if (e.key === "Enter") go(results[index]);
          }}
        />
        <ul>
          {results.map((route, i) => (
            <li key={route.path}>
              <Link
                href={href(route)}
                className={cx(i === index && "active")}
                onClick={close}
              >
                <span>{route.title}</span>
                <small>{route.menu}</small>
              </Link>
            </li>
          ))}
          {!results.length && (
            <li style={{ padding: 14, color: "var(--muted)" }}>
              No page matches “{text}”.
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}

function StatusDot({ health }: { health: Loaded<Health> }) {
  const colour = health.error
    ? "#f87171"
    : health.data?.status === "Healthy"
      ? "#4ade80"
      : health.data
        ? "#fbbf24"
        : "rgba(255,255,255,.6)";
  return (
    <span
      aria-hidden
      style={{
        width: 9,
        height: 9,
        borderRadius: "50%",
        background: colour,
        boxShadow: "0 0 0 3px rgba(255,255,255,.18)",
      }}
    />
  );
}

/**
 * One notice for the whole site when the forecast service is not ready: starting up
 * (it scales to zero when idle), unreachable, or an older release than this site.
 */
function ServiceNotice({ health }: { health: Loaded<Health> }) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!health.loading) return setSlow(false);
    const timer = window.setTimeout(() => setSlow(true), 4000);
    return () => window.clearTimeout(timer);
  }, [health.loading]);
  let text: React.ReactNode = null;
  if (health.loading && slow)
    text = (
      <>
        <strong>Waking up the forecast service.</strong> It sleeps when nobody
        uses it; the first page takes up to a minute.
      </>
    );
  else if (health.error && !health.loading)
    text = (
      <>
        <strong>The forecast service is not answering.</strong> Pages will load
        once it is back.{" "}
        <button type="button" onClick={health.reload}>
          Try again
        </button>
      </>
    );
  else if (health.data && health.data.mode !== "operational")
    text = (
      <>
        <strong>The forecast service is being updated.</strong> It still runs an
        earlier release, so some pages cannot load yet.
      </>
    );
  if (!text) return null;
  return (
    <div className="service-notice" role="status">
      <div className="wrap">{text}</div>
    </div>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const active = findRoute(pathname ?? "/");
  const home = active?.page === "home";
  const config = useApi<Config>("/config");
  const current = useApi<CurrentModel>("/models/current");
  const health = useApi<Health>("/health");
  const [open, setOpen] = useState<Menu | null>(null);
  const [mobile, setMobile] = useState(false);
  const [search, setSearch] = useState(false);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const nav = useRef<HTMLElement>(null);

  const refresh = useCallback(() => {
    config.reload();
    current.reload();
    health.reload();
  }, [config, current, health]);
  const app = useMemo(
    () => ({ config, current, health, refresh }),
    [config, current, health, refresh],
  );

  useEffect(() => {
    setOpen(null);
    setMobile(false);
  }, [pathname]);
  useEffect(() => {
    const keys = (e: KeyboardEvent) => {
      const typing =
        e.target instanceof HTMLElement &&
        ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName);
      if (e.key === "/" && !typing) {
        e.preventDefault();
        setSearch(true);
      }
      if (e.key === "Escape") setOpen(null);
    };
    const outside = (e: MouseEvent) => {
      if (nav.current && !nav.current.contains(e.target as Node)) setOpen(null);
    };
    window.addEventListener("keydown", keys);
    window.addEventListener("click", outside);
    return () => {
      window.removeEventListener("keydown", keys);
      window.removeEventListener("click", outside);
    };
  }, []);

  return (
    <AppContext.Provider value={app}>
      <a href="#content" className="sr-only focus:not-sr-only">
        Skip to content
      </a>
      <header className={cx("site-top", home && "home")}>
        <div className="wrap brandbar">
          <Link
            className="brand"
            href="/"
            aria-label="ICPAC Week-2 forecasts, home"
          >
            <img src="/igad-seal-white.png" alt="" width={74} height={74} />
            <div>
              <b>ICPAC</b>
              <small>IGAD Climate Prediction and Applications Centre</small>
            </div>
          </Link>
          <div className="utility">
            <Link className="hide-sm" href="/system">
              Status <StatusDot health={health} />
            </Link>
            <button type="button" onClick={() => setSearch(true)}>
              <span className="label">Search</span>
              <Search size={18} aria-hidden />
            </button>
            <Link className="pill-white hide-sm" href="/data/runs">
              Run forecast
            </Link>
            <button
              type="button"
              className="menu-toggle"
              aria-label={mobile ? "Close menu" : "Open menu"}
              aria-expanded={mobile}
              onClick={() => setMobile((m) => !m)}
            >
              {mobile ? <X size={26} /> : <MenuIcon size={26} />}
            </button>
          </div>
        </div>
        <nav
          ref={nav}
          className={cx("mainnav", mobile && "mobile-open")}
          aria-label="Main"
        >
          <ul>
            {MENUS.map((menu) => (
              <MenuEntry
                key={menu}
                menu={menu}
                active={active}
                open={open === menu}
                setOpen={setOpen}
              />
            ))}
          </ul>
        </nav>
        {!home && (
          <div className="banner">
            <div className="wrap">
              <div ref={setSlot} className="banner-slot" />
              <div className="banner-fallback">
                <h1>{active?.title ?? "Page not found"}</h1>
              </div>
            </div>
          </div>
        )}
      </header>
      <ServiceNotice health={health} />
      <BannerSlot.Provider value={slot}>
        <main id="content">{children}</main>
      </BannerSlot.Provider>
      <footer className="site-footer">
        <div className="wrap cols">
          <div className="about">
            <Link className="brand" href="/">
              <img src="/igad-seal-white.png" alt="" width={56} height={56} />
              <div>
                <b>ICPAC</b>
                <small>IGAD Climate Prediction and Applications Centre</small>
              </div>
            </Link>
          </div>
          <div>
            <h4>Forecasts</h4>
            <Link href="/forecasts">Latest forecast</Link>
            <Link href="/maps/rainfall">Rainfall maps</Link>
            <Link href="/forecasts/archive">Forecast archive</Link>
            <Link href="/verification">Verification</Link>
            <Link href="/copilot">Forecaster Copilot</Link>
          </div>
          <div>
            <h4>Products and Data</h4>
            <Link href="/bulletin">Weekly bulletin</Link>
            <Link href="/data">Data sources</Link>
            <Link href="/data/ecmwf">ECMWF ensemble</Link>
            <Link href="/monitoring">Rainfall monitoring</Link>
            <Link href="/models">Model registry</Link>
          </div>
          <div>
            <h4>Organisation</h4>
            {ORGANISATION.map(([label, url]) => (
              <a key={url} href={url} target="_blank" rel="noreferrer">
                {label}
              </a>
            ))}
          </div>
        </div>
        <div className="wrap legal">
          <span>© ICPAC {new Date().getUTCFullYear()}</span>
          <span>
            Forecast data: ECMWF Open Data (CC BY 4.0) · Observations: CHIRPS,
            TAMSAT
          </span>
        </div>
      </footer>
      {search && <SearchDialog close={() => setSearch(false)} />}
    </AppContext.Provider>
  );
}
