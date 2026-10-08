"use client";
/** Renders the view of a route; each view is its own code-split chunk. */
import dynamic from "next/dynamic";
import { findRoute } from "@/features/routes";
import type { PageKey, Route } from "@/features/routes";
import { Skeleton } from "@/components/ui";

/** id: an optional forecast identifier from the URL (?id=). */
export type PageProps = { route: Route; id?: string };

// Views fetch their data in the browser, so they render there only: a control never
// appears before it works (no clicks lost to hydration).
const loading = () => <Skeleton className="h-96" />;
const PAGES: Record<PageKey, React.ComponentType<PageProps>> = {
  overview: dynamic(() => import("@/features/operational/overview"), {
    loading,
    ssr: false,
  }),
  forecast: dynamic(() => import("@/features/operational/forecast"), {
    loading,
    ssr: false,
  }),
  runs: dynamic(() => import("@/features/operational/runs"), {
    loading,
    ssr: false,
  }),
  layer: dynamic(() => import("@/features/operational/layer"), {
    loading,
    ssr: false,
  }),
  maps: dynamic(() => import("@/features/operational/maps"), {
    loading,
    ssr: false,
  }),
  country: dynamic(() => import("@/features/operational/country"), {
    loading,
    ssr: false,
  }),
  verification: dynamic(() => import("@/features/operational/verification"), {
    loading,
    ssr: false,
  }),
  models: dynamic(() => import("@/features/operational/models"), {
    loading,
    ssr: false,
  }),
  "data-ecmwf": dynamic(() => import("@/features/operational/data-ecmwf"), {
    loading,
    ssr: false,
  }),
  "data-chirps": dynamic(() => import("@/features/operational/data-chirps"), {
    loading,
    ssr: false,
  }),
  "data-runs": dynamic(() => import("@/features/operational/runs"), {
    loading,
    ssr: false,
  }),
  bulletin: dynamic(() => import("@/features/operational/bulletin"), {
    loading,
    ssr: false,
  }),
  system: dynamic(() => import("@/features/operational/system"), {
    loading,
    ssr: false,
  }),
  copilot: dynamic(() => import("@/features/workspace"), {
    loading,
    ssr: false,
  }),
  drafts: dynamic(() => import("@/features/workspace"), {
    loading,
    ssr: false,
  }),
  jobs: dynamic(() => import("@/features/workspace"), { loading, ssr: false }),
  settings: dynamic(() => import("@/features/workspace"), {
    loading,
    ssr: false,
  }),
  demo: dynamic(() => import("@/features/demo"), { loading, ssr: false }),
};

export default function View({ path, id }: { path: string; id?: string }) {
  const route = findRoute(path);
  if (!route) return null;
  const Page = PAGES[route.page];
  return <Page route={route} id={id} />;
}
