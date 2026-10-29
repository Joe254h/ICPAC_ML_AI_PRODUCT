/**
 * Every page of the site: path, the menu it sits in and the view that renders it.
 * The server page validates URLs against this table; the header menus are built from it.
 */
export type PageKey =
  | "home"
  | "forecast"
  | "archive"
  | "layer"
  | "maps"
  | "country"
  | "countries"
  | "verification"
  | "evidence"
  | "monitoring"
  | "models"
  | "data"
  | "source"
  | "operations"
  | "automations"
  | "bulletin"
  | "drafts"
  | "decision"
  | "copilot"
  | "system"
  | "about";

export type Route = {
  path: string;
  title: string;
  /** Top-level menu (header navigation). */
  menu: Menu;
  page: PageKey;
  param?: string;
  /** Listed in the menus and search; false keeps an older URL working. */
  nav?: boolean;
  /** A page under a main page (a layer, a country, a data source): listed under its
   * ``group`` heading in the header menu, after the menu's main pages. */
  sub?: boolean;
  group?: string;
  /** Shown as "coming later" (planned data sources). */
  soon?: boolean;
};

export type Menu =
  | "Home"
  | "Forecasts"
  | "Countries"
  | "Bulletin"
  | "Verification"
  | "Monitoring"
  | "Copilot"
  | "Operations";

/** ICPAC member states, alphabetical. */
export const COUNTRIES = [
  "Burundi",
  "Djibouti",
  "Eritrea",
  "Ethiopia",
  "Kenya",
  "Rwanda",
  "Somalia",
  "South Sudan",
  "Sudan",
  "Tanzania",
  "Uganda",
] as const;

export const countrySlug = (name: string) =>
  name.toLowerCase().replaceAll(" ", "-");

/** Header menus: what the service gives, then the staff's own tools. */
export const MENUS: Menu[] = [
  "Forecasts",
  "Countries",
  "Bulletin",
  "Verification",
  "Monitoring",
  "Copilot",
  "Operations",
];

/** The menu for the people who run the service, set apart in the header. */
export const STAFF_MENU: Menu = "Operations";

/** The further rainfall estimates summed from daily files. */
export const DAILY_SOURCES = [
  { id: "arc2", title: "ARC 2.0" },
  { id: "rfe2", title: "RFE 2.0" },
  { id: "imerg", title: "GPM IMERG" },
] as const;

export const ROUTES: Route[] = [
  { path: "", title: "Home", menu: "Home", page: "home" },
  { path: "about", title: "About this service", menu: "Home", page: "about" },
  // Forecasts: this week's outlook, its maps and earlier weeks.
  {
    path: "forecasts",
    title: "Latest forecast",
    menu: "Forecasts",
    page: "forecast",
  },
  {
    path: "maps/rainfall",
    title: "Rainfall maps",
    menu: "Forecasts",
    page: "maps",
    param: "rainfall",
  },
  {
    path: "forecasts/archive",
    title: "Forecast archive",
    menu: "Forecasts",
    page: "archive",
  },
  {
    path: "forecasts/raw",
    title: "Raw ECMWF",
    menu: "Forecasts",
    page: "layer",
    param: "raw",
    sub: true,
    group: "Forecast layers",
  },
  {
    path: "forecasts/mbc",
    title: "MBC",
    menu: "Forecasts",
    page: "layer",
    param: "mbc",
    sub: true,
    group: "Forecast layers",
  },
  {
    path: "forecasts/hybrid",
    title: "MBC + AI/ML",
    menu: "Forecasts",
    page: "layer",
    param: "hybrid",
    sub: true,
    group: "Forecast layers",
  },
  // Countries: one page with all eleven; each opens from it.
  {
    path: "countries",
    title: "All member states",
    menu: "Countries",
    page: "countries",
  },
  ...COUNTRIES.map((name) => ({
    path: "countries/" + countrySlug(name),
    title: name,
    menu: "Countries" as const,
    page: "country" as const,
    param: name,
    sub: true,
    group: "Member states",
  })),
  // Bulletin
  {
    path: "bulletin",
    title: "Weekly bulletin",
    menu: "Bulletin",
    page: "bulletin",
  },
  {
    path: "bulletins",
    title: "Bulletin drafts and review",
    menu: "Bulletin",
    page: "drafts",
  },
  {
    path: "bulletins/action",
    title: "Bulletin decision",
    menu: "Bulletin",
    page: "decision",
    nav: false,
  },
  // Verification: live scores, the independent test and the per-cell maps.
  {
    path: "verification",
    title: "Verification",
    menu: "Verification",
    page: "verification",
  },
  {
    path: "verification/experimental",
    title: "Model evidence 2022–2024",
    menu: "Verification",
    page: "evidence",
  },
  {
    path: "maps/bias",
    title: "Error and skill maps",
    menu: "Verification",
    page: "maps",
    param: "bias",
  },
  {
    path: "maps/rmse",
    title: "RMSE map",
    menu: "Verification",
    page: "maps",
    param: "rmse",
    sub: true,
    group: "Maps by measure",
  },
  {
    path: "maps/correlation",
    title: "Correlation map",
    menu: "Verification",
    page: "maps",
    param: "correlation",
    sub: true,
    group: "Maps by measure",
  },
  {
    path: "maps/skill",
    title: "Skill map",
    menu: "Verification",
    page: "maps",
    param: "skill",
    sub: true,
    group: "Maps by measure",
  },
  {
    path: "monitoring",
    title: "Rainfall monitoring",
    menu: "Monitoring",
    page: "monitoring",
  },
  {
    path: "copilot",
    title: "Forecaster Copilot",
    menu: "Copilot",
    page: "copilot",
  },
  // Operations: the staff's tools.
  {
    path: "data/runs",
    title: "Run the weekly cycle",
    menu: "Operations",
    page: "operations",
  },
  {
    path: "automations",
    title: "Automation",
    menu: "Operations",
    page: "automations",
  },
  { path: "data", title: "Data sources", menu: "Operations", page: "data" },
  {
    path: "models",
    title: "Model registry",
    menu: "Operations",
    page: "models",
  },
  {
    path: "system",
    title: "System status",
    menu: "Operations",
    page: "system",
  },
  {
    path: "data/ecmwf",
    title: "ECMWF ensemble",
    menu: "Operations",
    page: "source",
    param: "ecmwf",
    sub: true,
    group: "Data sources",
  },
  {
    path: "data/chirps",
    title: "CHIRPS",
    menu: "Operations",
    page: "source",
    param: "chirps",
    sub: true,
    group: "Data sources",
  },
  {
    path: "data/tamsat",
    title: "TAMSAT",
    menu: "Operations",
    page: "source",
    param: "tamsat",
    sub: true,
    group: "Data sources",
  },
  ...DAILY_SOURCES.map((source) => ({
    path: "data/" + source.id,
    title: source.title,
    menu: "Operations" as const,
    page: "source" as const,
    param: source.id,
    sub: true,
    group: "Data sources",
  })),
  // Earlier URLs keep working without a place in the menus.
  ...(
    [
      ["forecasts/week-2", "Forecast archive", "Forecasts", "archive"],
      ["models/candidate", "Model registry", "Operations", "models"],
      ["models/production", "Model registry", "Operations", "models"],
      ["system/data", "System status", "Operations", "system"],
      ["system/models", "System status", "Operations", "system"],
      ["system/processing", "System status", "Operations", "system"],
      ["health", "System status", "Operations", "system"],
      ["jobs", "Run the weekly cycle", "Operations", "operations"],
      ["operations", "Run the weekly cycle", "Operations", "operations"],
      ["maps", "Rainfall maps", "Forecasts", "maps"],
    ] as const
  ).map(([path, title, menu, page]) => ({
    path,
    title,
    menu,
    page,
    nav: false,
  })),
];

export function findRoute(path: string): Route | undefined {
  return ROUTES.find((route) => route.path === path.replace(/^\/+|\/+$/g, ""));
}

export function resolveRoute(segments?: string[]): Route | undefined {
  return findRoute((segments ?? []).map(decodeURIComponent).join("/"));
}

export function href(route: Route) {
  return "/" + route.path;
}

/** The main pages of a header menu. */
export function menuRoutes(menu: Menu): Route[] {
  return ROUTES.filter((r) => r.menu === menu && r.nav !== false && !r.sub);
}

/** Everything a header menu lists: its main pages, then each group of pages under them
 * (the layers, the member states, the data sources), so no page has to be hunted for. */
export function menuGroups(
  menu: Menu,
): { label: string | null; routes: Route[] }[] {
  const groups: { label: string | null; routes: Route[] }[] = [
    { label: null, routes: menuRoutes(menu) },
  ];
  for (const route of ROUTES) {
    if (route.menu !== menu || !route.sub || route.nav === false) continue;
    const label = route.group ?? "More";
    const group = groups.find((g) => g.label === label);
    if (group) group.routes.push(route);
    else groups.push({ label, routes: [route] });
  }
  return groups;
}
