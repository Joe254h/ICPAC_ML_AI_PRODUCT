"use client";
/** Renders the view of a route; each view is its own code-split chunk. */
import dynamic from "next/dynamic";
import { findRoute } from "@/features/routes";
import type { PageKey, Route } from "@/features/routes";
import { Skeleton } from "@/components/ui";

/** id: an optional identifier from the URL (?id=), e.g. a forecast. */
export type PageProps = { route: Route; id?: string };

// Views fetch their data in the browser, so they render there only: a control never
// appears before it works (no clicks lost to hydration).
const loading = () => (
  <div className="page">
    <div className="wrap">
      <Skeleton height={420} />
    </div>
  </div>
);
const view = (
  load: () => Promise<{ default: React.ComponentType<PageProps> }>,
) => dynamic(load, { loading, ssr: false });

const PAGES: Record<PageKey, React.ComponentType<PageProps>> = {
  home: view(() => import("@/features/home")),
  forecast: view(() => import("@/features/operational/forecast")),
  archive: view(() => import("@/features/operational/archive")),
  layer: view(() => import("@/features/operational/layer")),
  maps: view(() => import("@/features/operational/maps")),
  country: view(() => import("@/features/operational/country")),
  countries: view(() => import("@/features/operational/countries")),
  verification: view(() => import("@/features/operational/verification")),
  monitoring: view(() => import("@/features/operational/monitoring")),
  models: view(() => import("@/features/operational/models")),
  data: view(() => import("@/features/operational/data")),
  source: view(() => import("@/features/operational/source")),
  operations: view(() => import("@/features/operational/operations")),
  bulletin: view(() => import("@/features/operational/bulletin")),
  drafts: view(() => import("@/features/bulletins")),
  copilot: view(() => import("@/features/copilot")),
  system: view(() => import("@/features/operational/system")),
};

export default function View({ path, id }: { path: string; id?: string }) {
  const route = findRoute(path);
  if (!route) return null;
  const Page = PAGES[route.page];
  return <Page route={route} id={id} />;
}
