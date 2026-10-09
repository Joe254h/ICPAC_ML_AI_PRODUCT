import { expect, test } from "vitest";
import {
  COUNTRIES,
  MENUS,
  PLANNED_SOURCES,
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

test("planned data sources are listed as coming later", () => {
  for (const source of PLANNED_SOURCES) {
    const route = findRoute("data/" + source.id);
    expect(route?.page, source.id).toBe("source");
    expect(route?.soon, source.id).toBe(true);
  }
  expect(findRoute("data/ecmwf")?.soon).toBeFalsy();
  expect(findRoute("data/chirps")?.soon).toBeFalsy();
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
