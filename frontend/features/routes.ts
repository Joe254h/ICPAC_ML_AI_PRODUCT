/**
 * Every page of the workspace: path, navigation group and the view that renders it.
 * The server page validates URLs against this table; the sidebar is built from it.
 */
export type PageKey =
  | "overview"
  | "forecast"
  | "runs"
  | "layer"
  | "maps"
  | "country"
  | "verification"
  | "models"
  | "data-ecmwf"
  | "data-chirps"
  | "data-runs"
  | "bulletin"
  | "system"
  | "copilot"
  | "drafts"
  | "jobs"
  | "demo"
  | "settings";

export type Route = {
  path: string;
  title: string;
  group: string;
  page: PageKey;
  param?: string;
  nav?: boolean;
};

/** ICPAC member states in the order of the navigation brief. */
export const COUNTRIES = [
  "Kenya",
  "Ethiopia",
  "Somalia",
  "Uganda",
  "Tanzania",
  "Rwanda",
  "Burundi",
  "South Sudan",
  "Sudan",
  "Djibouti",
  "Eritrea",
] as const;

export const countrySlug = (name: string) =>
  name.toLowerCase().replaceAll(" ", "-");

export const GROUPS = [
  "Overview",
  "Forecasts",
  "Maps",
  "Countries",
  "Verification",
  "Models",
  "Data",
  "Bulletin",
  "System",
  "Workspace",
] as const;

export const ROUTES: Route[] = [
  { path: "", title: "Overview", group: "Overview", page: "overview" },
  {
    path: "forecasts",
    title: "Latest forecast",
    group: "Forecasts",
    page: "forecast",
  },
  {
    path: "forecasts/week-2",
    title: "Week-2",
    group: "Forecasts",
    page: "runs",
  },
  {
    path: "forecasts/raw",
    title: "Raw ECMWF",
    group: "Forecasts",
    page: "layer",
    param: "raw",
  },
  {
    path: "forecasts/mbc",
    title: "MBC",
    group: "Forecasts",
    page: "layer",
    param: "mbc",
  },
  {
    path: "forecasts/hybrid",
    title: "MBC + AI/ML",
    group: "Forecasts",
    page: "layer",
    param: "hybrid",
  },
  {
    path: "maps/rainfall",
    title: "Rainfall",
    group: "Maps",
    page: "maps",
    param: "rainfall",
  },
  {
    path: "maps/bias",
    title: "Bias",
    group: "Maps",
    page: "maps",
    param: "bias",
  },
  {
    path: "maps/rmse",
    title: "RMSE",
    group: "Maps",
    page: "maps",
    param: "rmse",
  },
  {
    path: "maps/correlation",
    title: "Correlation",
    group: "Maps",
    page: "maps",
    param: "correlation",
  },
  {
    path: "maps/skill",
    title: "Skill",
    group: "Maps",
    page: "maps",
    param: "skill",
  },
  ...COUNTRIES.map((name) => ({
    path: "countries/" + countrySlug(name),
    title: name,
    group: "Countries",
    page: "country" as const,
    param: name,
  })),
  {
    path: "verification",
    title: "Verification",
    group: "Verification",
    page: "verification",
  },
  {
    path: "models",
    title: "Model registry",
    group: "Models",
    page: "models",
    param: "registry",
  },
  {
    path: "models/candidate",
    title: "Candidate models",
    group: "Models",
    page: "models",
    param: "candidate",
  },
  {
    path: "models/production",
    title: "Production models",
    group: "Models",
    page: "models",
    param: "production",
  },
  { path: "data/ecmwf", title: "ECMWF", group: "Data", page: "data-ecmwf" },
  { path: "data/chirps", title: "CHIRPS", group: "Data", page: "data-chirps" },
  {
    path: "data/runs",
    title: "Forecast runs",
    group: "Data",
    page: "data-runs",
  },
  {
    path: "bulletin",
    title: "Weekly product",
    group: "Bulletin",
    page: "bulletin",
  },
  {
    path: "system/data",
    title: "Data status",
    group: "System",
    page: "system",
    param: "data",
  },
  {
    path: "system/models",
    title: "Model status",
    group: "System",
    page: "system",
    param: "models",
  },
  {
    path: "system/processing",
    title: "Processing status",
    group: "System",
    page: "system",
    param: "processing",
  },
  {
    path: "copilot",
    title: "Forecaster Copilot",
    group: "Workspace",
    page: "copilot",
  },
  {
    path: "bulletins",
    title: "Bulletin drafts",
    group: "Workspace",
    page: "drafts",
  },
  { path: "jobs", title: "Pipeline jobs", group: "Workspace", page: "jobs" },
  {
    path: "demo",
    title: "Demonstration",
    group: "Workspace",
    page: "demo",
    param: "overview",
  },
  { path: "settings", title: "Settings", group: "Workspace", page: "settings" },
  // Earlier URLs keep working without a place in the navigation.
  {
    path: "monitoring",
    title: "Demonstration · monitoring",
    group: "Workspace",
    page: "demo",
    param: "monitoring",
    nav: false,
  },
  {
    path: "observations",
    title: "Demonstration · observations",
    group: "Workspace",
    page: "demo",
    param: "observations",
    nav: false,
  },
  {
    path: "products",
    title: "Demonstration · products",
    group: "Workspace",
    page: "demo",
    param: "products",
    nav: false,
  },
  {
    path: "health",
    title: "System health",
    group: "System",
    page: "system",
    param: "all",
    nav: false,
  },
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
