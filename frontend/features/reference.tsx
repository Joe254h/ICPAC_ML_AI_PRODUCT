"use client";
/** A reference the Copilot cites (an approved guide or the glossary), as a readable page. */
import { Card, ErrorState, PageBanner, Skeleton } from "@/components/ui";
import type { PageProps } from "@/features/view";
import { useApi } from "@/services/hooks";

type Reference = { id: string; title: string; content: string };

/** The reference's text: "#" lines as headings, blank lines between paragraphs. */
function Text({ content }: { content: string }) {
  return (
    <>
      {content
        .split(/\n\s*\n/)
        .map((block) => block.trim())
        .filter(Boolean)
        .map((block, i) => {
          const heading = block.match(/^#+\s+(.*)$/);
          if (heading && !block.includes("\n"))
            return <h3 key={i}>{heading[1]}</h3>;
          return (
            <p key={i} style={{ whiteSpace: "pre-line" }}>
              {block.replace(/^#+\s+/gm, "")}
            </p>
          );
        })}
    </>
  );
}

export default function ReferencePage({ id }: PageProps) {
  const reference = useApi<Reference>(
    id ? `/references/${encodeURIComponent(id)}` : null,
  );
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title={reference.data?.title ?? "Reference"}
          crumbs={[
            { label: "Copilot", href: "/copilot" },
            { label: "Reference" },
          ]}
          subtitle="An approved reference the Forecaster Copilot cites."
        />
        {reference.loading && <Skeleton height={240} />}
        {reference.error && (
          <ErrorState message={reference.error} retry={reference.reload} />
        )}
        {!id && <ErrorState message="No reference was named." />}
        {reference.data && (
          <Card>
            <Text content={reference.data.content} />
          </Card>
        )}
      </div>
    </div>
  );
}
