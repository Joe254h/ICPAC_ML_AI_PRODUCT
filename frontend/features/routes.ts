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
  | "monitoring"
  | "models"
  | "data"
  | "source"
  | "operations"
  | "bulletin"
  | "drafts"
  | "copilot"
  | "system";

export type Route = {
  path: string;
  title: string;
  /** Top-level menu (header navigation). */
  menu: Menu;
  page: PageKey;
  param?: string;
  /** Listed in the menus and search; false keeps an older URL working. */
  nav?: boolean;
  /** Shown as "coming later" (planned data sources). */
  soon?: boolean;
};

export type Menu =
  | "Home"
  | "Forecasts"
  | "Monitoring"
  | "Maps"
  | "Countries"
  | "Verification"
  | "Bulletin"
  | "Data & Tools"
  | "Copilot";

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

/** Header menus, in the order of the ICPAC website's navigation. */
export const MENUS: Menu[] = [
  "Forecasts",
  "Monitoring",
  "Maps",
  "Countries",
  "Verification",
  "Bulletin",
  "Data & Tools",
  "Copilot",
];

/** Planned observation sources: listed now, readers come later. */
export const PLANNED_SOURCES = [
  { id: "tamsat", title: "TAMSAT" },
  { id: "rfe2", title: "RFE 2.0" },
  { id: "arc2", title: "ARC 2.0" },
  { id: "imerg", title: "GPM IMERG" },
] as const;

export const ROUTES: Route[] = [
  { path: "", title: "Home", menu: "Home", page: "home" },
  {
    path: "forecasts",
    title: "Latest forecast",
    menu: "Forecasts",
    page: "forecast",
  },
  {
    path: "forecasts/raw",
    title: "Raw ECMWF",
    menu: "Forecasts",
    page: "layer",
    param: "raw",
  },
  {
    path: "forecasts/mbc",
    title: "MBC",
    menu: "Forecasts",
    page: "layer",
    param: "mbc",
  },
  {
    path: "forecasts/hybrid",
    title: "MBC + AI/ML",
    menu: "Forecasts",
    page: "layer",
    param: "hybrid",
  },
  {
    path: "forecasts/archive",
    title: "Forecast archive",
    menu: "Forecasts",
    page: "archive",
  },
  {
    path: "maps/rainfall",
    title: "Rainfall maps",
    menu: "Maps",
    page: "maps",
    param: "rainfall",
  },
  {
    path: "maps/bias",
    title: "Bias",
    menu: "Maps",
    page: "maps",
    param: "bias",
  },
  {
    path: "maps/rmse",
    title: "RMSE",
    menu: "Maps",
    page: "maps",
    param: "rmse",
  },
  {
    path: "maps/correlation",
    title: "Correlation",
    menu: "Maps",
    page: "maps",
    param: "correlation",
  },
  {
    path: "maps/skill",
    title: "Skill",
    menu: "Maps",
    page: "maps",
    param: "skill",
  },
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
  })),
  {
    path: "verification",
    title: "Verification",
    menu: "Verification",
    page: "verification",
  },
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
    path: "monitoring",
    title: "Rainfall monitoring",
    menu: "Monitoring",
    page: "monitoring",
  },
  {
    path: "models",
    title: "Model registry",
    menu: "Data & Tools",
    page: "models",
  },
  { path: "data", title: "Data sources", menu: "Data & Tools", page: "data" },
  {
    path: "data/ecmwf",
    title: "ECMWF ensemble",
    menu: "Data & Tools",
    page: "source",
    param: "ecmwf",
  },
  {
    path: "data/chirps",
    title: "CHIRPS",
    menu: "Data & Tools",
    page: "source",
    param: "chirps",
  },
  ...PLANNED_SOURCES.map((source) => ({
    path: "data/" + source.id,
    title: source.title,
    menu: "Data & Tools" as const,
    page: "source" as const,
    param: source.id,
    soon: true,
  })),
  {
    path: "data/runs",
    title: "Operations",
    menu: "Data & Tools",
    page: "operations",
  },
  {
    path: "system",
    title: "System status",
    menu: "Data & Tools",
    page: "system",
  },
  {
    path: "copilot",
    title: "Forecaster Copilot",
    menu: "Copilot",
    page: "copilot",
  },
  // Earlier URLs keep working without a place in the menus.
  ...(
    [
      ["forecasts/week-2", "Forecast archive", "Forecasts", "archive"],
      ["models/candidate", "Model registry", "Data & Tools", "models"],
      ["models/production", "Model registry", "Data & Tools", "models"],
      ["system/data", "System status", "Data & Tools", "system"],
      ["system/models", "System status", "Data & Tools", "system"],
      ["system/processing", "System status", "Data & Tools", "system"],
      ["health", "System status", "Data & Tools", "system"],
      ["jobs", "Operations", "Data & Tools", "operations"],
      ["operations", "Operations", "Data & Tools", "operations"],
      ["maps", "Rainfall maps", "Maps", "maps"],
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

export function menuRoutes(menu: Menu): Route[] {
  return ROUTES.filter((r) => r.menu === menu && r.nav !== false);
}
