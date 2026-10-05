import type { Source } from "@/types/workflows";
export default function Sources({ sources }: { sources: Source[] }) {
  return (
    <div className="reference-list">
      {sources.map((source) => (
        <details key={source.id}>
          <summary>
            {source.title}
            <span className="badge amber">
              {source.category.replaceAll("_", " ")}
            </span>
          </summary>
          <p>{source.excerpt}</p>
          {source.synthetic && <strong>Synthetic historical example</strong>}
          <small>SHA256 {source.checksum}</small>
          <a
            className="small-link"
            href={source.url}
            target="_blank"
            rel="noreferrer"
          >
            Open source document
          </a>
        </details>
      ))}
    </div>
  );
}
