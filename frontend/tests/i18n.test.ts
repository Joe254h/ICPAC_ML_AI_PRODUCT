import { describe, expect, it } from "vitest";
import { ROUTES, MENUS } from "@/features/routes";
import { SITE_LANGUAGES, hasTranslation, translate } from "@/lib/i18n";

describe("site words", () => {
  it("translates menus and page names, in any letter case", () => {
    expect(translate("Forecasts", "sw")).toBe("Utabiri");
    expect(translate("Forecast Archive", "sw")).toBe("Hifadhi ya utabiri");
    expect(translate("Forecast archive", "fr")).toBe("Archives des prévisions");
  });

  it("keeps English, and words without a translation, as they are", () => {
    expect(translate("Forecast Archive", "en")).toBe("Forecast Archive");
    expect(translate("Kenya", "sw")).toBe("Kenya");
    expect(translate("Forecasts", "om")).toBe("Forecasts");
  });

  it("has every menu and every listed page in each site language", () => {
    // Countries, data sources and forecast layers keep their own names.
    const named = new Set(["country", "source", "layer"]);
    const names = [
      ...MENUS,
      ...ROUTES.filter(
        (route) => route.nav !== false && !named.has(route.page),
      ).map((route) => route.title),
    ];
    const missing = Object.keys(SITE_LANGUAGES)
      .filter((language) => language !== "en")
      .flatMap((language) =>
        names
          .filter((name) => !hasTranslation(name, language))
          .map((name) => `${name} (${language})`),
      );
    expect(missing).toEqual([]);
  });
});
