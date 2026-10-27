import { expect, test } from "vitest";
import {
  COUNTRIES,
  MENUS,
  DAILY_SOURCES,
  ROUTES,
  countrySlug,
  findRoute,
  menuRoutes,
  resolveRoute,
} from "../features/routes";

test("every header menu has pages", () => {
  for (const menu of MENUS)
    expect(menuRoutes(menu).length, menu).toBeGreaterThan(0);
});

test("header menus stay short; the rest is reached from its page and search", () => {
  for (const menu of MENUS)
    expect(menuRoutes(menu).length, menu).toBeLessThanOrEqual(6);
  // Each country, layer and data source has a page, outside the menus.
  for (const path of ["countries/kenya", "forecasts/raw", "data/tamsat"]) {
    const route = findRoute(path);
    expect(route?.sub, path).toBe(true);
    expect(menuRoutes(route!.menu)).not.toContain(route);
  }
  expect(menuRoutes("Countries").map((r) => r.path)).toEqual(["countries"]);
});

test("the eleven member states each have a country page", () => {
  expect(COUNTRIES).toHaveLength(11);
  for (const name of COUNTRIES)
    expect(findRoute("/countries/" + countrySlug(name))?.param).toBe(name);
  expect(countrySlug("South Sudan")).toBe("south-sudan");
});

test("URLs resolve to routes and unknown ones do not", () => {
  expect(resolveRoute(undefined)?.page).toBe("home");
  expect(resolveRoute(["forecasts", "hybrid"])?.param).toBe("hybrid");
  expect(resolveRoute(["maps", "skill"])?.page).toBe("maps");
  expect(resolveRoute(["countries", "south-sudan"])?.title).toBe("South Sudan");
  expect(resolveRoute(["data", "chirps"])?.page).toBe("source");
  expect(resolveRoute(["nowhere"])).toBeUndefined();
});

test("every data source has its page, none of them coming later", () => {
  for (const id of [
    "ecmwf",
    "chirps",
    "tamsat",
    ...DAILY_SOURCES.map((s) => s.id),
  ]) {
    const route = findRoute("data/" + id);
    expect(route?.page, id).toBe("source");
    expect(route?.soon, id).toBeFalsy();
  }
});

test("earlier URLs keep working", () => {
  for (const path of [
    "copilot",
    "bulletins",
    "jobs",
    "models",
    "verification",
    "health",
  ])
    expect(findRoute(path), path).toBeDefined();
});

test("the retired demonstration pages are gone", () => {
  for (const path of [
    "demo",
    "workspace",
    "settings",
    "observations",
    "products",
  ])
    expect(findRoute(path), path).toBeUndefined();
});

test("paths are unique", () => {
  const paths = ROUTES.map((r) => r.path);
  expect(new Set(paths).size).toBe(paths.length);
});
