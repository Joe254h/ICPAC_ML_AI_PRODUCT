"use client";
/**
 * Site shell: one white header with the IGAD seal and the product's name, the menus (the
 * staff's Operations menu set apart), search, service status and staff access; the page
 * header; and a short footer with ICPAC's links and the data credits.
 */
import Link from "next/link";
import StaffAccess from "@/components/bulletin-access";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ChevronDown,
  ExternalLink,
  Languages,
  Menu as MenuIcon,
  Moon,
  Search,
  Sun,
  X,
} from "lucide-react";
import { BannerSlot } from "@/components/banner";
import { cx } from "@/components/ui";
import {
  MENUS,
  ROUTES,
  STAFF_MENU,
  findRoute,
  href,
  menuGroups,
  menuRoutes,
} from "@/features/routes";
import type { Menu, Route } from "@/features/routes";
import { SITE_LANGUAGES, translate } from "@/lib/i18n";
import { useLanguage } from "@/lib/language";
import { useTheme } from "@/lib/theme";
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

type MenuState = { menu: Menu | null; pinned: boolean };

/** A header menu: hovering shows its pages, a click keeps them open (a second click, Escape
 * or a click elsewhere closes them). */
function MenuEntry({
  menu,
  active,
  state,
  setState,
  t,
}: {
  menu: Menu;
  active?: Route;
  state: MenuState;
  setState: (state: MenuState) => void;
  t: (text: string) => string;
}) {
  const open = state.menu === menu;
  const groups = menuGroups(menu);
  const routes = groups.flatMap((group) => group.routes);
  const current = active?.menu === menu;
  const staff = menu === STAFF_MENU;
  if (routes.length === 1)
    return (
      <li>
        <Link
          className="item"
          href={href(routes[0])}
          aria-current={current ? "page" : undefined}
        >
          {t(menu)}
        </Link>
      </li>
    );
  return (
    <li
      className={cx(open && "open", staff && "staff")}
      onMouseEnter={() => {
        if (!state.pinned || !open) setState({ menu, pinned: false });
      }}
      onMouseLeave={() => {
        if (!state.pinned) setState({ menu: null, pinned: false });
      }}
    >
      <button
        type="button"
        className="item"
        aria-expanded={open}
        aria-haspopup="true"
        aria-current={current ? "page" : undefined}
        onClick={() =>
          setState(
            open && state.pinned
              ? { menu: null, pinned: false }
              : { menu, pinned: true },
          )
        }
      >
        {t(menu)} <ChevronDown size={16} aria-hidden className="chevron" />
      </button>
      <div className={cx("dropdown", groups.length > 1 && "grouped")}>
        {groups.map((group) => (
          <div
            key={group.label ?? "main"}
            className={cx(
              "dropdown-group",
              group.routes.length > 6 && "columns",
            )}
          >
            {group.label && <p className="dropdown-label">{t(group.label)}</p>}
            {group.routes.map((route) => (
              <Link
                key={route.path}
                href={href(route)}
                aria-current={active?.path === route.path ? "page" : undefined}
                onClick={() => setState({ menu: null, pinned: false })}
              >
                {t(route.title)}
                {route.soon && (
                  <span className="soon">{t("Coming later")}</span>
                )}
              </Link>
            ))}
          </div>
        ))}
      </div>
    </li>
  );
}

function SearchDialog({
  close,
  t,
}: {
  close: () => void;
  t: (text: string) => string;
}) {
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
          [route.title, route.menu, t(route.title), t(route.menu)].some(
            (name) => name.toLowerCase().includes(needle),
          )),
    ).slice(0, 12);
  }, [text, t]);
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
                <span>{t(route.title)}</span>
                <small>{t(route.menu)}</small>
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

/** The site's language: menus, page names and the footer, and the language the Copilot
 * answers in and the bulletin is offered in. In the bar it shows a short code; the list
 * itself gives each language's own name. */
function LanguagePicker({
  language,
  choose,
  compact,
}: {
  language: string;
  choose: (code: string) => void;
  compact?: boolean;
}) {
  const known = language in SITE_LANGUAGES;
  return (
    <label
      className={cx("language-picker", compact ? "in-bar" : "in-menu")}
      title={translate("Site language", language)}
    >
      <Languages size={16} aria-hidden />
      {compact && (
        <span className="code" aria-hidden>
          {language.toUpperCase()}
        </span>
      )}
      {/* Uncontrolled, so a re-render while the choice is being made cannot put the
          earlier language back; a change made elsewhere remounts it. */}
      <select
        key={language}
        aria-label="Site language"
        defaultValue={language}
        onChange={(e) => choose(e.target.value)}
      >
        {Object.entries(SITE_LANGUAGES).map(([code, name]) => (
          <option key={code} value={code} lang={code}>
            {name}
          </option>
        ))}
        {/* A language chosen in the Copilot that the menus do not come in yet. */}
        {!known && <option value={language}>{language}</option>}
      </select>
    </label>
  );
}

function statusOf(health: Loaded<Health>) {
  if (health.error) return { tone: "bad", text: "not answering" };
  if (health.data?.status === "Healthy") return { tone: "ok", text: "healthy" };
  if (health.data) return { tone: "warn", text: "needs attention" };
  return { tone: "unknown", text: "checking" };
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
  const status = statusOf(health);
  const [theme, setTheme] = useTheme();
  const [language, chooseLanguage] = useLanguage();
  const t = useCallback(
    (text: string) => translate(text, language),
    [language],
  );
  const [menuState, setMenuState] = useState<MenuState>({
    menu: null,
    pinned: false,
  });
  const [mobile, setMobile] = useState(false);
  const [search, setSearch] = useState(false);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const [accessVersion, setAccessVersion] = useState(0);
  const nav = useRef<HTMLElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  // When the menus do not fit the bar (a long language, the staff's buttons), the bar
  // first tightens (closer menus, staff access as an icon) and then folds the menus into
  // the menu button, as it does below 1240 px. ``fitsFrom[step]`` is the bar width the
  // step before needs.
  const [fit, setFit] = useState(0);
  const fitsFrom = useRef([0, 0, 0]);
  useLayoutEffect(() => setFit(0), [language]);
  useLayoutEffect(() => {
    const head = bar.current;
    const menus = nav.current;
    const list = menus?.querySelector("ul");
    if (!head || !menus || !list) return;
    const check = () => {
      if (fit > 0 && head.clientWidth >= fitsFrom.current[fit]) {
        setFit(fit - 1);
        return;
      }
      if (fit === 2) return;
      if (getComputedStyle(menus).position === "absolute") return; // folded by width
      const over = list.scrollWidth - menus.clientWidth;
      if (over > 0) {
        fitsFrom.current[fit + 1] = head.clientWidth + over;
        setFit(fit + 1);
      }
    };
    check();
    const observer = new ResizeObserver(check);
    observer.observe(head);
    observer.observe(list);
    const utility = head.querySelector(".utility");
    if (utility) observer.observe(utility);
    return () => observer.disconnect();
  }, [fit, language]);
  useEffect(() => {
    const changed = () => setAccessVersion((v) => v + 1);
    window.addEventListener("staff-access", changed);
    return () => window.removeEventListener("staff-access", changed);
  }, []);

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
    setMenuState({ menu: null, pinned: false });
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
      if (e.key === "Escape") setMenuState({ menu: null, pinned: false });
    };
    const outside = (e: MouseEvent) => {
      if (nav.current && !nav.current.contains(e.target as Node))
        setMenuState({ menu: null, pinned: false });
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
      <header
        className={cx(
          "site-top",
          home && "home",
          fit > 0 && "tight",
          fit > 1 && "crowded",
        )}
      >
        <div ref={bar} className="wrap headbar">
          <Link
            className="brand"
            href="/"
            aria-label="ICPAC Week-2 Rainfall Outlook, home"
          >
            <img src="/igad-seal.png" alt="" width={40} height={40} />
            <div className="brand-name">
              <b>ICPAC</b>
              <small>{t("Week-2 Rainfall Outlook")}</small>
            </div>
          </Link>
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
                  state={menuState}
                  setState={setMenuState}
                  t={t}
                />
              ))}
            </ul>
            <LanguagePicker language={language} choose={chooseLanguage} />
          </nav>
          <div className="utility">
            <LanguagePicker
              language={language}
              choose={chooseLanguage}
              compact
            />
            <button
              type="button"
              className="icon-button"
              onClick={() => setSearch(true)}
              aria-label="Search"
              title={`${t("Search")} (/)`}
            >
              <Search size={18} aria-hidden />
            </button>
            <button
              type="button"
              className="icon-button"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={
                theme === "dark"
                  ? "Switch to light mode"
                  : "Switch to dark mode"
              }
              title={theme === "dark" ? "Light mode" : "Dark mode"}
            >
              {theme === "dark" ? (
                <Sun size={18} aria-hidden />
              ) : (
                <Moon size={18} aria-hidden />
              )}
            </button>
            <Link
              href="/system"
              className="icon-button"
              title={`Service ${status.text}`}
              aria-label={`Service status: ${status.text}`}
            >
              <span aria-hidden className={cx("status-dot", status.tone)} />
            </Link>
            {health.data && health.data.access_mode !== "public" && (
              <StaffAccess />
            )}
            <button
              type="button"
              className="menu-toggle"
              aria-label={mobile ? "Close menu" : "Open menu"}
              aria-expanded={mobile}
              onClick={() => setMobile((m) => !m)}
            >
              {mobile ? <X size={22} /> : <MenuIcon size={22} />}
            </button>
          </div>
        </div>
        {!home && (
          <div className="banner">
            <div className="wrap">
              <div ref={setSlot} className="banner-slot" />
              <div className="banner-fallback">
                <h1>{t(active?.title ?? "Page not found")}</h1>
              </div>
            </div>
          </div>
        )}
      </header>
      <ServiceNotice health={health} />
      <BannerSlot.Provider value={slot}>
        <main id="content" key={accessVersion}>
          {children}
        </main>
      </BannerSlot.Provider>
      <footer className="site-footer">
        <div className="wrap footer-main">
          <Link className="brand" href="/">
            <img src="/igad-seal-white.png" alt="" width={42} height={42} />
            <div className="brand-name">
              <b>ICPAC</b>
              <small>
                {t("IGAD Climate Prediction and Applications Centre")}
              </small>
            </div>
          </Link>
          <nav className="footer-links" aria-label="ICPAC">
            <Link href="/about">{t("About this service")}</Link>
            {ORGANISATION.map(([label, url]) => (
              <a key={url} href={url} target="_blank" rel="noreferrer">
                {label} <ExternalLink size={12} aria-hidden />
              </a>
            ))}
          </nav>
        </div>
        <nav className="wrap sitemap" aria-label="Site map">
          {MENUS.map((menu) => (
            <div key={menu}>
              <h2>{t(menu)}</h2>
              <ul>
                {menuRoutes(menu).map((route) => (
                  <li key={route.path}>
                    <Link href={href(route)}>{t(route.title)}</Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="wrap legal">
          <span>
            © ICPAC {new Date().getUTCFullYear()} ·{" "}
            {t("WMO Regional Climate Centre for Eastern Africa")}
          </span>
        </div>
      </footer>
      {search && <SearchDialog close={() => setSearch(false)} t={t} />}
    </AppContext.Provider>
  );
}
