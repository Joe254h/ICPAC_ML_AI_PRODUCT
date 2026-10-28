/**
 * The Copilot's answers as formatted text: headings, bold and italic words, bullet and
 * numbered lists, tables, inline code and links. Everything is built as React elements
 * from the text (no HTML is injected), and only web or site links are made clickable.
 */
import { Fragment } from "react";

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "paragraph"; lines: string[] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^(#{1,4})\s+(.*?)\s*#*$/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function cells(row: string): string[] {
  return row
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((cell) => cell.trim());
}

export function blocks(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const result: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      result.push({
        kind: "heading",
        level: heading[1].length,
        text: heading[2],
      });
      i += 1;
      continue;
    }
    if (
      TABLE_ROW.test(line) &&
      i + 1 < lines.length &&
      TABLE_RULE.test(lines[i + 1])
    ) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && TABLE_ROW.test(lines[i])) {
        rows.push(cells(lines[i]));
        i += 1;
      }
      result.push({ kind: "table", head, rows });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet || numbered) {
      const ordered = !bullet;
      const pattern = ordered ? NUMBERED : BULLET;
      const items: string[] = [];
      while (i < lines.length) {
        const match = pattern.exec(lines[i]);
        if (match) items.push(match[1]);
        else if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length)
          items[items.length - 1] += " " + lines[i].trim();
        else break;
        i += 1;
      }
      result.push({ kind: "list", ordered, items });
      continue;
    }
    const paragraph: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !HEADING.test(lines[i]) &&
      !BULLET.test(lines[i]) &&
      !NUMBERED.test(lines[i]) &&
      !(TABLE_ROW.test(lines[i]) && TABLE_RULE.test(lines[i + 1] ?? ""))
    ) {
      paragraph.push(lines[i]);
      i += 1;
    }
    result.push({ kind: "paragraph", lines: paragraph });
  }
  return result;
}

const INLINE =
  /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;

function safeLink(url: string): string | null {
  if (url.startsWith("/") && !url.startsWith("//")) return url;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

/** Bold, italic, code and links inside one line of text. */
export function Inline({ text }: { text: string }) {
  const parts = text.split(INLINE);
  return (
    <>
      {parts.map((part, i) => {
        if (!part) return null;
        if (/^(\*\*|__).+(\*\*|__)$/.test(part))
          return <strong key={i}>{part.slice(2, -2)}</strong>;
        if (/^`.+`$/.test(part))
          return <code key={i}>{part.slice(1, -1)}</code>;
        const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
        if (link) {
          const url = safeLink(link[2]);
          return url ? (
            <a
              key={i}
              href={url}
              target={url.startsWith("/") ? undefined : "_blank"}
              rel="noreferrer"
            >
              {link[1]}
            </a>
          ) : (
            <Fragment key={i}>{link[1]}</Fragment>
          );
        }
        if (/^([*_]).+\1$/.test(part))
          return <em key={i}>{part.slice(1, -1)}</em>;
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

export default function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      {blocks(text).map((block, i) => {
        if (block.kind === "heading") {
          const Tag = block.level < 4 ? "h3" : "h4";
          return (
            <Tag key={i}>
              <Inline text={block.text} />
            </Tag>
          );
        }
        if (block.kind === "list") {
          const Tag = block.ordered ? "ol" : "ul";
          return (
            <Tag key={i}>
              {block.items.map((item, j) => (
                <li key={j}>
                  <Inline text={item} />
                </li>
              ))}
            </Tag>
          );
        }
        if (block.kind === "table")
          return (
            <div key={i} className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    {block.head.map((cell, j) => (
                      <th key={j}>
                        <Inline text={cell} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, j) => (
                    <tr key={j}>
                      {row.map((cell, k) => (
                        <td key={k}>
                          <Inline text={cell} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        return (
          <p key={i}>
            {block.lines.map((line, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                <Inline text={line} />
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
