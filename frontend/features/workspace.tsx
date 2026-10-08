"use client";
/** Workspace tools kept from the first release: Copilot, drafting, jobs, settings. */
import { PageHeader } from "@/components/ui";
import { useApp } from "@/components/shell";
import Workflow from "@/features/workflow";
import type { PageProps } from "@/features/view";

const VIEWS: Record<string, [string, string]> = {
  copilot: [
    "copilot",
    "Ask about forecasts, sources and verification; answers cite the tools and references used.",
  ],
  drafts: [
    "bulletins",
    "Draft, review and approve the ICPAC weekly bulletin, frozen with its Word document and maps.",
  ],
  jobs: ["jobs", "Fixed pipeline stages with dependencies, logs and status."],
  settings: [
    "settings",
    "Versioned scientific configuration served by the API.",
  ],
};

export default function Workspace({ route }: PageProps) {
  const { config, selection, refresh } = useApp();
  const [view, description] = VIEWS[route.page] ?? VIEWS.settings;
  return (
    <>
      <PageHeader title={route.title} description={description} />
      <div className="legacy">
        <Workflow
          view={view}
          selection={selection}
          config={config.data ?? null}
          refresh={refresh}
        />
      </div>
    </>
  );
}
