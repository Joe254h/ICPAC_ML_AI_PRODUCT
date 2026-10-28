import { expect, test } from "vitest";
import {
  COUNTRIES,
  MENUS,
  DAILY_SOURCES,
  ROUTES,
  countrySlug,
  findRoute,
  menuGroups,
  menuRoutes,
  resolveRoute,
} from "../features/routes";

test("every header menu has pages", () => {
  for (const menu of MENUS)
    expect(menuRoutes(menu).length, menu).toBeGreaterThan(0);
});

test("every page is listed in the header menus, grouped under its main pages", () => {
  for (const menu of MENUS)
    expect(menuRoutes(menu).length, menu).toBeLessThanOrEqual(6);
  const listed = new Set(
    MENUS.flatMap((menu) =>
      menuGroups(menu).flatMap((group) => group.routes.map((r) => r.path)),
    ),
  );
  for (const route of ROUTES.filter(
    (r) => r.nav !== false && r.page !== "home",
  ))
    expect(listed.has(route.path), route.path).toBe(true);
  // Countries, layers and data sources sit under their own headings.
  const countries = menuGroups("Countries");
  expect(countries.map((g) => g.label)).toEqual([null, "Member states"]);
  expect(countries[1].routes).toHaveLength(11);
  expect(menuGroups("Forecasts").map((g) => g.label)).toEqual([
    null,
    "Forecast layers",
  ]);
  expect(
    menuGroups("Operations")
      .at(-1)
      ?.routes.map((r) => r.path),
  ).toContain("data/imerg");
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
