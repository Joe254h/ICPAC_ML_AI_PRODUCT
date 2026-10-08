import { expect, test } from "vitest";
import {
  COUNTRIES,
  GROUPS,
  ROUTES,
  countrySlug,
  findRoute,
  resolveRoute,
} from "../features/routes";

test("every navigation group of the brief has pages", () => {
  for (const group of GROUPS)
    expect(
      ROUTES.some((r) => r.group === group && r.nav !== false),
      group,
    ).toBe(true);
});

test("the eleven member states each have a country page", () => {
  expect(COUNTRIES).toHaveLength(11);
  for (const name of COUNTRIES)
    expect(findRoute("/countries/" + countrySlug(name))?.param).toBe(name);
  expect(countrySlug("South Sudan")).toBe("south-sudan");
});

test("URLs resolve to routes and unknown ones do not", () => {
  expect(resolveRoute(undefined)?.page).toBe("overview");
  expect(resolveRoute(["forecasts", "hybrid"])?.param).toBe("hybrid");
  expect(resolveRoute(["maps", "skill"])?.page).toBe("maps");
  expect(resolveRoute(["countries", "south-sudan"])?.title).toBe("South Sudan");
  expect(resolveRoute(["nowhere"])).toBeUndefined();
});

test("earlier URLs keep working", () => {
  for (const path of [
    "copilot",
    "bulletins",
    "jobs",
    "models",
    "verification",
    "settings",
    "monitoring",
    "observations",
    "products",
    "health",
  ])
    expect(findRoute(path), path).toBeDefined();
});

test("paths are unique", () => {
  const paths = ROUTES.map((r) => r.path);
  expect(new Set(paths).size).toBe(paths.length);
});
