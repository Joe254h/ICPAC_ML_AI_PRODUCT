"use client";
/** Health component lines ("Healthy · …", "Warning · …", "Unavailable · …") as rows. */
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { Badge, Table } from "@/components/ui";

export function parseStatus(value: string): {
  level: "Healthy" | "Warning" | "Unavailable" | "Info";
  detail: string;
} {
  const [head, ...rest] = value.split(" · ");
  if (head === "Healthy" || head === "Warning" || head === "Unavailable")
    return { level: head, detail: rest.join(" · ") };
  return { level: "Info", detail: value };
}

export function StatusBadge({ level }: { level: string }) {
  if (level === "Healthy")
    return (
      <Badge tone="good" icon={<CheckCircle2 size={13} />}>
        Healthy
      </Badge>
    );
  if (level === "Warning")
    return (
      <Badge tone="warning" icon={<AlertTriangle size={13} />}>
        Warning
      </Badge>
    );
  if (level === "Unavailable")
    return (
      <Badge tone="critical" icon={<XCircle size={13} />}>
        Unavailable
      </Badge>
    );
  return <Badge>Info</Badge>;
}

export function StatusTable({ rows }: { rows: [string, string][] }) {
  return (
    <Table head={["Component", "Status", "Detail"]}>
      {rows.map(([name, value]) => {
        const { level, detail } = parseStatus(value);
        return (
          <tr key={name}>
            <td className="font-medium">{name}</td>
            <td>
              <StatusBadge level={level} />
            </td>
            <td className="text-muted-foreground">{detail || "—"}</td>
          </tr>
        );
      })}
    </Table>
  );
}
